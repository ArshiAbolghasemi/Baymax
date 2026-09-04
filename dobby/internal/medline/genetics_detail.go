package medline

import (
	"encoding/json"
	"fmt"
	"path"
	"strings"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/textutil"
)

// flexString decodes a field that MedlinePlus Genetics sometimes returns as a
// string and sometimes as a number. Anything else decodes to "" rather than
// failing the whole document, because one odd field should not cost the caller
// an entire entry.
type flexString string

// UnmarshalJSON accepts a string or a number and never fails, so a single
// oddly typed field does not discard an otherwise usable document.
func (f *flexString) UnmarshalJSON(data []byte) error {
	var asString string

	err := json.Unmarshal(data, &asString)
	if err == nil {
		*f = flexString(asString)

		return nil
	}

	var asNumber json.Number

	err = json.Unmarshal(data, &asNumber)
	if err == nil {
		*f = flexString(asNumber.String())

		return nil
	}

	*f = ""

	return nil
}

func (f flexString) String() string { return strings.TrimSpace(string(f)) }

// geneticsDetail mirrors the download/genetics/<page>.json document. Every list
// wraps its items in a single-key object named after the item, which is why
// each list element needs its own struct rather than a bare value.
type geneticsDetail struct {
	GeneSymbol flexString `json:"gene-symbol"`
	Name       flexString `json:"name"`
	Reviewed   flexString `json:"reviewed"`
	Published  flexString `json:"published"`

	TextList []struct {
		Text struct {
			HTML flexString `json:"html"`
		} `json:"text"`
	} `json:"text-list"`

	RelatedGeneList []struct {
		RelatedGene struct {
			GeneSymbol flexString `json:"gene-symbol"`
		} `json:"related-gene"`
	} `json:"related-gene-list"`

	RelatedConditionList []struct {
		RelatedCondition struct {
			Name flexString `json:"name"`
		} `json:"related-health-condition"`
	} `json:"related-health-condition-list"`

	InheritanceList []struct {
		InheritancePattern struct {
			Memo flexString `json:"memo"`
		} `json:"inheritance-pattern"`
	} `json:"inheritance-pattern-list"`
}

// ParseGeneticsDetail turns one genetics detail document into an Entry.
// pageURL supplies the citation and the entity type, neither of which the
// document itself states unambiguously.
func ParseGeneticsDetail(payload []byte, pageURL string, maxSummaryChars int) (Entry, error) {
	var detail geneticsDetail

	err := json.Unmarshal(payload, &detail)
	if err != nil {
		return Entry{}, fmt.Errorf("malformed genetics detail for %s: %w", pageURL, err)
	}

	// The summary is a sequence of HTML fragments; Clean strips the markup and
	// enforces the budget once, over the joined text.
	fragments := make([]string, 0, len(detail.TextList))
	for _, item := range detail.TextList {
		if html := item.Text.HTML.String(); html != "" {
			fragments = append(fragments, html)
		}
	}

	entry := Entry{
		Name:      detailName(&detail, pageURL),
		Type:      EntityType(pageURL),
		Summary:   textutil.Clean(strings.Join(fragments, " "), maxSummaryChars),
		Source:    SourceGenetics,
		URL:       pageURL,
		Reviewed:  detail.Reviewed.String(),
		Published: detail.Published.String(),
	}

	genes := make([]string, 0, len(detail.RelatedGeneList))
	for _, item := range detail.RelatedGeneList {
		genes = append(genes, item.RelatedGene.GeneSymbol.String())
	}

	conditions := make([]string, 0, len(detail.RelatedConditionList))
	for _, item := range detail.RelatedConditionList {
		conditions = append(conditions, item.RelatedCondition.Name.String())
	}

	inheritance := make([]string, 0, len(detail.InheritanceList))
	for _, item := range detail.InheritanceList {
		inheritance = append(inheritance, item.InheritancePattern.Memo.String())
	}

	entry.RelatedGenes = capped(genes, relatedLimit)
	entry.RelatedConditions = capped(conditions, relatedLimit)
	entry.Inheritance = capped(inheritance, inheritanceLimit)

	return entry, nil
}

// detailName prefers the gene symbol, then the document name, and finally the
// last path segment of the page URL so an entry is never left unnamed.
func detailName(detail *geneticsDetail, pageURL string) string {
	if symbol := detail.GeneSymbol.String(); symbol != "" {
		return symbol
	}

	if name := detail.Name.String(); name != "" {
		return name
	}

	return path.Base(strings.TrimRight(pageURL, "/"))
}
