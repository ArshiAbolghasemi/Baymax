package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/httpx"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/mark3labs/mcp-go/mcp"
	"go.uber.org/zap"
)

const (
	drugSafetyToolName = "search_drug_safety"

	drugSafetySource    = "openFDA / FAERS"
	drugSafetySourceURL = "https://open.fda.gov/apis/drug/event/"

	// openFDA query parameters.
	paramSearch = "search"
	paramCount  = "count"
	paramLimit  = "limit"
	paramSort   = "sort"

	// reactionField aggregates reports by MedDRA preferred term.
	reactionField = "patient.reaction.reactionmeddrapt.exact"

	// Reaction-count bounds, matching the schema hiro's agent was given.
	defaultSafetyLimit = 10
	minSafetyLimit     = 1
	maxSafetyLimit     = 25

	// seriousnessLimit covers the handful of buckets the serious flag has.
	seriousnessLimit = "10"
	// boundaryLimit fetches a single report at each end of the date range.
	boundaryLimit = "1"

	// receiptDateLayout is how FAERS states a report's receipt date.
	receiptDateLayout = "20060102"
	// earliestFAERSYear predates the oldest report in the dataset.
	earliestFAERSYear = 1968

	drugSafetyDescription = `Summarize reported adverse events and safety reports from openFDA/FAERS.

Use for reported adverse events, FAERS reports, safety signals, or recent
drug-safety reports. Counts are spontaneous reports and must never be treated
as incidence, probability, or proof that the drug caused an event.

Returns a status of "ok", "no_results", or "error". An "error" means the source
could not be reached; only "no_results" means no reports were found.`
)

// ReactionCount is one reported adverse reaction and how many reports named it.
type ReactionCount struct {
	Reaction string `json:"reaction"`
	Count    int    `json:"count"`
}

// SeriousnessCount splits the report total by whether it was flagged serious.
type SeriousnessCount struct {
	Serious bool `json:"serious"`
	Count   int  `json:"count"`
}

// DateRange bounds the reports the aggregates were drawn from.
type DateRange struct {
	From string `json:"from"`
	To   string `json:"to"`
}

// ReportSummary describes one individual report at the edge of the range.
type ReportSummary struct {
	SafetyReportID        string   `json:"safety_report_id,omitempty"`
	ReceiptDate           string   `json:"receipt_date,omitempty"`
	Serious               bool     `json:"serious"`
	SeriousnessCategories []string `json:"seriousness_categories,omitempty"`
}

// DrugSafetyResult is what search_drug_safety returns.
type DrugSafetyResult struct {
	Meta

	Drug              string             `json:"drug"`
	ReportedEvents    []ReactionCount    `json:"reported_events"`
	SeriousnessCounts []SeriousnessCount `json:"seriousness_counts,omitempty"`
	ReportDateRange   *DateRange         `json:"report_date_range,omitempty"`
	BoundaryReports   []ReportSummary    `json:"boundary_reports,omitempty"`
	DataLastUpdated   string             `json:"data_last_updated,omitempty"`
	// Disclaimer is attached to every result, errors included, because the
	// caveat applies to the absence of data as much as to its presence.
	Disclaimer string `json:"disclaimer"`
}

func (s *Set) searchDrugSafety() Tool {
	options := append([]mcp.ToolOption{
		mcp.WithDescription(drugSafetyDescription),
		drugNameParam(),
		mcp.WithNumber("limit",
			mcp.DefaultNumber(defaultSafetyLimit),
			mcp.Min(minSafetyLimit),
			mcp.Max(maxSafetyLimit),
			mcp.Description("Maximum reaction aggregates to return."),
		),
		mcp.WithOutputSchema[DrugSafetyResult](),
	}, referenceAnnotations()...)

	def := mcp.NewTool(drugSafetyToolName, options...)

	handler := func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		raw, err := request.RequireString("drug_name")
		if err != nil {
			return invalidArgument(drugSafetyToolName, err), nil
		}

		drugName, err := normalizeText(raw, "drug_name", maxDrugNameChars)
		if err != nil {
			return invalidArgument(drugSafetyToolName, err), nil
		}

		limit := clamp(request.GetInt("limit", defaultSafetyLimit), minSafetyLimit, maxSafetyLimit)

		result, err := s.drugSafety(ctx, drugName, limit)
		if err != nil {
			failed := &DrugSafetyResult{
				Drug:           drugName,
				ReportedEvents: []ReactionCount{},
				Disclaimer:     config.Conf.FAERSDisclaimer,
				Meta:           errorMeta(drugSafetySource, drugSafetySourceURL, err),
			}

			return retrievalFailure(drugSafetyToolName, failed, err), nil
		}

		return jsonResult(drugSafetyToolName, result), nil
	}

	return Tool{Def: def, Handler: handler}
}

