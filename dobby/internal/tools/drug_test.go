package tools

import (
	"io"
	"net/http"
	"strings"
	"testing"
)

// openFDA answers 404 when a search matches no reports. That is an answer, and
// conflating it with a failure would let a model read "no reported adverse
// events" out of "we could not reach FDA".
func TestDrugSafetyTreatsNotFoundAsNoResults(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, _ *http.Request) {
		writer.WriteHeader(http.StatusNotFound)
	})

	var result DrugSafetyResult

	call(t, set, drugSafetyToolName, map[string]any{"drug_name": "unobtainium"}, &result)

	if result.Status != StatusNoResults {
		t.Fatalf("status = %q, want no_results", result.Status)
	}

	if result.Error != nil {
		t.Errorf("404 must not be reported as an error: %+v", result.Error)
	}

	// The caveat applies to an absence of reports as much as to their presence.
	if result.Disclaimer == "" {
		t.Error("a drug-safety result must always carry the disclaimer")
	}
}

func TestDrugSafetyAggregatesReactions(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, request *http.Request) {
		query := request.URL.Query()

		switch {
		case query.Get("count") == reactionField:
			_, _ = io.WriteString(writer, `{"meta":{"last_updated":"2026-08-01"},
				"results":[{"term":"NAUSEA","count":120},{"term":"HEADACHE","count":80},{"term":"","count":5}]}`)
		case query.Get("count") == "serious":
			_, _ = io.WriteString(writer, `{"results":[{"term":"1","count":40},{"term":"2","count":160}]}`)
		case query.Get("sort") == "receiptdate:asc":
			_, _ = io.WriteString(writer,
				`{"results":[{"safetyreportid":"1","receiptdate":"20200101","serious":"1","seriousnessdeath":"1"}]}`)
		default:
			_, _ = io.WriteString(writer, `{"results":[{"safetyreportid":"9","receiptdate":"20260801","serious":"2"}]}`)
		}
	})

	var result DrugSafetyResult

	call(t, set, drugSafetyToolName, map[string]any{"drug_name": "aspirin", "limit": 2}, &result)

	if result.Status != StatusOK {
		t.Fatalf("status = %q (%+v)", result.Status, result)
	}

	// The blank term is dropped: an unnamed reaction tells a model nothing.
	if len(result.ReportedEvents) != 2 {
		t.Fatalf("got %d events, want 2: %+v", len(result.ReportedEvents), result.ReportedEvents)
	}

	if result.ReportedEvents[0] != (ReactionCount{Reaction: "NAUSEA", Count: 120}) {
		t.Errorf("first event = %+v", result.ReportedEvents[0])
	}

	if len(result.SeriousnessCounts) != 2 || !result.SeriousnessCounts[0].Serious {
		t.Errorf("seriousness counts = %+v", result.SeriousnessCounts)
	}

	if result.ReportDateRange == nil {
		t.Fatal("no report date range")
	}

	if result.ReportDateRange.From != "20200101" || result.ReportDateRange.To != "20260801" {
		t.Errorf("date range = %+v", result.ReportDateRange)
	}

	if len(result.BoundaryReports) != 2 {
		t.Fatalf("got %d boundary reports, want 2", len(result.BoundaryReports))
	}

	got := result.BoundaryReports[0].SeriousnessCategories
	if len(got) != 1 || got[0] != "death" {
		t.Errorf("seriousness categories = %v, want [death]", got)
	}

	if result.DataLastUpdated != "2026-08-01" {
		t.Errorf("data_last_updated = %q", result.DataLastUpdated)
	}
}

// The enrichment calls only add context. If they fail, the reaction counts the
// caller actually asked for must still come back.
func TestDrugSafetySurvivesFailedEnrichment(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Query().Get("count") != reactionField {
			writer.WriteHeader(http.StatusInternalServerError)

			return
		}

		_, _ = io.WriteString(writer, `{"results":[{"term":"NAUSEA","count":10}]}`)
	})

	var result DrugSafetyResult

	call(t, set, drugSafetyToolName, map[string]any{"drug_name": "aspirin"}, &result)

	if result.Status != StatusOK {
		t.Fatalf("status = %q, want ok", result.Status)
	}

	if len(result.ReportedEvents) != 1 {
		t.Fatalf("events = %+v", result.ReportedEvents)
	}

	if result.ReportDateRange != nil || len(result.BoundaryReports) != 0 {
		t.Errorf("failed enrichment should have been dropped: %+v", result)
	}
}

// FAERS contains transcription errors: a report dated in the year 3004 is
// really in the dataset. A nonsense date must not reach the model as if it
// bounded the reports.
func TestDrugSafetyDropsImplausibleDates(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, request *http.Request) {
		query := request.URL.Query()

		switch {
		case query.Get("count") == reactionField:
			_, _ = io.WriteString(writer, `{"results":[{"term":"NAUSEA","count":10}]}`)
		case query.Get("sort") == "receiptdate:asc":
			_, _ = io.WriteString(writer, `{"results":[{"safetyreportid":"1","receiptdate":"19770215"}]}`)
		default:
			_, _ = io.WriteString(writer, `{"results":[{"safetyreportid":"2","receiptdate":"30040423"}]}`)
		}
	})

	var result DrugSafetyResult

	call(t, set, drugSafetyToolName, map[string]any{"drug_name": "aspirin"}, &result)

	if result.ReportDateRange == nil {
		t.Fatal("the plausible date should still bound the range")
	}

	if result.ReportDateRange.To == "30040423" {
		t.Errorf("range = %+v, want the year-3004 date dropped", result.ReportDateRange)
	}

	for _, report := range result.BoundaryReports {
		if report.ReceiptDate == "30040423" {
			t.Errorf("a boundary report kept an impossible date: %+v", report)
		}
	}
}

