// Package metrics exposes the Prometheus instrumentation for tool calls.
package metrics

import (
	"net/http"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	toolCallRequestRate = promauto.NewCounterVec(prometheus.CounterOpts{
		// Same series names the phoenix dobby exposes, so one dashboard and
		// one alert rule cover every MCP server in the estate.
		Name: "tool_call_request_rate_total",
		Help: "Number of tool calls.",
	}, []string{"status", "name"})

	toolCallResponseTime = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name: "tool_call_response_time",
		Help: "Time spent executing a tool call in seconds.",
	}, []string{"status", "name"})

	// upstreamRequestRate separates a failing source from a failing tool: a
	// tool can answer "no_results" perfectly well while an upstream is down.
	upstreamRequestRate = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "upstream_request_rate_total",
		Help: "Number of outbound requests to an authoritative medical source.",
	}, []string{"status", "source"})

	upstreamResponseTime = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name: "upstream_response_time",
		Help: "Time spent on an outbound request to a medical source in seconds.",
	}, []string{"status", "source"})
)

// Status labels for an observed call.
const (
	StatusSuccess = "success"
	StatusFailed  = "failed"
)

// ObserveToolCall records the outcome and duration of a single tool call.
func ObserveToolCall(name, status string, duration time.Duration) {
	toolCallRequestRate.WithLabelValues(status, name).Inc()
	toolCallResponseTime.WithLabelValues(status, name).Observe(duration.Seconds())
}

// ObserveUpstream records the outcome and duration of one outbound request.
func ObserveUpstream(source, status string, duration time.Duration) {
	upstreamRequestRate.WithLabelValues(status, source).Inc()
	upstreamResponseTime.WithLabelValues(status, source).Observe(duration.Seconds())
}

// Handler serves the metrics and liveness endpoints.
func Handler() http.Handler {
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	return mux
}
