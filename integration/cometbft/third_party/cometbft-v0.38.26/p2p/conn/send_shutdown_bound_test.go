package conn

import (
	"testing"
	"time"
)

// Verify the original real queue operation's bound without lowering its timeout
// or replacing it with a fake send. The lifecycle patch relies on joining it.
func TestShutdownInFlightQueueSendKeepsOriginalBound(t *testing.T) {
	ch := &Channel{sendQueue: make(chan []byte, 1)}
	if !ch.sendBytes([]byte{1}) {
		t.Fatal("initial queue admission failed")
	}
	start := time.Now()
	if ch.sendBytes([]byte{2}) {
		t.Fatal("full unconsumed queue accepted another send")
	}
	elapsed := time.Since(start)
	if elapsed < defaultSendTimeout {
		t.Fatalf("original timeout shortened: %v", elapsed)
	}
	if elapsed > defaultSendTimeout+5*time.Second {
		t.Fatalf("send failed to respect its bounded operation: %v", elapsed)
	}
	if len(ch.sendQueue) != 1 {
		t.Fatal("timeout changed queued message")
	}
}
