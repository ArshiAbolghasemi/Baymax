package tools

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"unicode/utf8"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/httpx"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	"go.uber.org/zap"
)

// Status values a result can report. They are part of the tool contract: a
// model is told to distinguish "the source has nothing" from "the source
// failed", and must not treat the second as evidence of absence.
const (
	// StatusOK means the source answered and the result holds content.
	StatusOK = "ok"
	// StatusNoResults means the source answered and had nothing to say.
	StatusNoResults = "no_results"
	// StatusError means the source could not be retrieved or could not be
	// parsed.
	StatusError = "error"
)

// Argument bounds, matching the schemas hiro's Pydantic models enforced.
const (
	maxQueryChars    = 200
	maxDrugNameChars = 120
)

const retrievalFailureMessage = "The authoritative source is temporarily unavailable or returned invalid data."

// Argument errors. They are values rather than one-off fmt.Errorf calls so a
// caller can match on the kind of mistake, not on the wording.
var (
	errEmptyArgument   = errors.New("must not be empty")
	errArgumentTooLong = errors.New("is too long")
	errUnknownSection  = errors.New("is not a label section")
)

// Failure describes why a retrieval did not produce content. The message is
// deliberately generic; upstream error text is for the log, not for a model
// that might repeat it to a patient.
type Failure struct {
	Type       string `json:"type"`
	Message    string `json:"message"`
	HTTPStatus int    `json:"http_status,omitempty"`
}

// Meta is embedded in every tool result and carries the fields a model needs
// in order to judge and cite an answer.
type Meta struct {
	Status string   `json:"status"`
	Source string   `json:"source"`
	URL    string   `json:"url"`
	Error  *Failure `json:"error,omitempty"`
}

// okMeta returns the meta for a successful call, choosing between ok and
// no_results on whether anything was actually found.
func okMeta(source, sourceURL string, hasContent bool) Meta {
	status := StatusNoResults
	if hasContent {
		status = StatusOK
	}

	return Meta{Status: status, Source: source, URL: sourceURL}
}

// errorMeta returns the meta for a failed retrieval. The source and URL are
// still filled in, so an error result remains attributable.
func errorMeta(source, sourceURL string, err error) Meta {
	return Meta{
		Status: StatusError,
		Source: source,
		URL:    sourceURL,
		Error: &Failure{
			Type:       "retrieval_error",
			Message:    retrievalFailureMessage,
			HTTPStatus: httpx.StatusOf(err),
		},
	}
}

// queryParam is shared by the two free-text search tools.
func queryParam(description string) mcp.ToolOption {
	return mcp.WithString("query",
		mcp.Required(),
		mcp.MinLength(1),
		mcp.MaxLength(maxQueryChars),
		mcp.Description(description),
	)
}

// drugNameParam is shared by the two drug tools.
func drugNameParam() mcp.ToolOption {
	return mcp.WithString("drug_name",
		mcp.Required(),
		mcp.MinLength(1),
		mcp.MaxLength(maxDrugNameChars),
		mcp.Description("Generic or brand drug name."),
	)
}

// normalizeText trims value and rejects it if it is empty or over-long. The
// schema advertises the same bounds, but a client is free to ignore a schema,
// so they are enforced here too.
func normalizeText(value, field string, limit int) (string, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return "", fmt.Errorf("%s: %w", field, errEmptyArgument)
	}

	count := utf8.RuneCountInString(trimmed)
	if count > limit {
		return "", fmt.Errorf("%s %w: at most %d characters, got %d",
			field, errArgumentTooLong, limit, count)
	}

	return trimmed, nil
}

// jsonResult renders a payload as both the structured content and the JSON
// text of a tool result, so a client that reads either one gets the whole
// answer.
func jsonResult(toolName string, payload any) *mcp.CallToolResult {
	encoded, err := json.Marshal(payload)
	if err != nil {
		logging.Logger.Error("failed to encode the tool result",
			zap.String("tool", toolName),
			zap.Error(err),
		)

		return mcp.NewToolResultErrorFromErr("failed to encode tool result", err)
	}

	return mcp.NewToolResultStructured(payload, string(encoded))
}

// invalidArgument logs and reports an argument the caller got wrong. This is
// the one failure reported as a tool error rather than as a result: it is the
// only one the model can fix and retry.
func invalidArgument(toolName string, err error) *mcp.CallToolResult {
	logging.Logger.Warn("tool called with invalid arguments",
		zap.String("tool", toolName),
		zap.Error(err),
	)

	return mcp.NewToolResultError(err.Error())
}

// retrievalFailure answers with a payload that names the failure, without
// marking the call an error.
//
// A model that asked about a drug label needs to be able to say "I could not
// check"; it cannot do that if the call fails at the transport level, and it
// must never read a failure as evidence that nothing exists.
func retrievalFailure(toolName string, payload any, err error) *mcp.CallToolResult {
	logging.Logger.Error("tool retrieval failed",
		zap.String("tool", toolName),
		zap.Int("status_code", httpx.StatusOf(err)),
		zap.Error(err),
	)

	return jsonResult(toolName, payload)
}

// RetrievalStatus exposes the status a result carries, so the server
// middleware can tell a retrieval failure from a healthy call without knowing
// the concrete result type.
func (m Meta) RetrievalStatus() string { return m.Status }

// searchSpec describes a free-text search tool. The two of them differ only in
// what they search and how an empty answer is shaped, so the handler around
// that is written once.
type searchSpec struct {
	toolName  string
	source    string
	sourceURL string
}

// searchHandler validates the query, runs the search, and turns a retrieval
// failure into a result rather than a protocol error.
func searchHandler[T any](
	spec searchSpec,
	run func(context.Context, string) (*T, error),
	onFailure func(query string, meta Meta) *T,
) server.ToolHandlerFunc {
	return func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		raw, err := request.RequireString("query")
		if err != nil {
			return invalidArgument(spec.toolName, err), nil
		}

		query, err := normalizeText(raw, "query", maxQueryChars)
		if err != nil {
			return invalidArgument(spec.toolName, err), nil
		}

		result, err := run(ctx, query)
		if err != nil {
			failure := onFailure(query, errorMeta(spec.source, spec.sourceURL, err))

			return retrievalFailure(spec.toolName, failure, err), nil
		}

		return jsonResult(spec.toolName, result), nil
	}
}

// referenceAnnotations are the hints every tool here carries. They only read
// public reference data, so a client may call them without confirming and may
// retry them safely, and every answer comes from outside this process.
func referenceAnnotations() []mcp.ToolOption {
	return []mcp.ToolOption{
		mcp.WithReadOnlyHintAnnotation(true),
		mcp.WithIdempotentHintAnnotation(true),
		mcp.WithOpenWorldHintAnnotation(true),
	}
}

// newSearchTool builds a complete free-text search tool. The two of them
// differ only in their wording and in what they search, so everything else is
// assembled here.
func newSearchTool[T any](
	spec searchSpec,
	description, queryDescription string,
	run func(context.Context, string) (*T, error),
	onFailure func(query string, meta Meta) *T,
) Tool {
	options := append([]mcp.ToolOption{
		mcp.WithDescription(description),
		queryParam(queryDescription),
		mcp.WithOutputSchema[T](),
	}, referenceAnnotations()...)

	return Tool{
		Def:     mcp.NewTool(spec.toolName, options...),
		Handler: searchHandler(spec, run, onFailure),
	}
}
