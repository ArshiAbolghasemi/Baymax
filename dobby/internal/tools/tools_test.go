package tools

import (
	"io"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/medline"
)

const searchResponse = `<?xml version="1.0"?>
<nlmSearchResult>
  <list>
    <document rank="0" url="https://medlineplus.gov/asthma.html">
      <content name="title">&lt;span&gt;Asthma&lt;/span&gt;</content>
      <content name="FullSummary">Asthma is a chronic disease that affects the airways.</content>
    </document>
  </list>
</nlmSearchResult>`

func TestHealthInfoReturnsTopics(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(writer, searchResponse)
	})

	var result HealthInfoResult

	call(t, set, healthInfoToolName, map[string]any{"query": "  asthma  "}, &result)

	if result.Status != StatusOK {
		t.Fatalf("status = %q, want ok (%+v)", result.Status, result)
	}

	// The query is trimmed before use and echoed back in its normalised form.
	if result.Query != "asthma" {
		t.Errorf("query = %q, want asthma", result.Query)
	}

	if len(result.Results) != 1 {
		t.Fatalf("got %d results, want 1", len(result.Results))
	}

	topic := result.Results[0]

	// Markup inside a content node must not reach the model.
	if topic.Title != "Asthma" {
		t.Errorf("title = %q, want Asthma", topic.Title)
	}

	if !strings.HasPrefix(topic.Summary, "Asthma is a chronic disease") {
		t.Errorf("summary = %q", topic.Summary)
	}

	if topic.URL != "https://medlineplus.gov/asthma.html" {
		t.Errorf("url = %q", topic.URL)
	}

	if result.Source != medline.SourceHealth {
		t.Errorf("source = %q", result.Source)
	}
}

func TestHealthInfoReportsNoResults(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(writer, `<nlmSearchResult><list/></nlmSearchResult>`)
	})

	var result HealthInfoResult

	call(t, set, healthInfoToolName, map[string]any{"query": "asthma"}, &result)

	if result.Status != StatusNoResults {
		t.Fatalf("status = %q, want no_results", result.Status)
	}

	if result.Error != nil {
		t.Errorf("an empty answer must not carry an error: %+v", result.Error)
	}
}

// An unreachable source must surface as a result with status "error", not as a
// protocol failure: the model has to be able to say "I could not check".
func TestHealthInfoReportsRetrievalFailureAsResult(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, _ *http.Request) {
		writer.WriteHeader(http.StatusBadGateway)
	})

	var result HealthInfoResult

	raw := call(t, set, healthInfoToolName, map[string]any{"query": "asthma"}, &result)

	if raw.IsError {
		t.Fatal("a retrieval failure must not be reported as a tool error")
	}

	if result.Status != StatusError {
		t.Fatalf("status = %q, want error", result.Status)
	}

	if result.Error == nil || result.Error.Type != "retrieval_error" {
		t.Fatalf("error = %+v, want a retrieval_error", result.Error)
	}

	if result.Error.HTTPStatus != http.StatusBadGateway {
		t.Errorf("http_status = %d, want 502", result.Error.HTTPStatus)
	}

	// The result is still attributable even though nothing was retrieved.
	if result.Source == "" || result.URL == "" {
		t.Errorf("an error result must still name its source: %+v", result.Meta)
	}
}

func TestRetrievalRetriesUpstream(t *testing.T) {
	var calls atomic.Int32

	set := harness(t, func(writer http.ResponseWriter, _ *http.Request) {
		if calls.Add(1) == 1 {
			writer.WriteHeader(http.StatusBadGateway)

			return
		}

		_, _ = io.WriteString(writer, searchResponse)
	})

	var first HealthInfoResult

	call(t, set, healthInfoToolName, map[string]any{"query": "asthma"}, &first)

	if first.Status != StatusError {
		t.Fatalf("first status = %q, want error", first.Status)
	}

	var second HealthInfoResult

	call(t, set, healthInfoToolName, map[string]any{"query": "asthma"}, &second)

	if second.Status != StatusOK {
		t.Fatalf("second status = %q, want ok", second.Status)
	}
}

func TestSuccessfulResultIsNotCached(t *testing.T) {
	var calls atomic.Int32

	set := harness(t, func(writer http.ResponseWriter, _ *http.Request) {
		calls.Add(1)

		_, _ = io.WriteString(writer, searchResponse)
	})

	for range 3 {
		var result HealthInfoResult

		call(t, set, healthInfoToolName, map[string]any{"query": "asthma"}, &result)

		if result.Status != StatusOK {
			t.Fatalf("status = %q", result.Status)
		}
	}

	if got := calls.Load(); got != 3 {
		t.Fatalf("hit the upstream %d times, want 3", got)
	}
}

