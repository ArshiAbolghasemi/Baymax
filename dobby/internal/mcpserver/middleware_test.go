package mcpserver

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/tools"
	"github.com/mark3labs/mcp-go/mcp"
)

// errBoom stands in for a real failure in these tests.
var errBoom = errors.New("boom")

func TestRedactArgumentsHidesTheQuestion(t *testing.T) {
	redacted := redactArguments(map[string]any{
		"query":     "do I have diabetes",
		"drug_name": "metformin",
		"section":   "warnings",
		"limit":     5,
	})

	// What a person asks is the sensitive part; only its shape may be logged.
	for _, key := range []string{"query", "drug_name"} {
		text, ok := redacted[key].(string)
		if !ok || !strings.HasPrefix(text, "<redacted:") {
			t.Errorf("%s = %v, want a redacted placeholder", key, redacted[key])
		}
	}

	if redacted["section"] != "warnings" || redacted["limit"] != 5 {
		t.Errorf("non-sensitive arguments were altered: %v", redacted)
	}
}

func TestRedactArgumentsHandlesNonStrings(t *testing.T) {
	redacted := redactArguments(map[string]any{"query": 42})
	if redacted["query"] != "<redacted>" {
		t.Errorf("query = %v, want <redacted>", redacted["query"])
	}
}

// A retrieval failure is reported inside a successful result by design. If the
// middleware missed that, a source outage would look healthy on every
// dashboard.
func TestFailedReadsTheResultStatus(t *testing.T) {
	tests := []struct {
		name   string
		result *mcp.CallToolResult
		want   bool
	}{
		{"nil", nil, false},
		{"tool error", &mcp.CallToolResult{IsError: true}, true},
		{
			"retrieval error",
			&mcp.CallToolResult{StructuredContent: tools.Meta{Status: tools.StatusError}},
			true,
		},
		{
			"no results is not a failure",
			&mcp.CallToolResult{StructuredContent: tools.Meta{Status: tools.StatusNoResults}},
			false,
		},
		{
			"ok",
			&mcp.CallToolResult{StructuredContent: tools.Meta{Status: tools.StatusOK}},
			false,
		},
		{"unknown payload", &mcp.CallToolResult{StructuredContent: 42}, false},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := failed(test.result); got != test.want {
				t.Errorf("failed = %v, want %v", got, test.want)
			}
		})
	}
}

func TestInstrumentPassesResultsThrough(t *testing.T) {
	want := mcp.NewToolResultText("done")

	handler := instrument(func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		return want, nil
	})

	request := mcp.CallToolRequest{}
	request.Params.Name = "search_health_info"
	request.Params.Arguments = map[string]any{"query": "asthma"}

	got, err := handler(t.Context(), request)
	if err != nil {
		t.Fatalf("handler: %v", err)
	}

	if got != want {
		t.Errorf("the middleware did not pass the result through")
	}
}

func TestInstrumentPropagatesErrors(t *testing.T) {
	wantErr := errBoom

	handler := instrument(func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		return nil, wantErr
	})

	request := mcp.CallToolRequest{}
	request.Params.Name = "search_health_info"

	_, err := handler(t.Context(), request)
	if !errors.Is(err, wantErr) {
		t.Fatalf("err = %v, want %v", err, wantErr)
	}
}
