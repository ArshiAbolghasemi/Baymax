package medline_test

import (
	"strings"
	"testing"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/medline"
)

const response = `<?xml version="1.0"?>
<nlmSearchResult><list>
  <document rank="0" url="https://medlineplus.gov/genetics/condition/cystic-fibrosis/">
    <content name="title">Cystic fibrosis</content>
    <content name="FullSummary">An inherited disorder.</content>
    <content name="gene">CFTR</content>
  </document>
  <document rank="1" url="https://medlineplus.gov/genetics/gene/brca1/">
    <content name="title">BRCA1</content>
    <content name="snippet">A tumor suppressor.</content>
  </document>
</list></nlmSearchResult>`

func TestParseTopics(t *testing.T) {
	t.Parallel()

	topics, err := medline.ParseTopics(response, 10, 500)
	if err != nil {
		t.Fatalf("ParseTopics: %v", err)
	}

	if len(topics) != 2 {
		t.Fatalf("got %d topics, want 2", len(topics))
	}
	// FullSummary is preferred; snippet is the fallback.
	if topics[0].Summary != "An inherited disorder." {
		t.Errorf("summary = %q", topics[0].Summary)
	}

	if topics[1].Summary != "A tumor suppressor." {
		t.Errorf("fallback summary = %q", topics[1].Summary)
	}

	if topics[0].Source != medline.SourceHealth {
		t.Errorf("source = %q", topics[0].Source)
	}
}

func TestParseTopicsRespectsMaxResults(t *testing.T) {
	t.Parallel()

	topics, err := medline.ParseTopics(response, 1, 500)
	if err != nil {
		t.Fatalf("ParseTopics: %v", err)
	}

	if len(topics) != 1 {
		t.Fatalf("got %d topics, want 1", len(topics))
	}
}

func TestParseTopicsRejectsMalformedXML(t *testing.T) {
	t.Parallel()

	_, err := medline.ParseTopics("<not xml", 5, 500)
	if err == nil {
		t.Fatal("ParseTopics accepted malformed XML")
	}
}

func TestParseGeneticsEntries(t *testing.T) {
	t.Parallel()

	entries, err := medline.ParseGeneticsEntries(response, 10, 500)
	if err != nil {
		t.Fatalf("ParseGeneticsEntries: %v", err)
	}

	if len(entries) != 2 {
		t.Fatalf("got %d entries, want 2", len(entries))
	}

	if entries[0].Type != "condition" || entries[1].Type != "gene" {
		t.Errorf("types = %q, %q", entries[0].Type, entries[1].Type)
	}

	if got := entries[0].RelatedGenes; len(got) != 1 || got[0] != "CFTR" {
		t.Errorf("related genes = %v", got)
	}
	// An entry with no related list must omit it rather than send an empty one.
	if entries[1].RelatedGenes != nil {
		t.Errorf("related genes = %v, want nil", entries[1].RelatedGenes)
	}
}

func TestEntityType(t *testing.T) {
	t.Parallel()

	tests := map[string]string{
		"https://medlineplus.gov/genetics/gene/brca1/":                "gene",
		"https://medlineplus.gov/genetics/condition/cystic-fibrosis/": "condition",
		"https://medlineplus.gov/genetics/chromosome/21/":             "chromosome",
		"https://medlineplus.gov/genetics/mitochondrial-dna/mt-tl1/":  "mitochondrial_dna",
		"https://medlineplus.gov/genetics/understanding/basics/":      "genetics_topic",
		"https://medlineplus.gov/genetics/something-else/":            "genetics_topic",
	}
	for url, want := range tests {
		if got := medline.EntityType(url); got != want {
			t.Errorf("EntityType(%q) = %q, want %q", url, got, want)
		}
	}
}

func TestGeneticsPageURLs(t *testing.T) {
	t.Parallel()

	urls := medline.GeneticsPageURLs(response, 10)

	want := []string{
		"https://medlineplus.gov/genetics/condition/cystic-fibrosis",
		"https://medlineplus.gov/genetics/gene/brca1",
	}
	if len(urls) != len(want) {
		t.Fatalf("got %v, want %v", urls, want)
	}

	for index, url := range urls {
		if url != want[index] {
			t.Errorf("url[%d] = %q, want %q", index, url, want[index])
		}
	}
}

