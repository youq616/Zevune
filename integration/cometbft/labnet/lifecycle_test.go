package labnet

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestUnexpectedEngineExitIsNotSuccessfulShutdown(t *testing.T) {
	quit := make(chan struct{})
	close(quit)
	if err := awaitNodeStop(context.Background(), quit); !errors.Is(err, ErrNodeStopped) {
		t.Fatalf("unexpected engine exit was not reported: %v", err)
	}
}

func TestRequestedShutdownDoesNotNeedEngineExit(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := awaitNodeStop(ctx, make(chan struct{})); err != nil {
		t.Fatal(err)
	}
}

func TestConcurrentCancellationAndEngineExitRemainRequested(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	quit := make(chan struct{})
	close(quit)
	for i := 0; i < 100; i++ {
		if err := awaitNodeStop(ctx, quit); err != nil {
			t.Fatal(err)
		}
	}
}

func TestEngineExitReleasesWaitingSupervisor(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	quit := make(chan struct{})
	result := make(chan error, 1)
	go func() { result <- awaitNodeStop(ctx, quit) }()
	close(quit)
	select {
	case err := <-result:
		if !errors.Is(err, ErrNodeStopped) {
			t.Fatal(err)
		}
	case <-ctx.Done():
		t.Fatal("supervisor did not observe engine termination")
	}
}

func TestLifecycleRejectsMissingContext(t *testing.T) {
	if !errors.Is(awaitNodeStop(nil, nil), ErrBounds) {
		t.Fatal("nil context accepted")
	}
}
