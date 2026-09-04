// Package mcpserver wires dobby's tools onto an MCP server and serves it over
// the configured transport.
package mcpserver

import (
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/tools"
	"github.com/mark3labs/mcp-go/server"
	"go.uber.org/zap"
)

// instructions are handed to the client at initialization, alongside the tools.
// They carry the rules that hold across every tool, so the four descriptions do
// not have to repeat them.
const instructions = `Authoritative medical reference tools for the Baymax assistant.

Every tool returns a status field. "ok" means content was found, "no_results"
means the source was reached and had nothing, and "error" means the source could
not be retrieved — never read an "error" as evidence that something does not
exist. Cite the url field of any result you rely on.

These sources are reference material, not medical advice, and none of them
account for an individual patient. FAERS reaction counts in particular are
spontaneous reports: they are not incidence rates, not probabilities, and not
evidence that a drug caused an event.`

// New builds the MCP server exposing the enabled subset of tools.
func New(set *tools.Set) *server.MCPServer {
	srv := server.NewMCPServer(
		config.Conf.ServerName,
		config.Conf.ServerVersion,
		server.WithInstructions(instructions),
		server.WithToolCapabilities(false),
		server.WithRecovery(),
		// The schemas are generated from the same Go types the handlers
		// return, so they are accurate enough to enforce in both directions.
		server.WithInputSchemaValidation(),
		server.WithOutputSchemaValidation(),
		server.WithToolHandlerMiddleware(instrument),
	)

	enabled := set.Enabled()
	names := make([]string, 0, len(enabled))

	for index := range enabled {
		srv.AddTool(enabled[index].Def, enabled[index].Handler)
		names = append(names, enabled[index].Def.Name)
	}

	logging.Logger.Info("registered mcp tools",
		zap.String("server_name", config.Conf.ServerName),
		zap.String("server_version", config.Conf.ServerVersion),
		zap.Int("count", len(names)),
		zap.Strings("tools", names),
	)

	return srv
}
