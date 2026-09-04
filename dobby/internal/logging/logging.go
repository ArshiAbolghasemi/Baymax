package logging

import (
	"os"
	"strings"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging/zapconsole"
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// Logger is the process-wide logger. It fans every entry out to a JSON log
// file and to a human-readable console sink.
var Logger *zap.Logger

func init() {
	var err error

	Logger, err = getDoubleLogger()
	if err != nil {
		zap.NewExample().Fatal("Could not initialize logger", zap.String("error", err.Error()))
	}
}

func getDoubleLogger() (*zap.Logger, error) {
	productionEncoderConfig := zap.NewProductionEncoderConfig()
	productionEncoderConfig.EncodeTime = zapcore.ISO8601TimeEncoder

	developmentEncoderConfig := zap.NewDevelopmentEncoderConfig()
	developmentEncoderConfig.ConsoleSeparator = "  "

	level, err := zapcore.ParseLevel(config.Conf.LogLevel)
	if err != nil {
		zap.NewExample().Info("Invalid log level, using info level")

		level = zapcore.InfoLevel
	}

	// Under `go test` the binary is named *.test; writing the JSON sink to a
	// file there would litter every package directory with an access.log.
	outputPath := config.Conf.LogFilePath
	if strings.HasSuffix(os.Args[0], ".test") {
		outputPath = "stderr"
	}

	zapConfig := &zap.Config{
		Level:             zap.NewAtomicLevelAt(level),
		Development:       false,
		DisableCaller:     false,
		DisableStacktrace: false,
		Encoding:          "json",
		EncoderConfig:     productionEncoderConfig,
		OutputPaths:       []string{outputPath},
	}

	fileLogger, err := zapConfig.Build()
	if err != nil {
		return nil, err
	}

	consoleEncoder := zapconsole.NewConsoleEncoder(&developmentEncoderConfig)

	core := zapcore.NewTee(
		fileLogger.Core(),
		zapcore.NewCore(consoleEncoder, zapcore.AddSync(os.Stdout), level),
	)

	return zap.New(core, zap.AddCaller()), nil
}
