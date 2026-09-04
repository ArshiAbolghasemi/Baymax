package config

import (
	"testing"
	"time"
)

// load re-reads the configuration into a fresh value, the way init does.
func load(t *testing.T) *Config {
	t.Helper()

	var cfg Config

	err := loadEnvConfig(&cfg)
	if err != nil {
		t.Fatalf("loadEnvConfig: %v", err)
	}

	return &cfg
}

func TestDefaults(t *testing.T) {
	cfg := load(t)

	if cfg.ServerName != "dobby" {
		t.Errorf("server name = %q", cfg.ServerName)
	}

	if cfg.MaxResults != 5 {
		t.Errorf("max results = %d, want 5", cfg.MaxResults)
	}

	if cfg.HTTPTimeout != 15*time.Second {
		t.Errorf("http timeout = %s, want 15s", cfg.HTTPTimeout)
	}

	if cfg.FAERSDisclaimer == "" {
		t.Error("the FAERS disclaimer must never default to empty")
	}
}

// A trailing slash on a base URL would double up in every derived path.
func TestBaseURLsAreNormalized(t *testing.T) {
	t.Setenv("DAILYMED_API_URL", "https://example.test/v2/")
	t.Setenv("MEDLINEPLUS_GENETICS_URL", "https://example.test/genetics/")

	cfg := load(t)

	if cfg.DailyMedURL != "https://example.test/v2" {
		t.Errorf("dailymed = %q", cfg.DailyMedURL)
	}

	if cfg.MedlinePlusGeneticsURL != "https://example.test/genetics" {
		t.Errorf("genetics = %q", cfg.MedlinePlusGeneticsURL)
	}
}

func TestTransientStatusCodes(t *testing.T) {
	cfg := load(t)

	for _, code := range []int{408, 429, 503} {
		if !cfg.IsTransientStatus(code) {
			t.Errorf("%d should be retryable by default", code)
		}
	}

	// openFDA uses 404 for an empty search, so retrying it would triple the
	// load for every drug that simply has no reports.
	if cfg.IsTransientStatus(404) {
		t.Error("404 must not be retryable")
	}
}

func TestTransientStatusOverrideReplacesDefaults(t *testing.T) {
	t.Setenv("MEDICAL_TOOLS_TRANSIENT_STATUS_CODES", "429,503")

	cfg := load(t)

	if !cfg.IsTransientStatus(429) || !cfg.IsTransientStatus(503) {
		t.Errorf("override not applied: %v", cfg.TransientStatus)
	}

	if cfg.IsTransientStatus(500) {
		t.Error("the override should replace the defaults, not extend them")
	}
}

// A typo in a deployment's environment must stop the process, not silently
// serve with a value nobody chose.
func TestInvalidValuesAreRejected(t *testing.T) {
	tests := map[string][2]string{
		"zero results":     {"MEDICAL_TOOLS_MAX_RESULTS", "0"},
		"negative retries": {"MEDICAL_TOOLS_HTTP_MAX_RETRIES", "-1"},
	}

	for name, pair := range tests {
		t.Run(name, func(t *testing.T) {
			t.Setenv(pair[0], pair[1])

			var cfg Config

			err := loadEnvConfig(&cfg)
			if err == nil {
				t.Fatalf("loadEnvConfig accepted %s=%q", pair[0], pair[1])
			}
		})
	}
}
