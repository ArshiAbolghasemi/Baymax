package tools

import (
	"context"
	"errors"
	"strconv"
	"testing"
	"time"
)

// errUpstreamDown stands in for a real failure in these tests.
var errUpstreamDown = errors.New("upstream down")

type cachedPayload struct {
	Name  string   `json:"name"`
	Items []string `json:"items"`
}

func TestCachedReusesSuccess(t *testing.T) {
	cache := NewCache(8)
	calls := 0

	produce := func(context.Context) (cachedPayload, error) {
		calls++

		return cachedPayload{Name: "aspirin"}, nil
	}

	for range 3 {
		value, err := cached(t.Context(), cache, "tool", "key", time.Minute, produce)
		if err != nil {
			t.Fatalf("cached: %v", err)
		}

		if value.Name != "aspirin" {
			t.Fatalf("cached returned %+v", value)
		}
	}

	if calls != 1 {
		t.Fatalf("producer ran %d times, want 1", calls)
	}
}

// A failed retrieval must never be cached, or one blip would poison a key for
// the length of its TTL.
func TestCachedDoesNotStoreErrors(t *testing.T) {
	cache := NewCache(8)
	calls := 0
	wantErr := errUpstreamDown

	produce := func(context.Context) (cachedPayload, error) {
		calls++

		return cachedPayload{}, wantErr
	}

	for range 2 {
		_, err := cached(t.Context(), cache, "tool", "key", time.Minute, produce)
		if !errors.Is(err, wantErr) {
			t.Fatalf("cached error = %v, want %v", err, wantErr)
		}
	}

	if calls != 2 {
		t.Fatalf("producer ran %d times, want 2", calls)
	}

	if cache.Len() != 0 {
		t.Fatalf("cache holds %d entries after only failures", cache.Len())
	}
}

func TestCachedExpires(t *testing.T) {
	cache := NewCache(8)
	calls := 0

	produce := func(context.Context) (cachedPayload, error) {
		calls++

		return cachedPayload{Name: "x"}, nil
	}

	_, err := cached(t.Context(), cache, "tool", "key", time.Nanosecond, produce)
	if err != nil {
		t.Fatalf("cached: %v", err)
	}

	time.Sleep(2 * time.Millisecond)

	_, err = cached(t.Context(), cache, "tool", "key", time.Nanosecond, produce)
	if err != nil {
		t.Fatalf("cached: %v", err)
	}

	if calls != 2 {
		t.Fatalf("producer ran %d times, want 2: the entry should have expired", calls)
	}
}

// A caller must not be able to reach into another caller's cached value
// through a shared slice header.
func TestCachedReturnsIndependentCopies(t *testing.T) {
	cache := NewCache(8)

	produce := func(context.Context) (cachedPayload, error) {
		return cachedPayload{Name: "n", Items: []string{"a", "b"}}, nil
	}

	first, err := cached(t.Context(), cache, "tool", "key", time.Minute, produce)
	if err != nil {
		t.Fatalf("cached: %v", err)
	}

	first.Items[0] = "mutated"

	second, err := cached(t.Context(), cache, "tool", "key", time.Minute, produce)
	if err != nil {
		t.Fatalf("cached: %v", err)
	}

	if second.Items[0] != "a" {
		t.Fatalf("the cached value was mutated through a returned slice: %+v", second)
	}
}

func TestCacheIsBounded(t *testing.T) {
	cache := NewCache(4)

	for index := range 50 {
		key := strconv.Itoa(index)

		_, err := cached(t.Context(), cache, "tool", key, time.Minute,
			func(context.Context) (cachedPayload, error) {
				return cachedPayload{Name: key}, nil
			})
		if err != nil {
			t.Fatalf("cached: %v", err)
		}
	}

	if cache.Len() > 4 {
		t.Fatalf("cache grew to %d entries, want at most 4", cache.Len())
	}
}

func TestZeroMaxEntriesDisablesCaching(t *testing.T) {
	cache := NewCache(0)
	calls := 0

	produce := func(context.Context) (cachedPayload, error) {
		calls++

		return cachedPayload{}, nil
	}

	for range 2 {
		_, err := cached(t.Context(), cache, "tool", "key", time.Minute, produce)
		if err != nil {
			t.Fatalf("cached: %v", err)
		}
	}

	if calls != 2 {
		t.Fatalf("producer ran %d times, want 2", calls)
	}
}
