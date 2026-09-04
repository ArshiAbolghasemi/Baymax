package httpx

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync/atomic"
	"testing"
	"time"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/config"
)

// errBoom stands in for a real failure in these tests.
var errBoom = errors.New("boom")

// withPolicy installs a fast retry policy for the duration of a test.
func withPolicy(t *testing.T, maxRetries int) *http.Client {
	t.Helper()

	previous := config.Conf

	t.Cleanup(func() { config.Conf = previous })

	config.Conf.HTTPMaxRetries = maxRetries
	config.Conf.RetryMultiplier = time.Millisecond
	config.Conf.RetryMaxWait = 2 * time.Millisecond
	config.Conf.TransientStatus = []int{
		http.StatusTooManyRequests, http.StatusServiceUnavailable,
	}

	client, err := NewClient(5*time.Second, "")
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}

	return client
}

func TestGetReturnsBody(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if got := request.URL.Query().Get("term"); got != "asthma" {
			t.Errorf("term = %q, want asthma", got)
		}

		_, _ = io.WriteString(writer, "<response/>")
	}))
	defer server.Close()

	body, err := Get(t.Context(), withPolicy(t, 2), "test", server.URL, url.Values{"term": {"asthma"}})
	if err != nil {
		t.Fatalf("Get: %v", err)
	}

	if string(body) != "<response/>" {
		t.Fatalf("body = %q", body)
	}
}

func TestGetJSONDecodes(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(writer, `{"name":"aspirin"}`)
	}))
	defer server.Close()

	var out struct {
		Name string `json:"name"`
	}

	err := GetJSON(t.Context(), withPolicy(t, 0), "test", server.URL, nil, &out)
	if err != nil {
		t.Fatalf("GetJSON: %v", err)
	}

	if out.Name != "aspirin" {
		t.Fatalf("name = %q", out.Name)
	}
}

func TestGetRetriesTransientStatus(t *testing.T) {
	var attempts atomic.Int32

	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		if attempts.Add(1) < 3 {
			writer.WriteHeader(http.StatusServiceUnavailable)

			return
		}

		_, _ = io.WriteString(writer, "ok")
	}))
	defer server.Close()

	body, err := Get(t.Context(), withPolicy(t, 2), "test", server.URL, nil)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}

	if string(body) != "ok" {
		t.Fatalf("body = %q", body)
	}

	if got := attempts.Load(); got != 3 {
		t.Fatalf("made %d attempts, want 3", got)
	}
}

// A permanent status must cost exactly one attempt.
func TestGetDoesNotRetryPermanentStatus(t *testing.T) {
	var attempts atomic.Int32

	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		attempts.Add(1)
		writer.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()

	_, err := Get(t.Context(), withPolicy(t, 2), "test", server.URL, nil)
	if err == nil {
		t.Fatal("Get succeeded, want an error")
	}

	if got := StatusOf(err); got != http.StatusNotFound {
		t.Fatalf("StatusOf = %d, want 404", got)
	}

	if got := attempts.Load(); got != 1 {
		t.Fatalf("made %d attempts, want 1", got)
	}
}

func TestGetGivesUpAfterMaxRetries(t *testing.T) {
	var attempts atomic.Int32

	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		attempts.Add(1)
		writer.WriteHeader(http.StatusTooManyRequests)
	}))
	defer server.Close()

	_, err := Get(t.Context(), withPolicy(t, 2), "test", server.URL, nil)
	if err == nil {
		t.Fatal("Get succeeded, want an error")
	}

	// MaxRetries counts retries after the first attempt.
	if got := attempts.Load(); got != 3 {
		t.Fatalf("made %d attempts, want 3", got)
	}
}

func TestGetHonoursCancellation(t *testing.T) {
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		<-release
	}))

	defer func() {
		close(release)
		server.Close()
	}()

	ctx, cancel := context.WithCancel(t.Context())

	go func() {
		time.Sleep(10 * time.Millisecond)
		cancel()
	}()

	start := time.Now()

	_, err := Get(ctx, withPolicy(t, 2), "test", server.URL, nil)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("Get error = %v, want context.Canceled", err)
	}

	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("Get took %s after cancellation", elapsed)
	}
}

func TestStatusOfIgnoresUnrelatedErrors(t *testing.T) {
	if got := StatusOf(errBoom); got != 0 {
		t.Fatalf("StatusOf = %d, want 0", got)
	}
}

func TestNewClientRejectsBadProxy(t *testing.T) {
	_, err := NewClient(time.Second, "://not a url")
	if err == nil {
		t.Fatal("NewClient accepted an invalid proxy url")
	}
}
