// Package config loads the whole dobby configuration from the environment
// (and an optional .env file) into a single global Conf value.
package config

import (
	"errors"
	"os"
	"reflect"
	"slices"
	"strings"
	"time"

	"github.com/go-playground/validator/v10"
	"github.com/spf13/viper"
	"go.uber.org/zap"
)

// Config contains the application configuration.
//
// Every setting is read from an environment variable named after its
// `mapstructure` tag (upper-cased); `mapdefault` supplies the fallback used
// when the variable is unset.
//
// The source and limit variables deliberately reuse the names hiro's Python
// configuration already reads, so one .env or one ConfigMap configures both
// processes and they cannot drift apart.
type Config struct {
	Environment string `mapdefault:"local"        mapstructure:"environment"`
	LogLevel    string `mapdefault:"INFO"         mapstructure:"log_level"`
	LogFilePath string `mapdefault:"./access.log" mapstructure:"log_file_path"`

	// MCP server.
	ServerName      string        `mapdefault:"dobby" mapstructure:"server_name"`
	ServerVersion   string        `mapdefault:"0.1.0" mapstructure:"server_version"`
	HTTPAddr        string        `mapdefault:":8080" mapstructure:"mcp_http_addr"`
	HTTPEndpoint    string        `mapdefault:"/mcp"  mapstructure:"mcp_http_endpoint"`
	HTTPStateless   bool          `mapdefault:"true"  mapstructure:"mcp_http_stateless"`
	ShutdownTimeout time.Duration `mapdefault:"30s"   mapstructure:"shutdown_timeout"`
	MetricsAddr     string        `mapdefault:":2112" mapstructure:"metrics_addr"`

	// EnabledTools selects which tools the server exposes, in the given order.
	// Unknown names are ignored; an empty value exposes every tool.
	EnabledTools []string `mapdefault:"" mapstructure:"enabled_tools"`

	// Upstream medical sources. None of them needs a key.
	MedlinePlusSearchURL   string `mapdefault:"https://wsearch.nlm.nih.gov/ws/query"              mapstructure:"medlineplus_search_url"`
	MedlinePlusGeneticsURL string `mapdefault:"https://medlineplus.gov/download/genetics"         mapstructure:"medlineplus_genetics_url"`
	DailyMedURL            string `mapdefault:"https://dailymed.nlm.nih.gov/dailymed/services/v2" mapstructure:"dailymed_api_url"`
	OpenFDAEventURL        string `mapdefault:"https://api.fda.gov/drug/event.json"               mapstructure:"openfda_event_url"`

	// SearchToolIdentifier is the caller name sent to the NLM search service,
	// which asks automated clients to identify themselves.
	SearchToolIdentifier string `mapdefault:"baymax" mapstructure:"medical_tools_search_identifier"`

	// Response budgets. Every one is a hard cap applied after retrieval, so a
	// verbose source cannot blow up a client's context window.
	MaxResults           int `mapdefault:"5"    mapstructure:"medical_tools_max_results"             validate:"min=1,max=50"`
	MaxSummaryChars      int `mapdefault:"1600" mapstructure:"medical_tools_max_summary_chars"       validate:"min=100"`
	MaxLabelSectionChars int `mapdefault:"1800" mapstructure:"medical_tools_max_label_section_chars" validate:"min=100"`

	// Outbound HTTP: timeouts and the bounded, transient-only retry policy.
	HTTPTimeout     time.Duration `mapdefault:"15s"                         mapstructure:"medical_tools_http_timeout"`
	HTTPMaxRetries  int           `mapdefault:"2"                           mapstructure:"medical_tools_http_max_retries"       validate:"min=0,max=10"`
	RetryMultiplier time.Duration `mapdefault:"250ms"                       mapstructure:"medical_tools_http_retry_multiplier"`
	RetryMaxWait    time.Duration `mapdefault:"2s"                          mapstructure:"medical_tools_http_retry_max_wait"`
	TransientStatus []int         `mapdefault:"408,425,429,500,502,503,504" mapstructure:"medical_tools_transient_status_codes"`

	// FAERSDisclaimer is attached to every drug-safety result. It is a setting
	// rather than a constant so a deployment can meet its own regulatory
	// wording without a code change.
	FAERSDisclaimer string `mapdefault:"FAERS reports do not establish that the drug caused the reported event. Counts are reports, not incidence rates or probabilities." mapstructure:"faers_disclaimer"`
}

// Conf is the process-wide configuration, populated once at startup.
var Conf Config

func init() {
	err := loadEnvConfig(&Conf)
	if err != nil && !strings.HasSuffix(os.Args[0], ".test") {
		zap.NewExample().Fatal("failed to load config", zap.String("error", err.Error()))
	}
}

func loadEnvConfig(cfg *Config) error {
	viper.AutomaticEnv()
	viper.AllowEmptyEnv(true)
	viper.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	setupDefaults()
	viper.SetConfigName(".env")
	viper.SetConfigType("env")
	viper.AddConfigPath(".")

	err := viper.ReadInConfig()
	if err != nil {
		if _, ok := errors.AsType[viper.ConfigFileNotFoundError](err); !ok {
			return err
		}
	}

	err = viper.Unmarshal(cfg)
	if err != nil {
		return err
	}

	normalize(cfg)

	return validator.New().Struct(cfg)
}

// normalize applies the fixup the raw settings cannot express: a trailing
// slash on a base URL would double up in every derived path.
func normalize(cfg *Config) {
	cfg.DailyMedURL = strings.TrimRight(cfg.DailyMedURL, "/")
	cfg.MedlinePlusGeneticsURL = strings.TrimRight(cfg.MedlinePlusGeneticsURL, "/")
}

func setupDefaults() {
	confType := reflect.TypeFor[Config]()
	for field := range confType.Fields() {
		viper.SetDefault(field.Tag.Get("mapstructure"), field.Tag.Get("mapdefault"))
	}
}

// IsTransientStatus reports whether an upstream status is worth another try.
func (c *Config) IsTransientStatus(status int) bool {
	return slices.Contains(c.TransientStatus, status)
}
