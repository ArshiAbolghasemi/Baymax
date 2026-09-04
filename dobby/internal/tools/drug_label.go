package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/httpx"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/textutil"
	"github.com/beevik/etree"
	"github.com/mark3labs/mcp-go/mcp"
	"go.uber.org/zap"
)

const (
	drugLabelToolName = "search_drug_label"

	drugLabelSource    = "DailyMed"
	drugLabelSourceURL = "https://dailymed.nlm.nih.gov/dailymed/"
	drugLabelPageURL   = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="

	// sectionAll requests every section rather than one.
	sectionAll = "all"

	// labelSearchPageSize is how many candidate labels to consider. A common
	// generic has dozens of filings, one per manufacturer.
	labelSearchPageSize = "20"

	// titleChars bounds a section title; a long one is malformed markup rather
	// than a heading.
	titleChars = 200
	// sourceSectionChars bounds one <text> node before the section as a whole
	// is trimmed to the configured budget.
	sourceSectionChars = 20_000
	// identifierChars bounds the names read out of the label body.
	identifierChars = 300

	drugLabelDescription = `Retrieve current official US prescribing-label content from DailyMed.

Use for labeled indications, dosage, contraindications, warnings, adverse
reactions, drug interactions, pregnancy, or clinical pharmacology. This is
official labeling, not a source for FAERS safety-signal or report questions.

Returns a status of "ok", "no_results", or "error". An "error" means the source
could not be reached, never that the drug has no such labeling.`
)

// labelSections maps the section names this tool accepts to the phrases that
// identify them in an SPL document. A label's own section titles vary by
// manufacturer, so matching is by substring over several known spellings, most
// specific first.
var labelSections = []struct {
	name  string
	terms []string
}{
	{"indications", []string{"indications and usage", "indications"}},
	{"dosage", []string{"dosage and administration", "dosage"}},
	{"contraindications", []string{"contraindications"}},
	{"warnings", []string{"warnings and precautions", "boxed warning", "warnings"}},
	{"adverse_reactions", []string{"adverse reactions"}},
	{"drug_interactions", []string{"drug interactions", "interactions"}},
	{"pregnancy", []string{"pregnancy", "use in specific populations"}},
	{"clinical_pharmacology", []string{"clinical pharmacology"}},
}

// sectionNames lists the accepted section values, for the schema enum and for
// validation.
var sectionNames = func() []string {
	names := make([]string, 0, len(labelSections)+1)
	for _, section := range labelSections {
		names = append(names, section.name)
	}

	return append(names, sectionAll)
}()

// LabelMetadata identifies the exact label revision an answer came from, so a
// claim can be traced to a specific document rather than to "DailyMed".
type LabelMetadata struct {
	PublishedDate string `json:"published_date,omitempty"`
	SPLVersion    string `json:"spl_version,omitempty"`
	DocumentID    string `json:"document_id,omitempty"`
	EffectiveTime string `json:"effective_time,omitempty"`
}

// DrugLabelResult is what search_drug_label returns.
//
// Sections is always a map, even when one section was requested, so the shape
// of the result never depends on the arguments.
type DrugLabelResult struct {
	Meta

	Drug        string            `json:"drug"`
	Section     string            `json:"section"`
	Sections    map[string]string `json:"sections"`
	SetID       string            `json:"setid,omitempty"`
	LabelTitle  string            `json:"label_title,omitempty"`
	GenericName string            `json:"generic_name,omitempty"`
	BrandName   string            `json:"brand_name,omitempty"`
	Metadata    *LabelMetadata    `json:"label_metadata,omitempty"`
}

func (s *Set) searchDrugLabel() Tool {
	options := append([]mcp.ToolOption{
		mcp.WithDescription(drugLabelDescription),
		drugNameParam(),
		mcp.WithString("section",
			mcp.DefaultString(sectionAll),
			mcp.Enum(sectionNames...),
			mcp.Description("The official label section to retrieve; defaults to all."),
		),
		mcp.WithOutputSchema[DrugLabelResult](),
	}, referenceAnnotations()...)

	def := mcp.NewTool(drugLabelToolName, options...)

	handler := func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		raw, err := request.RequireString("drug_name")
		if err != nil {
			return invalidArgument(drugLabelToolName, err), nil
		}

		drugName, err := normalizeText(raw, "drug_name", maxDrugNameChars)
		if err != nil {
			return invalidArgument(drugLabelToolName, err), nil
		}

		section := strings.ToLower(strings.TrimSpace(request.GetString("section", sectionAll)))
		if section == "" {
			section = sectionAll
		}

		if !slices.Contains(sectionNames, section) {
			return invalidArgument(drugLabelToolName, fmt.Errorf("%q %w; use one of %s",
				section, errUnknownSection, strings.Join(sectionNames, ", "))), nil
		}

		key := drugName + "\x00" + section

		result, err := cached(ctx, s.cache, drugLabelToolName, key, config.Conf.DrugLabelTTL,
			func(ctx context.Context) (*DrugLabelResult, error) {
				return s.drugLabel(ctx, drugName, section)
			})
		if err != nil {
			return retrievalFailure(drugLabelToolName, &DrugLabelResult{
				Drug:     drugName,
				Section:  section,
				Sections: map[string]string{},
				Meta:     errorMeta(drugLabelSource, drugLabelSourceURL, err),
			}, err), nil
		}

		return jsonResult(drugLabelToolName, result), nil
	}

	return Tool{Def: def, Handler: handler}
}

