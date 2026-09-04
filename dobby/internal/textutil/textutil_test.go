package textutil_test

import (
	"strings"
	"testing"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/textutil"
	"github.com/beevik/etree"
)

func TestClean(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name  string
		input string
		limit int
		want  string
	}{
		{"strips tags", "<p>Take <b>two</b> tablets</p>", 100, "Take two tablets"},
		{"unescapes entities", "fever &amp; chills", 100, "fever & chills"},
		{"collapses whitespace", "one\n\n  two\tthree", 100, "one two three"},
		{"no space stranded by a stripped tag", "Repairs <b>DNA</b>.", 100, "Repairs DNA."},
		{"keeps sentence spacing", "Take two. Then rest.", 100, "Take two. Then rest."},
		{"closing bracket", "dose <i>x</i> ) here", 100, "dose x) here"},
		{"empty input", "", 100, ""},
		{"zero limit", "anything", 0, ""},
		{"truncates with ellipsis", "abcdefghij", 5, "abcd…"},
		{"no truncation at exact limit", "abcde", 5, "abcde"},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()

			if got := textutil.Clean(test.input, test.limit); got != test.want {
				t.Errorf("Clean(%q, %d) = %q, want %q", test.input, test.limit, got, test.want)
			}
		})
	}
}

// Truncation must land on a rune boundary: cutting a multi-byte character in
// half would put invalid UTF-8 into a JSON-RPC frame.
func TestCleanTruncatesOnRuneBoundary(t *testing.T) {
	t.Parallel()

	got := textutil.Clean(strings.Repeat("é", 10), 5)
	if want := "éééé…"; got != want {
		t.Fatalf("Clean = %q, want %q", got, want)
	}

	for index, r := range got {
		if r == '�' {
			t.Fatalf("Clean produced invalid UTF-8 at byte %d: %q", index, got)
		}
	}
}

func TestFromElement(t *testing.T) {
	t.Parallel()

	document := etree.NewDocument()

	err := document.ReadFromString(
		`<text>Do not take <b>more</b> than <i>4</i> doses<footnote>see label</footnote></text>`)
	if err != nil {
		t.Fatalf("reading fixture: %v", err)
	}

	got := textutil.FromElement(document.Root(), 200)
	if want := "Do not take more than 4 doses see label"; got != want {
		t.Fatalf("FromElement = %q, want %q", got, want)
	}

	if got := textutil.FromElement(nil, 200); got != "" {
		t.Fatalf("FromElement(nil) = %q, want empty", got)
	}
}
