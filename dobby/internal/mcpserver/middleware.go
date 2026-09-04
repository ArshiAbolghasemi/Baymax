package mcpserver

import (
	"context"
	"strconv"
	"time"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/metrics"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/tools"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	"go.uber.org/zap"
)

// sensitiveArgs are never written to the logs verbatim; only their length is.
//
// What a person asks these tools is the health question itself — "query" and
// the drug they are asking about. That is exactly the data that must not sit in
// a log file, so both are redacted and only their shape is kept for tracing.
var sensitiveArgs = map[string]bool{"query": true, "drug_name": true}

// instrument records the duration and outcome of every tool call.
//
// A tool that reports a failed retrieval returns status "error" inside a
// successful result, by design, so the status field is read out of the payload
// rather than inferred from result.IsError alone. Without that, a source outage
// would look like a healthy call on every dashboard.
func instrument(next server.ToolHandlerFunc) server.ToolHandlerFunc {
	return func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		name := request.Params.Name

		logging.Logger.Info("tool call started",
			zap.String("tool", name),
			zap.Any("arguments", redactArguments(request.GetArguments())),
		)

		start := time.Now()
		result, err := next(ctx, request)
		duration := time.Since(start)

		status := metrics.StatusSuccess
		if err != nil || failed(result) {
			status = metrics.StatusFailed
		}

		metrics.ObserveToolCall(name, status, duration)

		fields := []zap.Field{
			zap.String("tool", name),
			zap.String("status", status),
			zap.Duration("duration", duration),
		}

		switch {
		case err != nil:
			logging.Logger.Error("tool call failed", append(fields, zap.Error(err))...)
		case status == metrics.StatusFailed:
			logging.Logger.Warn("tool call returned an error result", fields...)
		default:
			logging.Logger.Info("tool call finished", fields...)
		}

		return result, err
	}
}

// failed reports whether a result represents a failure: either an MCP-level
// tool error, or a retrieval error carried in the result's own status field.
func failed(result *mcp.CallToolResult) bool {
	if result == nil {
		return false
	}

	if result.IsError {
		return true
	}

	structured, ok := result.StructuredContent.(interface{ RetrievalStatus() string })
	if !ok {
		return false
	}

	return structured.RetrievalStatus() == tools.StatusError
}

// redactArguments replaces sensitive argument values with their length so a
// call can still be traced without recording what the user asked about.
func redactArguments(arguments map[string]any) map[string]any {
	redacted := make(map[string]any, len(arguments))

	for key, value := range arguments {
		if !sensitiveArgs[key] {
			redacted[key] = value

			continue
		}

		text, ok := value.(string)
		if ok {
			redacted[key] = "<redacted:" + strconv.Itoa(len(text)) + " chars>"

			continue
		}

		redacted[key] = "<redacted>"
	}

	return redacted
}