// splSummary is one entry from the DailyMed label search.
type splSummary struct {
	SetID         string     `json:"setid"`
	Title         string     `json:"title"`
	PublishedDate string     `json:"published_date"`
	SPLVersion    jsonScalar `json:"spl_version"`
}

// drugLabel picks the best matching label and extracts the requested sections.
func (s *Set) drugLabel(ctx context.Context, drugName, section string) (*DrugLabelResult, error) {
	var search struct {
		Data []splSummary `json:"data"`
	}

	err := httpx.GetJSON(ctx, s.client, drugLabelToolName,
		config.Conf.DailyMedURL+"/spls.json", url.Values{
			"drug_name": {drugName},
			"name_type": {"both"},
			"pagesize":  {labelSearchPageSize},
			"page":      {"1"},
		}, &search)
	if err != nil {
		return nil, err
	}

	label, ok := bestLabel(search.Data, drugName)
	if !ok {
		logging.Logger.Info("no matching label",
			zap.String("tool", drugLabelToolName),
			zap.String("drug", drugName),
			zap.Int("candidates", len(search.Data)),
		)

		return &DrugLabelResult{
			Drug:     drugName,
			Section:  section,
			Sections: map[string]string{},
			Meta:     okMeta(drugLabelSource, drugLabelSourceURL, false),
		}, nil
	}

	document, err := s.splDocument(ctx, label.SetID)
	if err != nil {
		return nil, err
	}

	sections := extractSections(document, config.Conf.MaxLabelSectionChars)
	if section != sectionAll {
		sections = onlySection(sections, section)
	}

	logging.Logger.Info("resolved drug label",
		zap.String("tool", drugLabelToolName),
		zap.String("drug", drugName),
		zap.String("setid", label.SetID),
		zap.String("section", section),
		zap.Int("sections", len(sections)),
	)

	result := &DrugLabelResult{
		Drug:       drugName,
		Section:    section,
		Sections:   sections,
		SetID:      label.SetID,
		LabelTitle: label.Title,
		Metadata: &LabelMetadata{
			PublishedDate: label.PublishedDate,
			SPLVersion:    label.SPLVersion.String(),
			DocumentID:    localAttr(document, "id", "root"),
			EffectiveTime: localAttr(document, "effectiveTime", "value"),
		},
		GenericName: descendantText(document, "genericMedicine", "name"),
		BrandName:   descendantText(document, "manufacturedProduct", "name"),
		Meta:        okMeta(drugLabelSource, drugLabelSourceURL, len(sections) > 0),
	}
	result.URL = drugLabelPageURL + url.QueryEscape(label.SetID)

	return result, nil
}

// splDocument fetches and parses one Structured Product Label.
func (s *Set) splDocument(ctx context.Context, setID string) (*etree.Document, error) {
	target := fmt.Sprintf("%s/spls/%s.xml", config.Conf.DailyMedURL, url.PathEscape(setID))

	body, err := httpx.Get(ctx, s.client, drugLabelToolName, target, nil)
	if err != nil {
		return nil, err
	}

	document := etree.NewDocument()

	err = document.ReadFromBytes(body)
	if err != nil {
		return nil, fmt.Errorf("malformed SPL document for setid %s: %w", setID, err)
	}

	return document, nil
}

// onlySection narrows the extracted sections to the one that was asked for.
func onlySection(sections map[string]string, section string) map[string]string {
	narrowed := make(map[string]string, 1)

	text, ok := sections[section]
	if ok {
		narrowed[section] = text
	}

	return narrowed
}

// bestLabel picks the label to answer from. A drug name commonly matches dozens
// of labels — every generic manufacturer files its own — so preference goes to
// a title that actually starts with the requested name, then to the most
// recently published, then to the highest SPL version.
func bestLabel(labels []splSummary, drugName string) (splSummary, bool) {
	if len(labels) == 0 {
		return splSummary{}, false
	}

	needle := strings.ToLower(drugName)
	best, bestScore := labels[0], labelScore(labels[0], needle)

	for index := range labels[1:] {
		candidate := labels[index+1]

		score := labelScore(candidate, needle)
		if score.better(bestScore) {
			best, bestScore = candidate, score
		}
	}

	return best, best.SetID != ""
}

