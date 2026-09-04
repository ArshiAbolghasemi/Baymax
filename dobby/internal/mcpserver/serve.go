package mcpserver

import (
	"context"
	"errors"
	"net/http"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/mark3labs/mcp-go/server"
	"go.uber.org/zap"
)

// Serve runs the MCP server over streamable HTTP until ctx is canceled or the
// listener fails.
func Serve(ctx context.Context, srv *server.MCPServer) error {
	httpServer := server.NewStreamableHTTPServer(srv,
		server.WithEndpointPath(config.Conf.HTTPEndpoint),
		server.WithStateLess(config.Conf.HTTPStateless),
	)

	serveErr := make(chan error, 1)

	go func() {
		logging.Logger.Info("serving mcp over streamable http",
			zap.String("addr", config.Conf.HTTPAddr),
			zap.String("endpoint", config.Conf.HTTPEndpoint),
			zap.Bool("stateless", config.Conf.HTTPStateless),
		)

		err := httpServer.Start(config.Conf.HTTPAddr)
		if errors.Is(err, http.ErrServerClosed) {
			err = nil
		}

		serveErr <- err
	}()

	select {
	case err := <-serveErr:
		if err != nil {
			logging.Logger.Error("the http transport stopped with an error", zap.Error(err))
		}

		return err
	case <-ctx.Done():
	}

	logging.Logger.Info("shutting down the http transport",
		zap.Duration("timeout", config.Conf.ShutdownTimeout))

	shutdownCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), config.Conf.ShutdownTimeout)
	defer cancel()

	err := httpServer.Shutdown(shutdownCtx)
	if err != nil {
		logging.Logger.Error("the http transport did not shut down cleanly", zap.Error(err))

		return err
	}

	logging.Logger.Info("the http transport shut down")

	return nil
}