func TestInvalidArgumentsAreRejected(t *testing.T) {
	set := harness(t, func(http.ResponseWriter, *http.Request) {
		t.Error("the upstream must not be called for invalid arguments")
	})

	tests := []struct {
		name string
		tool string
		args map[string]any
	}{
		{"blank query", healthInfoToolName, map[string]any{"query": "   "}},
		{"missing query", healthInfoToolName, map[string]any{}},
		{"over-long query", healthInfoToolName, map[string]any{"query": strings.Repeat("a", 201)}},
		{"over-long drug name", drugLabelToolName, map[string]any{"drug_name": strings.Repeat("a", 121)}},
		{"unknown section", drugLabelToolName, map[string]any{"drug_name": "aspirin", "section": "nonsense"}},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			result := call(t, set, test.tool, test.args, nil)
			if !result.IsError {
				t.Fatalf("the call succeeded, want a tool error: %+v", result)
			}
		})
	}
}

const geneticsSearchResponse = `<?xml version="1.0"?>
<nlmSearchResult><list>
  <document rank="0" url="https://medlineplus.gov/genetics/gene/brca1/">
    <content name="title">BRCA1</content>
    <content name="snippet">A gene.</content>
  </document>
</list></nlmSearchResult>`

func TestGeneticsPrefersDetailDocument(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, request *http.Request) {
		if strings.HasPrefix(request.URL.Path, "/wsearch") {
			_, _ = io.WriteString(writer, geneticsSearchResponse)

			return
		}

		_, _ = io.WriteString(writer, `{
			"gene-symbol":"BRCA1",
			"reviewed":"2026-01-01",
			"text-list":[{"text":{"html":"<p>BRCA1 helps <b>repair</b> damaged DNA.</p>"}}],
			"related-health-condition-list":[{"related-health-condition":{"name":"Breast cancer"}}],
			"inheritance-pattern-list":[{"inheritance-pattern":{"memo":"Autosomal dominant"}}]}`)
	})

	var result GeneticsResult

	call(t, set, geneticsToolName, map[string]any{"query": "BRCA1"}, &result)

	if result.Status != StatusOK {
		t.Fatalf("status = %q (%+v)", result.Status, result)
	}

	if len(result.Results) != 1 {
		t.Fatalf("got %d entries, want 1", len(result.Results))
	}

	entry := result.Results[0]
	if entry.Name != "BRCA1" || entry.Type != "gene" {
		t.Errorf("name/type = %q/%q", entry.Name, entry.Type)
	}

	// The detail summary must win over the search snippet.
	if !strings.Contains(entry.Summary, "helps repair damaged DNA") {
		t.Errorf("summary = %q, want the detail text", entry.Summary)
	}

	if len(entry.RelatedConditions) != 1 || entry.RelatedConditions[0] != "Breast cancer" {
		t.Errorf("related conditions = %v", entry.RelatedConditions)
	}

	if len(entry.Inheritance) != 1 || entry.Inheritance[0] != "Autosomal dominant" {
		t.Errorf("inheritance = %v", entry.Inheritance)
	}
}

// If every detail document fails, the search-level entries are still an answer.
func TestGeneticsFallsBackToSearchResults(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, request *http.Request) {
		if strings.HasPrefix(request.URL.Path, "/wsearch") {
			_, _ = io.WriteString(writer, geneticsSearchResponse)

			return
		}

		writer.WriteHeader(http.StatusInternalServerError)
	})

	var result GeneticsResult

	call(t, set, geneticsToolName, map[string]any{"query": "BRCA1"}, &result)

	if result.Status != StatusOK {
		t.Fatalf("status = %q, want ok", result.Status)
	}

	if len(result.Results) != 1 || result.Results[0].Summary != "A gene." {
		t.Fatalf("expected the search-level entry to survive: %+v", result.Results)
	}
}

func TestMalformedUpstreamIsAnError(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(writer, "this is not xml <<<")
	})

	var result HealthInfoResult

	call(t, set, healthInfoToolName, map[string]any{"query": "asthma"}, &result)

	if result.Status != StatusError {
		t.Fatalf("status = %q, want error", result.Status)
	}

	// Nothing was retrieved, so there is no status to report.
	if result.Error == nil || result.Error.HTTPStatus != 0 {
		t.Errorf("error = %+v", result.Error)
	}
}
