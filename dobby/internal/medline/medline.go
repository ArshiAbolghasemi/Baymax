// Package medline parses the National Library of Medicine search service that
// backs both the health-topic and the genetics tools.
//
// One endpoint (wsearch) serves both, selected by its db parameter, and returns
// the same document shape for each. The two tools differ only in what they make
// of a document, so the parsing lives here once.
package medline

import (
	"fmt"
	"strings"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/textutil"
	"github.com/beevik/etree"
)

// Sources named in results, so a model can attribute a claim.
const (
	SourceHealth   = "MedlinePlus"
	SourceGenetics = "MedlinePlus Genetics"
)

// Public landing pages, used as the result-level citation.
const (
	URLHealth   = "https://medlineplus.gov/healthtopics.html"
	URLGenetics = "https://medlineplus.gov/genetics/"
)

// geneticsPrefix is the page-URL prefix that marks a genetics entity and lets
// its detail document be derived.
const geneticsPrefix = "https://medlineplus.gov/genetics/"

// relatedLimit bounds the related-entity lists attached to a genetics entry.
// These lists can run to hundreds of items upstream, which would crowd out the
// summary that actually answers the question.
const relatedLimit = 10

// inheritanceLimit bounds inheritance-pattern notes on a genetics entry.
const inheritanceLimit = 5

// Topic is one patient-facing health topic.
type Topic struct {
	Title   string `json:"title"   jsonschema_description:"Title of the health topic"`
	Summary string `json:"summary" jsonschema_description:"Plain-language summary of the topic"`
	URL     string `json:"url"     jsonschema_description:"Canonical MedlinePlus page for the topic"`
	Source  string `json:"source"  jsonschema_description:"Publisher of the topic"`
}

// Entry is one genetics entity: a gene, a condition, a chromosome, mitochondrial
// DNA, or a general genetics topic.
type Entry struct {
	Name              string   `json:"name"                         jsonschema_description:"Gene symbol, condition name, or topic name"`
	Type              string   `json:"type"                         jsonschema_description:"gene, condition, chromosome, mitochondrial_dna, or genetics_topic"`
	Summary           string   `json:"summary"                      jsonschema_description:"Plain-language summary of the entity"`
	Source            string   `json:"source"                       jsonschema_description:"Publisher of the entry"`
	URL               string   `json:"url"                          jsonschema_description:"Canonical MedlinePlus Genetics page"`
	RelatedGenes      []string `json:"related_genes,omitempty"      jsonschema_description:"Gene symbols associated with this entity"`
	RelatedConditions []string `json:"related_conditions,omitempty" jsonschema_description:"Health conditions associated with this entity"`
	Inheritance       []string `json:"inheritance,omitempty"        jsonschema_description:"How the condition is inherited"`
	Reviewed          string   `json:"reviewed,omitempty"           jsonschema_description:"Date the entry was last reviewed"`
	Published         string   `json:"published,omitempty"          jsonschema_description:"Date the entry was published"`
}

// entityMarkers map a path fragment to the kind of entity a genetics page
// describes. MedlinePlus encodes it in the path and nowhere else.
var entityMarkers = []struct{ marker, kind string }{
	{"/gene/", "gene"},
	{"/condition/", "condition"},
	{"/chromosome/", "chromosome"},
	{"/mitochondrial-dna/", "mitochondrial_dna"},
	{"/understanding/", "genetics_topic"},
}

// EntityType classifies a genetics page from its URL. MedlinePlus encodes the
// kind of entity in the path, and nothing else in the search response does.
func EntityType(pageURL string) string {
	lowered := strings.ToLower(pageURL)
	for index := range entityMarkers {
		if strings.Contains(lowered, entityMarkers[index].marker) {
			return entityMarkers[index].kind
		}
	}

	return "genetics_topic"
}

// DetailURL maps a genetics page URL to the JSON document behind it, under the
// configured download base.
func DetailURL(base, pageURL string) string {
	path := strings.Trim(strings.TrimPrefix(pageURL, geneticsPrefix), "/")
	return fmt.Sprintf("%s/%s.json", strings.TrimRight(base, "/"), path)
}

// document is one search hit, flattened out of the response XML.
type document struct {
	url string
	// fields maps a lower-cased content name ("title", "fullsummary") to every
	// value carrying it; the service repeats a name for multi-valued fields.
	fields map[string][]string
}

