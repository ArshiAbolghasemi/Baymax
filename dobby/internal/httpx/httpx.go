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
	"math"
	"net"
	"net/http"
	"net/url"
	"time"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/metrics"
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

// retry performs the request, repeating it while the failure looks transient
// and the caller's context is still alive.
func retry(ctx context.Context, client *http.Client, source, target string) ([]byte, error) {
	start := time.Now()
	attempts := config.Conf.HTTPMaxRetries + 1

	var lastErr error

	for attempt := 1; attempt <= attempts; attempt++ {
		err := waitBeforeRetry(ctx, source, attempt, lastErr)
		if err != nil {
			return nil, err
		}

		body, err := do(ctx, client, source, target, attempt)
		if err == nil {
			metrics.ObserveUpstream(source, metrics.StatusSuccess, time.Since(start))

			return body, nil
		}

		lastErr = err

		if ctx.Err() != nil || !retryable(err) {
			break
		}
	}

	metrics.ObserveUpstream(source, metrics.StatusFailed, time.Since(start))

	logging.Logger.Error("upstream request failed",
		zap.String("source", source),
		zap.Int("status_code", StatusOf(lastErr)),
		zap.Duration("duration", time.Since(start)),
		zap.Error(lastErr),
	)

	return nil, lastErr
}

// waitBeforeRetry pauses before every attempt but the first, and reports a
// canceled context so the caller stops rather than sleeping through it.
func waitBeforeRetry(ctx context.Context, source string, attempt int, lastErr error) error {
	if attempt == 1 {
		return nil
	}

	wait := backoff(attempt - 1)

	logging.Logger.Warn("retrying an upstream request",
		zap.String("source", source),
		zap.Int("attempt", attempt),
		zap.Int("status_code", StatusOf(lastErr)),
		zap.Duration("wait", wait),
		zap.Error(lastErr),
	)

	return sleep(ctx, wait)
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

// backoffBase is the factor each retry multiplies the wait by.
const backoffBase = 2

// backoff is exponential in the configured multiplier, capped at the
// configured ceiling: multiplier * backoffBase^(retry-1).
func backoff(retry int) time.Duration {
	wait := time.Duration(float64(config.Conf.RetryMultiplier) * math.Pow(backoffBase, float64(retry-1)))

	return min(wait, config.Conf.RetryMaxWait)
}

func sleep(ctx context.Context, duration time.Duration) error {
	timer := time.NewTimer(duration)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