// labelRank orders candidate labels; see bestLabel.
type labelRank struct {
	exact     int
	published time.Time
	version   int
}

func (l labelRank) better(other labelRank) bool {
	switch {
	case l.exact != other.exact:
		return l.exact > other.exact
	case !l.published.Equal(other.published):
		return l.published.After(other.published)
	default:
		return l.version > other.version
	}
}

func labelScore(label splSummary, needle string) labelRank {
	title := strings.ToLower(label.Title)

	exact := 0
	if strings.HasPrefix(title, needle+" ") || strings.HasPrefix(title, needle+"-") {
		exact = 1
	}

	return labelRank{
		exact:     exact,
		published: parseLabelDate(label.PublishedDate),
		version:   label.SPLVersion.int(),
	}
}

// labelDateLayouts are the forms DailyMed states a publication date in. An
// unparsable value sorts oldest rather than failing the call.
var labelDateLayouts = []string{time.RFC1123, time.RFC1123Z, "Jan 2, 2006", "2006-01-02"}

func parseLabelDate(value string) time.Time {
	trimmed := strings.TrimSpace(value)

	for _, layout := range labelDateLayouts {
		parsed, err := time.Parse(layout, trimmed)
		if err == nil {
			return parsed.UTC()
		}
	}

	return time.Time{}
}

// extractSections pulls the sections of interest out of an SPL document.
//
// SPL nests sections arbitrarily deep and repeats a heading across a document's
// parts, so every <section> is examined and same-named matches are joined.
func extractSections(document *etree.Document, maxChars int) map[string]string {
	collected := map[string][]string{}

	for _, section := range document.FindElements("//section") {
		title := strings.ToLower(textutil.FromElement(section.SelectElement("title"), titleChars))
		if title == "" {
			continue
		}

		name, ok := sectionName(title)
		if !ok {
			continue
		}

		body := sectionText(section, maxChars)
		if body != "" && !slices.Contains(collected[name], body) {
			collected[name] = append(collected[name], body)
		}
	}

	sections := make(map[string]string, len(collected))
	for name, parts := range collected {
		sections[name] = strings.Join(parts, "\n\n")
	}

	return sections
}

// sectionName classifies an SPL section title. The first match wins, so
// labelSections is ordered most specific first.
func sectionName(title string) (string, bool) {
	for index := range labelSections {
		if anyContains(title, labelSections[index].terms) {
			return labelSections[index].name, true
		}
	}

	return "", false
}

// sectionText joins a section's text nodes and trims them to the budget.
func sectionText(section *etree.Element, maxChars int) string {
	texts := section.SelectElements("text")
	parts := make([]string, 0, len(texts))

	for _, text := range texts {
		body := textutil.FromElement(text, sourceSectionChars)
		if body != "" {
			parts = append(parts, body)
		}
	}

	return textutil.Clean(strings.Join(parts, " "), maxChars)
}

// descendantText finds the first element named childName anywhere beneath an
// element named parentName, matching on local names so the HL7 namespace does
// not have to be spelled out.
func descendantText(document *etree.Document, parentName, childName string) string {
	for _, parent := range document.FindElements("//" + parentName) {
		for _, child := range parent.FindElements(".//" + childName) {
			text := textutil.FromElement(child, identifierChars)
			if text != "" {
				return text
			}
		}
	}

	return ""
}

// localAttr returns the first non-empty value of the named attribute on the
// first element with the given name.
func localAttr(document *etree.Document, elementName, attribute string) string {
	for _, element := range document.FindElements("//" + elementName) {
		value := strings.TrimSpace(element.SelectAttrValue(attribute, ""))
		if value != "" {
			return value
		}
	}

	return ""
}

func anyContains(haystack string, needles []string) bool {
	for _, needle := range needles {
		if strings.Contains(haystack, needle) {
			return true
		}
	}

	return false
}

// jsonScalar decodes a field the upstream returns sometimes as a string and
// sometimes as a number.
type jsonScalar string

// UnmarshalJSON accepts either JSON form and never fails, so one oddly typed
// field cannot cost the caller the whole document.
func (j *jsonScalar) UnmarshalJSON(data []byte) error {
	var text string

	err := json.Unmarshal(data, &text)
	if err == nil {
		*j = jsonScalar(text)

		return nil
	}

	var number json.Number

	err = json.Unmarshal(data, &number)
	if err == nil {
		*j = jsonScalar(number.String())

		return nil
	}

	*j = ""

	return nil
}

func (j jsonScalar) String() string { return string(j) }

func (j jsonScalar) int() int {
	value, err := strconv.Atoi(string(j))
	if err != nil {
		return 0
	}

	return value
}
