// Package httpx holds the small amount of HTTP plumbing shared by dobby's
// outbound source clients.
//
// Beyond the request itself it owns the retry policy. The NLM and FDA services
// rate-limit and occasionally 503, so a transient failure is retried with
// bounded exponential backoff while a permanent one is returned on the first
// attempt: retrying a 400 only delays the answer, and retrying openFDA's 404
// would triple the load for every drug that simply has no reports.
package httpx

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"time"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/metrics"
	retrygo "github.com/avast/retry-go/v4"
	"go.uber.org/zap"
)

// maxBodyBytes caps how much of a response is read into memory. The largest
// document any tool retrieves is a DailyMed SPL; this leaves generous headroom
// while keeping a misbehaving upstream from exhausting the process.
const maxBodyBytes = 32 << 20

// maxErrorBody caps how much of a failing response body is kept for the error.
const maxErrorBody = 2 << 10

// userAgent identifies this client to the NLM and FDA services, which ask
// automated callers to say who they are.
const userAgent = "baymax-dobby/1.0 (+https://github.com/ArshiAbolghasemi/Baymax)"

// errUnexpectedTransport guards the assertion on http.DefaultTransport, which
// only fails if the default transport has been replaced.
var errUnexpectedTransport = errors.New("http.DefaultTransport is not an *http.Transport")

// StatusError reports a non-2xx response together with its (truncated) body.
// Callers read StatusCode to tell "the source said no" from "the source could
// not be reached".
type StatusError struct {
	StatusCode int
	Body       string
}

func (e *StatusError) Error() string {
	return fmt.Sprintf("unexpected status %d: %s", e.StatusCode, e.Body)
}

// StatusOf returns the HTTP status carried by err, or 0 when err never
// received a response.
func StatusOf(err error) int {
	if statusErr, ok := errors.AsType[*StatusError](err); ok {
		return statusErr.StatusCode
	}

	return 0
}

// NewClient builds an HTTP client with the given timeout, optionally routing
// requests through proxyURL.
func NewClient(timeout time.Duration, proxyURL string) (*http.Client, error) {
	client := &http.Client{Timeout: timeout}
	if proxyURL == "" {
		return client, nil
	}

	parsed, err := url.Parse(proxyURL)
	if err != nil {
		return nil, fmt.Errorf("invalid proxy url: %w", err)
	}

	base, ok := http.DefaultTransport.(*http.Transport)
	if !ok {
		return nil, errUnexpectedTransport
	}

	transport := base.Clone()
	transport.Proxy = http.ProxyURL(parsed)
	client.Transport = transport

	return client, nil
}

// Get issues a GET request with the given query parameters and returns the raw
// body. source names the upstream for the logs and the metrics.
func Get(
	ctx context.Context,
	client *http.Client,
	source, endpoint string,
	params url.Values,
) ([]byte, error) {
	target := endpoint
	if len(params) > 0 {
		target = endpoint + "?" + params.Encode()
	}

	return retry(ctx, client, source, target)
}

// GetJSON issues a GET request and decodes a successful response into out.
func GetJSON(
	ctx context.Context,
	client *http.Client,
	source, endpoint string,
	params url.Values,
	out any,
) error {
	body, err := Get(ctx, client, source, endpoint, params)
	if err != nil {
		return err
	}

	err = json.Unmarshal(body, out)
	if err != nil {
		logging.Logger.Error("failed to decode response body",
			zap.String("source", source),
			zap.String("url", endpoint),
			zap.Error(err),
		)

		return fmt.Errorf("decode response: %w", err)
	}

	return nil
}

// retry performs the request, repeating transient failures according to the
// configured retry policy.
func retry(ctx context.Context, client *http.Client, source, target string) ([]byte, error) {
	start := time.Now()
	attempt := 0

	body, err := retrygo.DoWithData(func() ([]byte, error) {
		attempt++

		return do(ctx, client, source, target, attempt)
	},
		retrygo.Attempts(uint(config.Conf.HTTPMaxRetries+1)),
		retrygo.Delay(config.Conf.RetryMultiplier),
		retrygo.MaxDelay(config.Conf.RetryMaxWait),
		retrygo.DelayType(retrygo.BackOffDelay),
		retrygo.RetryIf(retryable),
		retrygo.Context(ctx),
		retrygo.LastErrorOnly(true),
		retrygo.OnRetry(func(retry uint, err error) {
			if retry >= uint(config.Conf.HTTPMaxRetries) {
				return
			}

			logging.Logger.Warn("retrying an upstream request",
				zap.String("source", source),
				zap.Int("attempt", attempt+1),
				zap.Int("status_code", StatusOf(err)),
				zap.Error(err),
			)
		}),
	)
	if err == nil {
		metrics.ObserveUpstream(source, metrics.StatusSuccess, time.Since(start))

		return body, nil
	}

	metrics.ObserveUpstream(source, metrics.StatusFailed, time.Since(start))

	logging.Logger.Error("upstream request failed",
		zap.String("source", source),
		zap.Int("status_code", StatusOf(err)),
		zap.Duration("duration", time.Since(start)),
		zap.Error(err),
	)

	return nil, err
}

// do performs one attempt and returns the body it read.
func do(ctx context.Context, client *http.Client, source, target string, attempt int) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}

	req.Header.Set("Accept", "application/json, text/xml, application/xml;q=0.9, */*;q=0.8")
	req.Header.Set("User-Agent", userAgent)

	logging.Logger.Debug("outbound request started",
		zap.String("source", source),
		zap.String("url", req.URL.Redacted()),
		zap.Int("attempt", attempt),
	)

	start := time.Now()

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close() //nolint:errcheck // nothing actionable on a close failure

	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, maxErrorBody))

		return nil, &StatusError{StatusCode: resp.StatusCode, Body: string(body)}
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBodyBytes))
	if err != nil {
		return nil, fmt.Errorf("read response: %w", err)
	}

	logging.Logger.Debug("outbound request succeeded",
		zap.String("source", source),
		zap.String("url", req.URL.Redacted()),
		zap.Int("status_code", resp.StatusCode),
		zap.Int("bytes", len(body)),
		zap.Duration("duration", time.Since(start)),
	)

	return body, nil
}

// retryable reports whether another attempt could plausibly succeed.
func retryable(err error) bool {
	if errors.Is(err, context.Canceled) {
		return false
	}

	status := StatusOf(err)
	if status != 0 {
		return config.Conf.IsTransientStatus(status)
	}

	if _, ok := errors.AsType[net.Error](err); ok {
		return true
	}

	// A per-attempt timeout surfaces as a *url.Error wrapping
	// context.DeadlineExceeded; that is a timeout, not a caller cancellation.
	return errors.Is(err, context.DeadlineExceeded)
}