// drugSafety aggregates the reactions reported against a drug.
func (s *Set) drugSafety(ctx context.Context, drugName string, limit int) (*DrugSafetyResult, error) {
	search := searchExpression(drugName)
	empty := &DrugSafetyResult{
		Drug:           drugName,
		ReportedEvents: []ReactionCount{},
		Disclaimer:     config.Conf.FAERSDisclaimer,
		Meta:           okMeta(drugSafetySource, drugSafetySourceURL, false),
	}

	var counts struct {
		Meta struct {
			LastUpdated string `json:"last_updated"`
		} `json:"meta"`
		Results []struct {
			Term  string `json:"term"`
			Count int    `json:"count"`
		} `json:"results"`
	}

	err := httpx.GetJSON(ctx, s.client, drugSafetyToolName, config.Conf.OpenFDAEventURL, url.Values{
		paramSearch: {search},
		paramCount:  {reactionField},
		paramLimit:  {strconv.Itoa(limit)},
	}, &counts)
	if err != nil {
		// openFDA answers 404 when a search matches no reports. That is an
		// answer, not a failure, and must not be reported as one: "no reports"
		// and "we could not check" mean very different things to a model
		// reasoning about drug safety.
		if httpx.StatusOf(err) == http.StatusNotFound {
			logging.Logger.Info("no reports for the drug",
				zap.String("tool", drugSafetyToolName), zap.String("drug", drugName))

			return empty, nil
		}

		return nil, err
	}

	events := make([]ReactionCount, 0, len(counts.Results))

	for _, item := range counts.Results {
		// A blank term names no reaction, so it tells a model nothing.
		if item.Term != "" {
			events = append(events, ReactionCount{Reaction: item.Term, Count: item.Count})
		}
	}

	if len(events) == 0 {
		return empty, nil
	}

	result := &DrugSafetyResult{
		Drug:            drugName,
		ReportedEvents:  events,
		DataLastUpdated: counts.Meta.LastUpdated,
		Disclaimer:      config.Conf.FAERSDisclaimer,
		Meta:            okMeta(drugSafetySource, drugSafetySourceURL, true),
	}

	s.enrich(ctx, search, result)

	logging.Logger.Info("resolved drug safety reports",
		zap.String("tool", drugSafetyToolName),
		zap.String("drug", drugName),
		zap.Int("reactions", len(events)),
		zap.Int("boundary_reports", len(result.BoundaryReports)),
	)

	return result, nil
}

// enrich adds the seriousness split and the boundary reports. These three calls
// only add context to an answer that already exists, so any of them failing is
// logged and dropped rather than failing the tool.
func (s *Set) enrich(ctx context.Context, search string, result *DrugSafetyResult) {
	requests := []url.Values{
		{paramSearch: {search}, paramCount: {"serious"}, paramLimit: {seriousnessLimit}},
		{paramSearch: {search}, paramSort: {"receiptdate:asc"}, paramLimit: {boundaryLimit}},
		{paramSearch: {search}, paramSort: {"receiptdate:desc"}, paramLimit: {boundaryLimit}},
	}

	bodies := make([][]byte, len(requests))

	var wait sync.WaitGroup

	for index, params := range requests {
		wait.Go(func() {
			body, err := httpx.Get(ctx, s.client, drugSafetyToolName, config.Conf.OpenFDAEventURL, params)
			if err != nil {
				logging.Logger.Warn("drug safety detail skipped", zap.Error(err))

				return
			}

			bodies[index] = body
		})
	}

	wait.Wait()

	result.SeriousnessCounts = parseSeriousness(bodies[0])

	boundary := make([]ReportSummary, 0, len(bodies)-1)

	for _, body := range bodies[1:] {
		summary, ok := parseReport(body)
		if ok {
			boundary = append(boundary, summary)
		}
	}

	if len(boundary) == 0 {
		return
	}

	result.BoundaryReports = boundary
	result.ReportDateRange = dateRange(boundary)
}

