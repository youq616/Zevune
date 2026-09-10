package ledger

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"github.com/youq616/Zevune/internal/protocol"
	"math"
	"sync"
	"sync/atomic"
	"testing"
)

// This PUBLICLY FORGEABLE checksum is ONLY a deterministic test double.
// It is neither a zero-knowledge proof nor a signature. It never enters a binary.
type testOnlyChecksumVerifier struct{}

func (testOnlyChecksumVerifier) Verify(tx protocol.Envelope) error {
	h, e := tx.EffectDigest()
	if e != nil {
		return e
	}
	if !bytes.Equal(tx.Proof, h[:]) {
		return errors.New("bad TEST ONLY checksum")
	}
	return nil
}
func reproof(tx *protocol.Envelope) {
	tx.Proof = []byte{1}
	h, _ := tx.EffectDigest()
	tx.Proof = append([]byte(nil), h[:]...)
}
func testEngine(t *testing.T) *Engine {
	t.Helper()
	e, err := New("veil-local-devnet-1", nil, testOnlyChecksumVerifier{})
	if err != nil {
		t.Fatal(err)
	}
	return e
}
func transaction(e *Engine, name string) protocol.Envelope {
	x := protocol.Envelope{Version: protocol.Version, ChainID: e.chainID, CircuitID: protocol.CircuitID, Anchor: e.Summary().Root, ExpiryHeight: 10000, Fee: 1, Nullifiers: []protocol.Hash{sha256.Sum256([]byte("nullifier:" + name))}, Outputs: []protocol.Output{{Commitment: sha256.Sum256([]byte("output:" + name)), EphemeralKey: sha256.Sum256([]byte("ephemeral:" + name)), Ciphertext: make([]byte, protocol.CiphertextBytes)}}}
	reproof(&x)
	return x
}
func TestDefaultVerifierFailsClosed(t *testing.T) {
	e, _ := New("veil-local-devnet-1", nil, UnavailableVerifier{})
	x := transaction(e, "a")
	before := e.Summary()
	if !errors.Is(e.CheckTx(x), ErrProofBackendUnavailable) {
		t.Fatal("check did not fail closed")
	}
	if _, err := e.ApplyBlock(1, []protocol.Envelope{x}); !errors.Is(err, ErrProofBackendUnavailable) {
		t.Fatal("apply did not fail closed", err)
	}
	if e.Summary() != before {
		t.Fatal("state changed")
	}
}
func TestNilVerifierRejected(t *testing.T) {
	if _, e := New("local", nil, nil); !errors.Is(e, ErrProofBackendUnavailable) {
		t.Fatal(e)
	}
}
func TestInvalidGenesisRejected(t *testing.T) {
	h := protocol.Hash{1}
	if _, e := New("local", []protocol.Hash{h, h}, UnavailableVerifier{}); !errors.Is(e, ErrDuplicateOutput) {
		t.Fatal(e)
	}
	if _, e := New("INVALID", nil, UnavailableVerifier{}); e == nil {
		t.Fatal("invalid chain accepted")
	}
	if _, e := New("local", make([]protocol.Hash, 1025), UnavailableVerifier{}); e == nil {
		t.Fatal("oversize genesis")
	}
}
func TestApplyWithTESTONLYVerifier(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	s, err := e.ApplyBlock(1, []protocol.Envelope{x})
	if err != nil {
		t.Fatal(err)
	}
	if s.Height != 1 || s.CommitmentCount != 1 || s.SpentCount != 1 || s.PublicFees != 1 {
		t.Fatal(s)
	}
}
func TestCheckDoesNotMutate(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	s := e.Summary()
	for i := 0; i < 3; i++ {
		if err := e.CheckTx(x); err != nil {
			t.Fatal(err)
		}
	}
	if e.Summary() != s {
		t.Fatal("check mutates ledger")
	}
}
func TestCrossTransactionDoubleSpend(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	if _, err := e.ApplyBlock(1, []protocol.Envelope{x}); err != nil {
		t.Fatal(err)
	}
	if !errors.Is(e.CheckTx(x), ErrDoubleSpend) {
		t.Fatal("replay accepted")
	}
}
func TestDuplicateWithinTransaction(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	x.Nullifiers = append(x.Nullifiers, x.Nullifiers[0])
	reproof(&x)
	if !errors.Is(e.CheckTx(x), ErrDoubleSpend) {
		t.Fatal("duplicate nullifier")
	}
}
func TestOutputUniqueness(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	x.Outputs = append(x.Outputs, x.Outputs[0])
	reproof(&x)
	if !errors.Is(e.CheckTx(x), ErrDuplicateOutput) {
		t.Fatal("duplicate output")
	}
}
func TestExistingOutputRejected(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	_, _ = e.ApplyBlock(1, []protocol.Envelope{x})
	y := transaction(e, "b")
	y.Outputs[0].Commitment = x.Outputs[0].Commitment
	reproof(&y)
	if !errors.Is(e.CheckTx(y), ErrDuplicateOutput) {
		t.Fatal("existing output")
	}
}
func TestAtomicRollbackOnLaterDoubleSpend(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	y := transaction(e, "b")
	y.Nullifiers = x.Nullifiers
	reproof(&y)
	before := e.Summary()
	if _, err := e.ApplyBlock(1, []protocol.Envelope{x, y}); !errors.Is(err, ErrDoubleSpend) {
		t.Fatal(err)
	}
	if e.Summary() != before {
		t.Fatal("partial commit")
	}
	if err := e.CheckTx(x); err != nil {
		t.Fatal("failed block poisoned state", err)
	}
}
func TestAtomicRollbackOnBadProof(t *testing.T) {
	e := testEngine(t)
	x, y := transaction(e, "a"), transaction(e, "b")
	y.Proof[0] ^= 1
	before := e.Summary()
	if _, err := e.ApplyBlock(1, []protocol.Envelope{x, y}); err == nil {
		t.Fatal("bad proof accepted")
	}
	if e.Summary() != before {
		t.Fatal("partial commit")
	}
}
func TestProofBindsMutatedFee(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	x.Fee++
	if e.CheckTx(x) == nil {
		t.Fatal("unbound fee")
	}
}
func TestWrongChainExpiryAndAnchor(t *testing.T) {
	for name, expected := range map[string]error{"chain": ErrWrongChain, "expiry": ErrExpired, "anchor": ErrUnknownAnchor} {
		t.Run(name, func(t *testing.T) {
			e := testEngine(t)
			_, _ = e.ApplyBlock(1, nil)
			x := transaction(e, "a")
			switch name {
			case "chain":
				x.ChainID = "other-chain"
			case "expiry":
				x.ExpiryHeight = 1
			case "anchor":
				x.Anchor = protocol.Hash{99}
			}
			reproof(&x)
			if !errors.Is(e.CheckTx(x), expected) {
				t.Fatal("expected", expected)
			}
		})
	}
}
func TestExpiryIsInclusive(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	x.ExpiryHeight = 1
	reproof(&x)
	if _, err := e.ApplyBlock(1, []protocol.Envelope{x}); err != nil {
		t.Fatal(err)
	}
}
func TestUnknownBlockHeight(t *testing.T) {
	e := testEngine(t)
	if _, err := e.ApplyBlock(2, nil); !errors.Is(err, ErrHeight) {
		t.Fatal(err)
	}
}
func TestBlockCountLimit(t *testing.T) {
	e := testEngine(t)
	if _, err := e.ApplyBlock(1, make([]protocol.Envelope, MaxBlockTransactions+1)); !errors.Is(err, ErrBlockLimit) {
		t.Fatal(err)
	}
}
func TestBlockByteLimit(t *testing.T) {
	e := testEngine(t)
	xs := make([]protocol.Envelope, 33)
	for i := range xs {
		xs[i] = transaction(e, fmt.Sprint(i))
		xs[i].Proof = make([]byte, protocol.MaxProofBytes)
	}
	if _, err := e.ApplyBlock(1, xs); !errors.Is(err, ErrBlockLimit) {
		t.Fatal(err)
	}
}
func TestDeterministicStateHash(t *testing.T) {
	a, b := testEngine(t), testEngine(t)
	xs := []protocol.Envelope{transaction(a, "a"), transaction(a, "b")}
	one, e1 := a.ApplyBlock(1, xs)
	two, e2 := b.ApplyBlock(1, xs)
	if e1 != nil || e2 != nil || one != two {
		t.Fatal("nondeterminism", e1, e2)
	}
}
func TestSameBlockDoubleSpendRejected(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	if _, err := e.ApplyBlock(1, []protocol.Envelope{x, x}); !errors.Is(err, ErrDoubleSpend) {
		t.Fatal(err)
	}
}
func TestCommittedRootWindow(t *testing.T) {
	e := testEngine(t)
	old := e.Summary().Root
	for i := uint64(1); i <= RootWindow; i++ {
		x := transaction(e, fmt.Sprint(i))
		if _, err := e.ApplyBlock(i, []protocol.Envelope{x}); err != nil {
			t.Fatal(err)
		}
	}
	x := transaction(e, "late")
	x.Anchor = old
	reproof(&x)
	if !errors.Is(e.CheckTx(x), ErrUnknownAnchor) {
		t.Fatal("stale root accepted")
	}
}
func TestConcurrentBlockApplicationIsSerialized(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	var successes atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := e.ApplyBlock(1, []protocol.Envelope{x}); err == nil {
				successes.Add(1)
			}
		}()
	}
	wg.Wait()
	if successes.Load() != 1 || e.Summary().SpentCount != 1 {
		t.Fatal("double application")
	}
}
func TestFeeOverflowRejected(t *testing.T) {
	e := testEngine(t)
	e.s.fees = math.MaxUint64
	x := transaction(e, "a")
	before := e.Summary()
	if _, err := e.ApplyBlock(1, []protocol.Envelope{x}); err == nil {
		t.Fatal("overflow")
	}
	if e.Summary() != before {
		t.Fatal("overflow changed state")
	}
}
func TestHeightOverflowRejected(t *testing.T) {
	e := testEngine(t)
	e.s.height = math.MaxUint64
	x := transaction(e, "a")
	if !errors.Is(e.CheckTx(x), ErrHeight) {
		t.Fatal("height wrapped")
	}
	if _, err := e.ApplyBlock(0, nil); !errors.Is(err, ErrHeight) {
		t.Fatal("height wrapped")
	}
}
func TestCallerMutationAfterCommitDoesNotAffectState(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "a")
	_, _ = e.ApplyBlock(1, []protocol.Envelope{x})
	before := e.Summary()
	x.Nullifiers[0][0] ^= 1
	x.Outputs[0].Commitment[0] ^= 1
	x.Proof[0] ^= 1
	if e.Summary() != before {
		t.Fatal("caller alias")
	}
}
