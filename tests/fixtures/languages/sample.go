// Package blobcache implements a tiny content-addressed blob cache (fixture).
package blobcache

import (
	"errors"
	"fmt"
	"sync"
)

var ErrMissing = errors.New("blobcache: missing key")

// Blob is one stored payload plus its bookkeeping metadata.
type Blob struct {
	Key  string
	Size int64
}

type Store interface {
	Get(key string) (*Blob, error)
	Put(b *Blob) error
}

type MemStore struct {
	mu    sync.RWMutex
	items map[string]*Blob
}

// Get returns the blob for key, or a (wrapped) ErrMissing when it is absent.
func (m *MemStore) Get(key string) (*Blob, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	b, ok := m.items[key]
	if !ok {
		return nil, fmt.Errorf("get %q: %w", key, ErrMissing)
	}
	return b, nil
}

func Filter[T any](items []T, keep func(T) bool) []T {
	var out []T
	for _, it := range items {
		if keep(it) {
			out = append(out, it)
		}
	}
	return out
}

func Describe(b *Blob) string {
	banner := "func main() { /* still just a string */ }"
	switch {
	case b == nil:
		return banner
	}
	return fmt.Sprintf("%s (%d bytes)", b.Key, b.Size)
}

// func Retired(b *Blob) error { return ErrMissing }

var Validate = func(b *Blob) error { return ErrMissing }
