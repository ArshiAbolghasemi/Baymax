// Package tools implements every tool dobby exposes over MCP. Each tool lives
// in its own file next to the source it talks to, mirroring the layout of the
// Python hiro agent's tool package this was ported from.
package tools

import (
	"net/http"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/httpx"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	"go.uber.org/zap"
)

// Tool pairs an MCP tool definition with the handler that serves it.
type Tool struct {
	Def     mcp.Tool
	Handler server.ToolHandlerFunc
}

// Set owns the HTTP client shared by the upstream sources.
//
// A single client is enough here because every source is a plain public HTTP
// API with the same timeout and no proxy; connections still pool per host.
type Set struct {
	client *http.Client
}

// New builds the shared client.
func New() (*Set, error) {
	client, err := httpx.NewClient(config.Conf.HTTPTimeout, "")
	if err != nil {
		logging.Logger.Error("failed to build the source client", zap.Error(err))

		return nil, err
	}

	logging.Logger.Info("source client ready",
		zap.Duration("timeout", config.Conf.HTTPTimeout),
		zap.Int("max_retries", config.Conf.HTTPMaxRetries),
	)

	return &Set{client: client}, nil
}

// All returns every tool dobby knows how to serve. Adding a tool means adding
// its constructor here and nothing else.
func (s *Set) All() []Tool {
	return []Tool{
		s.searchHealthInfo(),
		s.searchDrugLabel(),
		s.searchDrugSafety(),
		s.searchGenetics(),
	}
}

// Enabled returns the tools selected by ENABLED_TOOLS, preserving the
// configured order. An empty setting exposes every tool; unknown names are
// ignored.
func (s *Set) Enabled() []Tool {
	all := s.All()

	names := config.Conf.EnabledTools
	if len(names) == 0 {
		return all
	}

	byName := make(map[string]int, len(all))
	for index := range all {
		byName[all[index].Def.Name] = index
	}

	selected := make([]Tool, 0, len(names))

	for _, name := range names {
		index, ok := byName[name]
		if !ok {
			logging.Logger.Warn("ignoring an unknown tool name", zap.String("tool", name))

			continue
		}

		selected = append(selected, all[index])
	}

	return selected
}

// Close releases the resources the set holds.
func (s *Set) Close() {
	logging.Logger.Info("closing the tool resources")
	s.client.CloseIdleConnections()
}
