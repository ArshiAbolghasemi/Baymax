package tools

import (
	"net/http"
	"testing"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
)

func TestAllToolsAreWellFormed(t *testing.T) {
	set := harness(t, func(http.ResponseWriter, *http.Request) {})

	want := []string{
		healthInfoToolName, drugLabelToolName, drugSafetyToolName, geneticsToolName,
	}

	all := set.All()
	if len(all) != len(want) {
		t.Fatalf("got %d tools, want %d", len(all), len(want))
	}

	for index, tool := range all {
		if tool.Def.Name != want[index] {
			t.Errorf("tool[%d] = %q, want %q", index, tool.Def.Name, want[index])
		}

		if tool.Def.Description == "" {
			t.Errorf("tool %s has no description for a model to select on", tool.Def.Name)
		}

		if tool.Handler == nil {
			t.Errorf("tool %s has no handler", tool.Def.Name)
		}

		if len(tool.Def.InputSchema.Properties) == 0 && tool.Def.RawInputSchema == nil {
			t.Errorf("tool %s advertises no input schema", tool.Def.Name)
		}

		hint := tool.Def.Annotations.ReadOnlyHint
		if hint == nil || !*hint {
			t.Errorf("tool %s should be annotated read-only", tool.Def.Name)
		}
	}
}

func TestEnabledSelectsAndOrders(t *testing.T) {
	set := harness(t, func(http.ResponseWriter, *http.Request) {})

	config.Conf.EnabledTools = []string{geneticsToolName, healthInfoToolName}

	enabled := set.Enabled()
	if len(enabled) != 2 {
		t.Fatalf("got %d tools, want 2", len(enabled))
	}

	if enabled[0].Def.Name != geneticsToolName || enabled[1].Def.Name != healthInfoToolName {
		t.Errorf("ENABLED_TOOLS order was not preserved: %s, %s",
			enabled[0].Def.Name, enabled[1].Def.Name)
	}
}

func TestEnabledIgnoresUnknownNames(t *testing.T) {
	set := harness(t, func(http.ResponseWriter, *http.Request) {})

	config.Conf.EnabledTools = []string{"not_a_tool", healthInfoToolName}

	enabled := set.Enabled()
	if len(enabled) != 1 || enabled[0].Def.Name != healthInfoToolName {
		t.Fatalf("unknown names should be ignored, got %d tools", len(enabled))
	}
}

func TestEnabledEmptyExposesEverything(t *testing.T) {
	set := harness(t, func(http.ResponseWriter, *http.Request) {})

	config.Conf.EnabledTools = nil

	if len(set.Enabled()) != len(set.All()) {
		t.Fatal("an empty ENABLED_TOOLS should expose every tool")
	}
}
