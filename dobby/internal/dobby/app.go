// Package dobby wires the process together: the tool set, the MCP server and
// the metrics endpoint.
package dobby

import (
	"context"
	"sync"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/mcpserver"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/tools"
)

// App owns the process-wide resources.
type App struct {
	tools *tools.Set
}

// NewApp builds the tool set.
//
// Nothing is probed at startup: every source is a public HTTP API with no
// credentials, and a source that is briefly down must not stop the server —
// the tools report an unreachable source per call, which is what a model
// needs anyway.
func NewApp() (*App, error) {
	set, err := tools.New()
	if err != nil {
		return nil, err
	}

	return &App{tools: set}, nil
}

// Serve runs the metrics endpoint and the MCP server until ctx is canceled.
// Whichever way the MCP server stops, the metrics server is told to stop too
// and joined, so the process never exits mid-shutdown.
func (a *App) Serve(ctx context.Context) error {
	metricsCtx, stopMetrics := context.WithCancel(ctx)

	var metrics sync.WaitGroup

	metrics.Go(func() {
		serveMetrics(metricsCtx)
	})

	err := mcpserver.Serve(ctx, mcpserver.New(a.tools))

	stopMetrics()
	metrics.Wait()

	return err
}

// Close releases the resources the app holds.
func (a *App) Close() {
	a.tools.Close()
}
