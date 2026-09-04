package dobby

import (
	"context"
	"errors"
	"net/http"
	"os/signal"
	"syscall"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/metrics"
	"go.uber.org/zap"
)

// Run owns the whole process lifecycle and returns the exit code, so every
// deferred cleanup still runs before the caller exits.
func Run() int {
	defer func() { _ = logging.Logger.Sync() }()

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	logging.Logger.Info("starting dobby",
		zap.String("environment", config.Conf.Environment),
		zap.String("server_name", config.Conf.ServerName),
		zap.String("server_version", config.Conf.ServerVersion),
		zap.String("log_level", config.Conf.LogLevel),
		zap.String("log_file_path", config.Conf.LogFilePath),
	)

	app, err := NewApp()
	if err != nil {
		logging.Logger.Error("failed to build the app", zap.Error(err))

		return 1
	}

	defer app.Close()

	err = app.Serve(ctx)
	if err != nil {
		logging.Logger.Error("the mcp server stopped with an error", zap.Error(err))

		return 1
	}

	logging.Logger.Info("dobby stopped")

	return 0
}

// serveMetrics exposes /metrics and /healthz until ctx is canceled. It joins
// its own shutdown watcher before returning, so no goroutine outlives the call
// however the listener ends.
func serveMetrics(ctx context.Context) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	server := &http.Server{
		Addr:              config.Conf.MetricsAddr,
		Handler:           metrics.Handler(),
		ReadHeaderTimeout: config.Conf.ShutdownTimeout,
	}

	watcher := make(chan struct{})

	go func() {
		defer close(watcher)

		<-ctx.Done()

		logging.Logger.Info("shutting down the metrics server")

		shutdownCtx, stop := context.WithTimeout(
			context.WithoutCancel(ctx), config.Conf.ShutdownTimeout)
		defer stop()

		err := server.Shutdown(shutdownCtx)
		if err != nil {
			logging.Logger.Error("the metrics server did not shut down cleanly", zap.Error(err))
		}
	}()

	logging.Logger.Info("serving metrics", zap.String("addr", config.Conf.MetricsAddr))

	err := server.ListenAndServe()
	if err != nil && !errors.Is(err, http.ErrServerClosed) {
		logging.Logger.Error("the metrics server stopped with an error", zap.Error(err))
	}

	// Stop the watcher if the listener died on its own, then wait for it.
	cancel()
	<-watcher
}
