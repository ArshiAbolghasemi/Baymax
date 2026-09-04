package tools

import (
	"context"
	"net/url"
	"strconv"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/httpx"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/medline"
	"go.uber.org/zap"
)

const (
	healthInfoToolName = "search_health_info"

	healthInfoDescription = `Search MedlinePlus for patient-friendly disease and condition information.

Use for symptoms, causes, diagnosis, treatment, prevention, and general disease
information. Do not use for detailed official drug labels or genetics questions;
use search_drug_label or search_genetics for those.

Returns a status of "ok", "no_results", or "error". An "error" means the source
could not be reached, never that the condition does not exist.`
)

// HealthInfoResult is what search_health_info returns.
type HealthInfoResult struct {
	Meta

	Query   string          `json:"query"`
	Results []medline.Topic `json:"results"`
}

func (s *Set) searchHealthInfo() Tool {
	spec := searchSpec{
		toolName:  healthInfoToolName,
		ttl:       config.Conf.HealthInfoTTL,
		source:    medline.SourceHealth,
		sourceURL: medline.URLHealth,
	}

	return newSearchTool(s.cache, spec, healthInfoDescription,
		"Disease, symptom, or health-topic query.",
		s.healthTopics,
		func(query string, meta Meta) *HealthInfoResult {
			return &HealthInfoResult{Meta: meta, Query: query, Results: []medline.Topic{}}
		})
}

// healthTopics runs the search and shapes the answer.
func (s *Set) healthTopics(ctx context.Context, query string) (*HealthInfoResult, error) {
	body, err := httpx.Get(ctx, s.client, healthInfoToolName, config.Conf.MedlinePlusSearchURL, url.Values{
		"db":      {"healthTopics"},
		"term":    {query},
		"retmax":  {strconv.Itoa(config.Conf.MaxResults)},
		"rettype": {"brief"},
		"tool":    {config.Conf.SearchToolIdentifier},
	})
	if err != nil {
		return nil, err
	}

	topics, err := medline.ParseTopics(string(body), config.Conf.MaxResults, config.Conf.MaxSummaryChars)
	if err != nil {
		return nil, err
	}

	logging.Logger.Info("resolved health topics",
		zap.String("tool", healthInfoToolName),
		zap.Int("results", len(topics)),
	)

	return &HealthInfoResult{
		Query:   query,
		Results: topics,
		Meta:    okMeta(medline.SourceHealth, medline.URLHealth, len(topics) > 0),
	}, nil
}
