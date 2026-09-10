//go:build orchard_e2e

package orchardbridge

import (
	"context"
	"crypto/sha256"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// This test MUST use a compiled genuine Rust worker and the public fixture from
// the actual Orchard proof test. Missing tools/fixtures are failures, not skips.
func TestGenuineRustWorkerAuthorization(t *testing.T) {
	executable := os.Getenv("ZEVUNE_REAL_WORKER")
	fixture := os.Getenv("ZEVUNE_PUBLIC_FIXTURE")
	if executable == "" || fixture == "" {
		t.Fatal("real worker and public fixture are required")
	}
	executable, err := filepath.Abs(executable)
	if err != nil {
		t.Fatal(err)
	}
	binary, err := os.ReadFile(executable)
	if err != nil {
		t.Fatal(err)
	}
	// This digest trusts the build made in THIS test run. Product distributions
	// need an independently trusted release manifest, not self-approved downloads.
	hash := sha256.Sum256(binary)
	raw, err := os.ReadFile(fixture)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	w, err := Start(ctx, Options{Executable: executable, ExpectedSHA256: hash})
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close()
	for i := 0; i < 3; i++ {
		result, err := w.VerifyAuthorization(ctx, raw)
		if err != nil {
			t.Fatal(err)
		}
		if result.Digest() != PayloadDigest(raw) {
			t.Fatal("payload binding")
		}
		e, err := result.Envelope()
		if err != nil {
			t.Fatal(err)
		}
		state := &testState{anchor: e.Anchor}
		effects, err := result.CheckCommittedState(state)
		if err != nil {
			t.Fatal(err)
		}
		state.spent = map[Hash]bool{effects.Nullifiers[0]: true}
		if _, err = result.CheckCommittedState(state); !errors.Is(err, ErrState) {
			t.Fatal("double spend admitted", err)
		}
	}
	for _, offset := range []int{HeaderSize + 2*ActionSize + 4, HeaderSize + 820, len(raw) - 1, HeaderSize + 160} {
		changed := append([]byte(nil), raw...)
		changed[offset] ^= 1
		if _, err := w.VerifyAuthorization(ctx, changed); !errors.Is(err, ErrRejected) {
			t.Fatal("corrupt authorization accepted", err)
		}
	}
	if _, err = w.VerifyAuthorization(ctx, raw); err != nil {
		t.Fatal("rejection damaged worker", err)
	}
}
