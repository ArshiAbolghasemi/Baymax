package tools

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/mark3labs/mcp-go/mcp"
)

// harness points every source at one fake upstream and returns a tool set
// wired to it, so no test reaches the real NLM or FDA services.
func harness(t *testing.T, upstream http.HandlerFunc) *Set {
	t.Helper()

	origin := httptest.NewServer(upstream)
	t.Cleanup(origin.Close)

	previous := config.Conf

	t.Cleanup(func() { config.Conf = previous })

	config.Conf = config.Config{
		ServerName:             "dobby-test",
		ServerVersion:          "test",
		MedlinePlusSearchURL:   origin.URL + "/wsearch",
		MedlinePlusGeneticsURL: origin.URL + "/genetics",
		DailyMedURL:            origin.URL + "/dailymed",
		OpenFDAEventURL:        origin.URL + "/openfda",
		SearchToolIdentifier:   "baymax-test",
		MaxResults:             5,
		MaxSummaryChars:        1600,
		MaxLabelSectionChars:   1800,
		HTTPTimeout:            5 * time.Second,
		HTTPMaxRetries:         0,
		RetryMultiplier:        time.Millisecond,
		RetryMaxWait:           2 * time.Millisecond,
		TransientStatus:        []int{http.StatusServiceUnavailable},
		FAERSDisclaimer:        "reports are not incidence",
	}

	set, err := New()
	if err != nil {
		t.Fatalf("building the tool set: %v", err)
	}

	t.Cleanup(set.Close)

	return set
}

// call invokes a tool by name and decodes its structured result into target.
func call(t *testing.T, set *Set, name string, args map[string]any, target any) *mcp.CallToolResult {
	t.Helper()

	var tool Tool

	all := set.All()
	for index := range all {
		if all[index].Def.Name == name {
			tool = all[index]

			break
		}
	}

	if tool.Handler == nil {
		t.Fatalf("no tool named %s", name)
	}

	request := mcp.CallToolRequest{}
	request.Params.Name = name
	request.Params.Arguments = args

	result, err := tool.Handler(t.Context(), request)
	if err != nil {
		t.Fatalf("calling %s: %v", name, err)
	}

	if target != nil {
		encoded, err := json.Marshal(result.StructuredContent)
		if err != nil {
			t.Fatalf("re-encoding the structured content: %v", err)
		}

		err = json.Unmarshal(encoded, target)
		if err != nil {
			t.Fatalf("decoding the structured content: %v\n%s", err, encoded)
		}
	}

	return result
}