// parse reads the wsearch response into documents, capping both the number of
// hits and the length of each field.
func parse(xmlText string, maxResults, maxSummaryChars int) ([]document, error) {
	doc := etree.NewDocument()

	err := doc.ReadFromString(xmlText)
	if err != nil {
		return nil, fmt.Errorf("malformed search response: %w", err)
	}

	elements := doc.FindElements("//document")
	if len(elements) > maxResults {
		elements = elements[:maxResults]
	}

	documents := make([]document, 0, len(elements))
	for _, element := range elements {
		parsed := document{url: element.SelectAttrValue("url", ""), fields: map[string][]string{}}
		for _, content := range element.SelectElements("content") {
			name := strings.ToLower(content.SelectAttrValue("name", ""))
			parsed.fields[name] = append(parsed.fields[name], textutil.FromElement(content, maxSummaryChars))
		}

		documents = append(documents, parsed)
	}

	return documents, nil
}

// first returns the first non-empty value stored under any of names.
func (d document) first(names ...string) string {
	for _, name := range names {
		for _, value := range d.fields[name] {
			if trimmed := strings.TrimSpace(value); trimmed != "" {
				return trimmed
			}
		}
	}

	return ""
}

// ParseTopics reads a db=healthTopics response into health topics. Documents
// carrying neither a title nor a URL are dropped: there is nothing a model
// could cite.
func ParseTopics(xmlText string, maxResults, maxSummaryChars int) ([]Topic, error) {
	documents, err := parse(xmlText, maxResults, maxSummaryChars)
	if err != nil {
		return nil, err
	}

	topics := make([]Topic, 0, len(documents))
	for _, parsed := range documents {
		title := parsed.first("title")
		if title == "" && parsed.url == "" {
			continue
		}

		topics = append(topics, Topic{
			Title:   title,
			Summary: parsed.first("fullsummary", "snippet"),
			URL:     parsed.url,
			Source:  SourceHealth,
		})
	}

	return topics, nil
}

// ParseGeneticsEntries reads a db=ghr response into genetics entries. These are
// the search-level summaries; the genetics tool enriches them from each page's
// detail document when it can.
func ParseGeneticsEntries(xmlText string, maxResults, maxSummaryChars int) ([]Entry, error) {
	documents, err := parse(xmlText, maxResults, maxSummaryChars)
	if err != nil {
		return nil, err
	}

	entries := make([]Entry, 0, len(documents))
	for _, parsed := range documents {
		title := parsed.first("title")
		if title == "" && parsed.url == "" {
			continue
		}

		entry := Entry{
			Name:    title,
			Type:    EntityType(parsed.url),
			Summary: parsed.first("fullsummary", "snippet"),
			Source:  SourceGenetics,
			URL:     parsed.url,
		}
		entry.RelatedGenes = capped(append(parsed.fields["gene"], parsed.fields["genes"]...), relatedLimit)
		entry.RelatedConditions = capped(append(parsed.fields["condition"], parsed.fields["conditions"]...), relatedLimit)
		entries = append(entries, entry)
	}

	return entries, nil
}

// GeneticsPageURLs collects the genetics page URLs a response points at, in
// result order and without duplicates. The service returns the page URL on the
// document element; some responses instead carry it as a <url> child of a
// <result>, so both shapes are read.
func GeneticsPageURLs(xmlText string, maxResults int) []string {
	doc := etree.NewDocument()

	err := doc.ReadFromString(xmlText)
	if err != nil {
		return nil
	}

	seen := map[string]bool{}

	var urls []string

	add := func(candidate string) {
		candidate = strings.TrimRight(strings.TrimSpace(candidate), "/")
		if !strings.HasPrefix(candidate, geneticsPrefix) || seen[candidate] || len(urls) >= maxResults {
			return
		}

		seen[candidate] = true
		urls = append(urls, candidate)
	}

	for _, element := range doc.FindElements("//document") {
		add(element.SelectAttrValue("url", ""))
	}

	for _, element := range doc.FindElements("//result/url") {
		add(element.Text())
	}

	return urls
}

func capped(values []string, limit int) []string {
	cleaned := make([]string, 0, len(values))
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			cleaned = append(cleaned, trimmed)
		}
	}

	if len(cleaned) == 0 {
		return nil
	}

	if len(cleaned) > limit {
		cleaned = cleaned[:limit]
	}

	return cleaned
}