// Only MedlinePlus Genetics pages have a derivable detail document; anything
// else must be ignored rather than turned into a 404.
func TestGeneticsPageURLsIgnoresForeignLinks(t *testing.T) {
	t.Parallel()

	foreign := `<nlmSearchResult><list>
		<document url="https://medlineplus.gov/asthma.html"><content name="title">Asthma</content></document>
		<document url="https://example.test/genetics/gene/x"><content name="title">X</content></document>
	</list></nlmSearchResult>`
	if urls := medline.GeneticsPageURLs(foreign, 10); len(urls) != 0 {
		t.Fatalf("got %v, want none", urls)
	}
}

func TestDetailURL(t *testing.T) {
	t.Parallel()

	got := medline.DetailURL("https://medlineplus.gov/download/genetics/",
		"https://medlineplus.gov/genetics/gene/brca1")
	if want := "https://medlineplus.gov/download/genetics/gene/brca1.json"; got != want {
		t.Fatalf("DetailURL = %q, want %q", got, want)
	}
}

const detail = `{
	"gene-symbol": "BRCA1",
	"reviewed": "2015-09",
	"published": 20250403,
	"text-list": [{"text": {"html": "<p>Repairs <b>DNA</b>.</p>"}}, {"text": {"html": "More text."}}],
	"related-gene-list": [{"related-gene": {"gene-symbol": "BRCA2"}}],
	"related-health-condition-list": [{"related-health-condition": {"name": "Breast cancer"}}],
	"inheritance-pattern-list": [{"inheritance-pattern": {"memo": "Autosomal dominant"}}]}`

func TestParseGeneticsDetail(t *testing.T) {
	t.Parallel()

	entry, err := medline.ParseGeneticsDetail([]byte(detail),
		"https://medlineplus.gov/genetics/gene/brca1", 500)
	if err != nil {
		t.Fatalf("ParseGeneticsDetail: %v", err)
	}

	if entry.Name != "BRCA1" || entry.Type != "gene" {
		t.Errorf("name/type = %q/%q", entry.Name, entry.Type)
	}

	if entry.Summary != "Repairs DNA. More text." {
		t.Errorf("summary = %q", entry.Summary)
	}
	// published arrives as a number here and as a string elsewhere.
	if entry.Published != "20250403" {
		t.Errorf("published = %q", entry.Published)
	}

	if len(entry.RelatedGenes) != 1 || len(entry.RelatedConditions) != 1 || len(entry.Inheritance) != 1 {
		t.Errorf("related lists = %v / %v / %v", entry.RelatedGenes, entry.RelatedConditions, entry.Inheritance)
	}
}

// A document with no gene symbol and no name still needs something to be
// called, or a model gets an unnamed result it cannot refer to.
func TestParseGeneticsDetailNamesFromURL(t *testing.T) {
	t.Parallel()

	entry, err := medline.ParseGeneticsDetail([]byte(`{}`),
		"https://medlineplus.gov/genetics/condition/marfan-syndrome", 500)
	if err != nil {
		t.Fatalf("ParseGeneticsDetail: %v", err)
	}

	if entry.Name != "marfan-syndrome" {
		t.Errorf("name = %q", entry.Name)
	}
}

func TestParseGeneticsDetailRejectsMalformedJSON(t *testing.T) {
	t.Parallel()

	_, err := medline.ParseGeneticsDetail(
		[]byte("{nope"), "https://medlineplus.gov/genetics/gene/x", 500)
	if err == nil {
		t.Fatal("ParseGeneticsDetail accepted malformed JSON")
	}
}

func TestSummaryIsBounded(t *testing.T) {
	t.Parallel()

	long := `{"name":"X","text-list":[{"text":{"html":"` + strings.Repeat("word ", 500) + `"}}]}`

	entry, err := medline.ParseGeneticsDetail([]byte(long), "https://medlineplus.gov/genetics/gene/x", 100)
	if err != nil {
		t.Fatalf("ParseGeneticsDetail: %v", err)
	}

	if count := len([]rune(entry.Summary)); count > 100 {
		t.Fatalf("summary is %d runes, want at most 100", count)
	}
}
