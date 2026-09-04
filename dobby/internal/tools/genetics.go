package tools

import (
	"context"
	"net/url"
	"strconv"
	"sync"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/httpx"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/medline"
	"go.uber.org/zap"
)

const (
	geneticsToolName = "search_genetics"

	geneticsDescription = `Search MedlinePlus Genetics for consumer-oriented genetics information.

Use for genes and gene function, genetic conditions, inheritance, chromosomes,
variants, and genetic mechanisms. Do not use for ordinary disease guidance or
detailed official drug labels.

Returns a status of "ok", "no_results", or "error". An "error" means the source
could not be reached, never that the gene or condition does not exist.`
)

// GeneticsResult is what search_genetics returns.
type GeneticsResult struct {
	Meta

	Query   string          `json:"query"`
	Results []medline.Entry `json:"results"`
}

func (s *Set) searchGenetics() Tool {
	spec := searchSpec{
		toolName:  geneticsToolName,
		ttl:       config.Conf.GeneticsTTL,
		source:    medline.SourceGenetics,
		sourceURL: medline.URLGenetics,
	}

	return newSearchTool(s.cache, spec, geneticsDescription,
		"Gene, genetic condition, inheritance, chromosome, or genetics-topic query.",
		s.geneticsEntries,
		func(query string, meta Meta) *GeneticsResult {
			return &GeneticsResult{Meta: meta, Query: query, Results: []medline.Entry{}}
		})
}

// geneticsEntries searches, then enriches each hit from its detail document.
//
// The search response alone gives only titles and snippets; the summary,
// inheritance and related entities that actually answer a genetics question
// live in the per-page detail document.
func (s *Set) geneticsEntries(ctx context.Context, query string) (*GeneticsResult, error) {
	body, err := httpx.Get(ctx, s.client, geneticsToolName, config.Conf.MedlinePlusSearchURL, url.Values{
		"db":      {"ghr"},
		"term":    {query},
		"retmax":  {strconv.Itoa(config.Conf.MaxResults)},
		"rettype": {"brief"},
		"tool":    {config.Conf.SearchToolIdentifier},
	})
	if err != nil {
		return nil, err
	}

	entries, err := medline.ParseGeneticsEntries(
		string(body), config.Conf.MaxResults, config.Conf.MaxSummaryChars)
	if err != nil {
		return nil, err
	}

	pageURLs := medline.GeneticsPageURLs(string(body), config.Conf.MaxResults)

	detailed := s.geneticsDetails(ctx, pageURLs)
	if len(detailed) > 0 {
		entries = detailed
	}

	logging.Logger.Info("resolved genetics entries",
		zap.String("tool", geneticsToolName),
		zap.Int("pages", len(pageURLs)),
		zap.Int("detailed", len(detailed)),
		zap.Int("results", len(entries)),
	)

	return &GeneticsResult{
		Query:   query,
		Results: entries,
		Meta:    okMeta(medline.SourceGenetics, medline.URLGenetics, len(entries) > 0),
	}, nil
}

// geneticsDetail fetches and parses one page's detail document. A failure is
// logged and reported as a miss, never as an error: see geneticsDetails.
func (s *Set) geneticsDetail(ctx context.Context, pageURL string) (medline.Entry, bool) {
	detailURL := medline.DetailURL(config.Conf.MedlinePlusGeneticsURL, pageURL)

	body, err := httpx.Get(ctx, s.client, geneticsToolName, detailURL, nil)
	if err != nil {
		logging.Logger.Warn("genetics detail skipped",
			zap.String("url", detailURL), zap.Error(err))

		return medline.Entry{}, false
	}

	entry, err := medline.ParseGeneticsDetail(body, pageURL, config.Conf.MaxSummaryChars)
	if err != nil {
		logging.Logger.Warn("genetics detail unparsable",
			zap.String("url", detailURL), zap.Error(err))

		return medline.Entry{}, false
	}

	return entry, true
}

// geneticsDetails fetches each detail document concurrently and returns the
// entries that parsed, in the original result order.
//
// A page that fails is skipped rather than failing the call: partial genetics
// results are still useful, and one flaky document should not lose the rest.
// If every page fails the caller keeps the search-level entries it already has.
func (s *Set) geneticsDetails(ctx context.Context, pageURLs []string) []medline.Entry {
	if len(pageURLs) == 0 {
		return nil
	}

	entries := make([]medline.Entry, len(pageURLs))
	found := make([]bool, len(pageURLs))

	var wait sync.WaitGroup

	for index, pageURL := range pageURLs {
		wait.Go(func() {
			entry, ok := s.geneticsDetail(ctx, pageURL)
			if ok {
				entries[index], found[index] = entry, true
			}
		})
	}

	wait.Wait()

	ordered := make([]medline.Entry, 0, len(entries))

	for index, ok := range found {
		if ok {
			ordered = append(ordered, entries[index])
		}
	}

	return ordered
}