const splDocument = `<?xml version="1.0"?>
<document xmlns="urn:hl7-org:v3">
  <id root="doc-123"/>
  <effectiveTime value="20260201"/>
  <component><structuredBody>
    <component><section>
      <title>INDICATIONS AND USAGE</title>
      <text><paragraph>For the relief of <content>mild</content> pain.</paragraph></text>
    </section></component>
    <component><section>
      <title>5.1 Warnings and Precautions</title>
      <text><paragraph>May cause bleeding.</paragraph></text>
    </section></component>
    <component><section>
      <title>Description</title>
      <text><paragraph>Not a section this tool extracts.</paragraph></text>
    </section></component>
  </structuredBody></component>
  <manufacturedProduct><manufacturedProduct>
    <name>BrandCo Aspirin</name>
    <asEntityWithGeneric><genericMedicine><name>aspirin</name></genericMedicine></asEntityWithGeneric>
  </manufacturedProduct></manufacturedProduct>
</document>`

func drugLabelUpstream(t *testing.T) http.HandlerFunc {
	t.Helper()

	return func(writer http.ResponseWriter, request *http.Request) {
		if strings.HasSuffix(request.URL.Path, "/spls.json") {
			// Deliberately unordered, with the exact-title match in the
			// middle, so the selection is doing real work.
			_, _ = io.WriteString(writer, `{"data":[
				{"setid":"old","title":"ASPIRIN AND OXYCODONE tablet","published_date":"Jan 2, 2020","spl_version":"3"},
				{"setid":"newest","title":"ASPIRIN tablet, coated","published_date":"Mar 5, 2026","spl_version":"7"},
				{"setid":"older","title":"ASPIRIN tablet","published_date":"Feb 1, 2019","spl_version":"2"}]}`)

			return
		}

		if !strings.Contains(request.URL.Path, "newest") {
			t.Errorf("fetched label %q, want the newest exact match", request.URL.Path)
		}

		_, _ = io.WriteString(writer, splDocument)
	}
}

func TestDrugLabelExtractsSections(t *testing.T) {
	set := harness(t, drugLabelUpstream(t))

	var result DrugLabelResult

	call(t, set, drugLabelToolName, map[string]any{"drug_name": "aspirin"}, &result)

	if result.Status != StatusOK {
		t.Fatalf("status = %q (%+v)", result.Status, result)
	}

	if result.SetID != "newest" {
		t.Errorf("setid = %q, want newest", result.SetID)
	}

	if got := result.Sections["indications"]; !strings.Contains(got, "relief of mild pain") {
		t.Errorf("indications = %q", got)
	}

	if got := result.Sections["warnings"]; !strings.Contains(got, "May cause bleeding") {
		t.Errorf("warnings = %q", got)
	}

	if _, present := result.Sections["description"]; present {
		t.Error("an unrequested section leaked into the result")
	}

	if result.GenericName != "aspirin" || result.BrandName != "BrandCo Aspirin" {
		t.Errorf("names = %q / %q", result.GenericName, result.BrandName)
	}

	if result.Metadata == nil ||
		result.Metadata.DocumentID != "doc-123" ||
		result.Metadata.EffectiveTime != "20260201" {
		t.Errorf("metadata = %+v", result.Metadata)
	}

	if !strings.Contains(result.URL, "setid=newest") {
		t.Errorf("url = %q, it should cite the exact label", result.URL)
	}
}

// Asking for one section must return only that section, and the shape of the
// result must not change with the arguments.
func TestDrugLabelHonoursSectionArgument(t *testing.T) {
	set := harness(t, drugLabelUpstream(t))

	var result DrugLabelResult

	call(t, set, drugLabelToolName,
		map[string]any{"drug_name": "aspirin", "section": "warnings"}, &result)

	if result.Section != "warnings" {
		t.Errorf("section = %q", result.Section)
	}

	if len(result.Sections) != 1 {
		t.Fatalf("sections = %+v, want only warnings", result.Sections)
	}

	if !strings.Contains(result.Sections["warnings"], "May cause bleeding") {
		t.Errorf("warnings = %q", result.Sections["warnings"])
	}
}

func TestDrugLabelReportsNoMatchingLabel(t *testing.T) {
	set := harness(t, func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(writer, `{"data":[]}`)
	})

	var result DrugLabelResult

	call(t, set, drugLabelToolName, map[string]any{"drug_name": "unobtainium"}, &result)

	if result.Status != StatusNoResults {
		t.Fatalf("status = %q, want no_results", result.Status)
	}
}
