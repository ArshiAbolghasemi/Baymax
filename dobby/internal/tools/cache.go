package tools

import (
	"context"
	"encoding/json"
	"sync"
	"time"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/logging"
	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/metrics"
	"go.uber.org/zap"
)

// entry is one cached answer and the instant it stops being usable.
type entry struct {
	expires time.Time
	payload []byte
}

// Cache is a process-local, size-bounded TTL cache. It is safe for concurrent
// use.
//
// The sources here are slow and rate-limited, and an agent commonly asks the
// same question twice in one conversation. Entries are stored as marshaled
// JSON so a caller can never mutate another caller's answer through a shared
// slice or map.
type Cache struct {
	mu         sync.Mutex
	entries    map[string]entry
	maxEntries int
}

// NewCache returns a cache holding at most maxEntries values. Zero or less
// disables caching entirely.
func NewCache(maxEntries int) *Cache {
	return &Cache{entries: make(map[string]entry), maxEntries: maxEntries}
}

// Len reports how many entries are currently held, expired ones included.
func (c *Cache) Len() int {
	c.mu.Lock()
	defer c.mu.Unlock()

	return len(c.entries)
}

// Clear empties the cache.
func (c *Cache) Clear() {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.entries = make(map[string]entry)
}

func (c *Cache) get(key string, now time.Time) ([]byte, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	found, ok := c.entries[key]
	if !ok {
		return nil, false
	}

	if !found.expires.After(now) {
		delete(c.entries, key)

		return nil, false
	}

	return found.payload, true
}

// set stores payload under key, first dropping expired entries and then, if the
// cache is still full, arbitrary ones. Eviction order is deliberately
// unspecified: every entry is reproducible by refetching, so the cost of a bad
// eviction is one extra request, not a wrong answer.
func (c *Cache) set(key string, payload []byte, ttl time.Duration, now time.Time) {
	if c.maxEntries <= 0 || ttl <= 0 {
		return
	}

	c.mu.Lock()
	defer c.mu.Unlock()

	_, exists := c.entries[key]
	if !exists && len(c.entries) >= c.maxEntries {
		c.evict(now)
	}

	c.entries[key] = entry{expires: now.Add(ttl), payload: payload}
}

// evict must be called with the lock held.
func (c *Cache) evict(now time.Time) {
	for key := range c.entries {
		if !c.entries[key].expires.After(now) {
			delete(c.entries, key)
		}
	}

	for key := range c.entries {
		if len(c.entries) < c.maxEntries {
			break
		}

		delete(c.entries, key)
	}
}

// cached returns the cached value for key, or calls produce and caches what it
// returns. A produce error is passed through and never cached: a failed
// retrieval must not stop the next call from trying again.
//
// Two concurrent misses on the same key both call produce. Making one wait on
// the other would cost a duplicate request at worst, and risks one slow call
// blocking an unrelated one.
func cached[T any](
	ctx context.Context,
	cache *Cache,
	toolName, key string,
	ttl time.Duration,
	produce func(context.Context) (T, error),
) (T, error) {
	var value T

	full := toolName + "\x00" + key

	payload, ok := cache.get(full, time.Now())
	if ok {
		err := json.Unmarshal(payload, &value)
		if err == nil {
			metrics.ObserveCache(toolName, metrics.CacheHit)
			logging.Logger.Debug("tool cache hit", zap.String("tool", toolName))

			return value, nil
		}
		// A stored payload that no longer decodes into T means the result type
		// changed under a running process. Treat it as a miss.
	}

	metrics.ObserveCache(toolName, metrics.CacheMiss)
	logging.Logger.Debug("tool cache miss", zap.String("tool", toolName))

	value, err := produce(ctx)
	if err != nil {
		return value, err
	}

	encoded, err := json.Marshal(value)
	if err == nil {
		cache.set(full, encoded, ttl, time.Now())
	}

	return value, nil
}
