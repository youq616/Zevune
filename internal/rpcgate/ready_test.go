package rpcgate

import (
	"context"
	"errors"
	"io"
	"os"
	"sync"
	"testing"
	"time"
)

type failingReady struct{}

func (failingReady) Write([]byte) (int, error) { return 0, errors.New("do not disclose") }
func (failingReady) Close() error              { return nil }

type blockedReady struct {
	entered, closed chan struct{}
	once            sync.Once
}

func (b *blockedReady) Write([]byte) (int, error) {
	close(b.entered)
	<-b.closed
	return 0, io.ErrClosedPipe
}
func (b *blockedReady) Close() error { b.once.Do(func() { close(b.closed) }); return nil }

func TestReadinessFailureCancellationAndRealPipe(t *testing.T) {
	if WriteReady(context.Background(), failingReady{}) != ErrReady {
		t.Fatal("failed writer")
	}
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	defer w.Close()
	done := make(chan error, 1)
	go func() { done <- WriteReady(context.Background(), w) }()
	raw := make([]byte, len(ReadyRecord))
	if _, err = io.ReadFull(r, raw); err != nil || string(raw) != ReadyRecord {
		t.Fatal("ready record")
	}
	if err = <-done; err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	b := &blockedReady{entered: make(chan struct{}), closed: make(chan struct{})}
	go func() { done <- WriteReady(ctx, b) }()
	<-b.entered
	cancel()
	select {
	case err = <-done:
		if err != ErrReady {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("blocked ready did not stop")
	}
	if WriteReady(nil, w) != ErrReady || WriteReady(context.Background(), nil) != ErrReady {
		t.Fatal("missing ready capability")
	}
}

func TestReadinessBlockedWriterTimesOut(t *testing.T) {
	b := &blockedReady{entered: make(chan struct{}), closed: make(chan struct{})}
	started := time.Now()
	if WriteReady(context.Background(), b) != ErrReady {
		t.Fatal("missing timeout")
	}
	if elapsed := time.Since(started); elapsed < 1900*time.Millisecond || elapsed > 3*time.Second {
		t.Fatal("ready deadline", elapsed)
	}
}

func TestReadinessCancellationClosesBlockedRealPipe(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	defer w.Close()
	fillDone := make(chan struct{})
	go func() { _, _ = w.Write(make([]byte, 4*1024*1024)); close(fillDone) }()
	// No reader: a multi-megabyte write must block on the OS pipe. The readiness
	// writer will wait on that descriptor's write lock until Close cancels both.
	select {
	case <-fillDone:
		t.Fatal("test pipe was not blocked")
	case <-time.After(30 * time.Millisecond):
	}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	if WriteReady(ctx, w) != ErrReady {
		t.Fatal("blocked pipe readiness succeeded")
	}
	select {
	case <-fillDone:
	case <-time.After(time.Second):
		t.Fatal("pipe Close did not interrupt write")
	}
}

func TestFailureOutputIsFixed(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	if err := WriteFailure(context.Background(), w); err != nil {
		t.Fatal(err)
	}
	w.Close()
	raw, err := io.ReadAll(r)
	if err != nil || string(raw) != FailureRecord {
		t.Fatal("failure record", err)
	}
}