// dateRange spans the plausible receipt dates among the boundary reports.
func dateRange(reports []ReportSummary) *DateRange {
	dates := make([]string, 0, len(reports))

	for index := range reports {
		if reports[index].ReceiptDate != "" {
			dates = append(dates, reports[index].ReceiptDate)
		}
	}

	if len(dates) == 0 {
		return nil
	}

	// Receipt dates are YYYYMMDD, so lexical order is chronological order.
	earliest, latest := dates[0], dates[0]
	for _, date := range dates[1:] {
		earliest, latest = min(earliest, date), max(latest, date)
	}

	return &DateRange{From: earliest, To: latest}
}

func parseSeriousness(body []byte) []SeriousnessCount {
	if body == nil {
		return nil
	}

	var payload struct {
		Results []struct {
			Term  jsonScalar `json:"term"`
			Count int        `json:"count"`
		} `json:"results"`
	}

	err := json.Unmarshal(body, &payload)
	if err != nil || len(payload.Results) == 0 {
		return nil
	}

	counts := make([]SeriousnessCount, 0, len(payload.Results))

	for index := range payload.Results {
		// openFDA encodes the seriousness flag as "1" for serious.
		counts = append(counts, SeriousnessCount{
			Serious: payload.Results[index].Term.String() == "1",
			Count:   payload.Results[index].Count,
		})
	}

	return counts
}

func parseReport(body []byte) (ReportSummary, bool) {
	if body == nil {
		return ReportSummary{}, false
	}

	var payload struct {
		Results []map[string]json.RawMessage `json:"results"`
	}

	err := json.Unmarshal(body, &payload)
	if err != nil || len(payload.Results) == 0 {
		return ReportSummary{}, false
	}

	report := payload.Results[0]
	summary := ReportSummary{
		SafetyReportID: scalarField(report, "safetyreportid"),
		ReceiptDate:    plausibleDate(scalarField(report, "receiptdate")),
		Serious:        scalarField(report, "serious") == "1",
	}

	// Every seriousness* field set to "1" names a category the report was
	// flagged under (seriousnessdeath, seriousnesshospitalization, ...).
	for key := range report {
		if strings.HasPrefix(key, "seriousness") && scalarField(report, key) == "1" {
			summary.SeriousnessCategories = append(summary.SeriousnessCategories,
				strings.TrimPrefix(key, "seriousness"))
		}
	}

	return summary, true
}

// plausibleDate keeps a FAERS receipt date only if it could be one. The dataset
// contains transcription errors — a report dated 30040423 is really in there —
// and a nonsense date is worse than no date: a model will reason about it as if
// it were real. Anything implausible is dropped rather than corrected, because
// there is no way to know what was meant.
func plausibleDate(value string) string {
	if len(value) != len(receiptDateLayout) {
		return ""
	}

	parsed, err := time.Parse(receiptDateLayout, value)
	if err != nil {
		return ""
	}

	if parsed.Year() < earliestFAERSYear || parsed.After(time.Now().AddDate(0, 0, 1)) {
		return ""
	}

	return value
}

func scalarField(report map[string]json.RawMessage, key string) string {
	raw, ok := report[key]
	if !ok {
		return ""
	}

	var value jsonScalar

	err := json.Unmarshal(raw, &value)
	if err != nil {
		return ""
	}

	return value.String()
}

// searchExpression builds the openFDA query, matching the drug name against the
// reported product name and both openFDA-normalised names. The name goes inside
// a quoted term of openFDA's Lucene-style query language, so %q supplies both
// the quotes and the escaping of any quote or backslash within it.
func searchExpression(drugName string) string {
	return fmt.Sprintf(
		`(patient.drug.medicinalproduct:%[1]q OR `+
			`patient.drug.openfda.brand_name:%[1]q OR `+
			`patient.drug.openfda.generic_name:%[1]q)`,
		drugName)
}

// clamp bounds an integer argument to [low, high].
func clamp(value, low, high int) int {
	return min(max(value, low), high)
}
