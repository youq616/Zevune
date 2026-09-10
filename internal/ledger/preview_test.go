package ledger

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"math"
	"reflect"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/youq616/Zevune/internal/protocol"
)

// All passing proofs in these tests are PUBLICLY FORGEABLE checksums from
// engine_test.go. They test state-machine mechanics, never payment privacy.
func TestPreviewDoesNotChangeMemoryOrJournal(t *testing.T) {
	e := openTestDisk(t, t.TempDir())
	before, saved, raw := e.Summary(), e.s.clone(), diskBytes(t, e)
	txs := []protocol.Envelope{transaction(e, "candidate")}
	p, err := e.PreviewBlock(1, txs)
	if err != nil || p.Result.Height != 1 || p.Result.CommitmentCount != 1 {
		t.Fatal(p, err)
	}
	for i := 0; i < 10; i++ {
		got, err := e.PreviewBlock(1, txs)
		if err != nil || got != p {
			t.Fatal("preview was not deterministic", err)
		}
	}
	if e.Summary() != before || !reflect.DeepEqual(saved, e.s) || !bytes.Equal(raw, diskBytes(t, e)) {
		t.Fatal("preview mutated committed state")
	}
	if err := e.CheckTx(txs[0]); err != nil {
		t.Fatal("preview reserved a nullifier", err)
	}
}

func TestPreviewCompetingBlocksRemainIndependent(t *testing.T) {
	e := testEngine(t)
	a := []protocol.Envelope{transaction(e, "a")}
	b := []protocol.Envelope{transaction(e, "b")}
	pa, err := e.PreviewBlock(1, a)
	if err != nil {
		t.Fatal(err)
	}
	pb, err := e.PreviewBlock(1, b)
	if err != nil || pa.BaseAppHash != pb.BaseAppHash || pa.BlockID == pb.BlockID {
		t.Fatal(pb, err)
	}
	got, err := e.CommitPreview(pb, b)
	if err != nil || got != pb.Result {
		t.Fatal(got, err)
	}
	if _, err = e.CommitPreview(pa, a); !errors.Is(err, ErrStalePreview) {
		t.Fatal(err)
	}
	if e.Summary() != got {
		t.Fatal("stale preview changed state")
	}
}

func TestPreviewMatchesDirectApplyAcrossRootWindow(t *testing.T) {
	a, b := testEngine(t), testEngine(t)
	for height := uint64(1); height <= RootWindow+5; height++ {
		txs := []protocol.Envelope{transaction(a, fmt.Sprint(height))}
		p, err := a.PreviewBlock(height, txs)
		if err != nil {
			t.Fatal(err)
		}
		actual, err := b.ApplyBlock(height, txs)
		if err != nil || actual != p.Result {
			t.Fatal("legacy apply differs", height, err)
		}
		committed, err := a.CommitPreview(p, txs)
		if err != nil || committed != actual {
			t.Fatal("checked commit differs", height, err)
		}
	}
}

func TestPreviewInvalidBlockLeavesNoPartialState(t *testing.T) {
	for _, kind := range []string{"proof", "double-spend", "output", "anchor", "chain", "expiry"} {
		t.Run(kind, func(t *testing.T) {
			e := openTestDisk(t, t.TempDir())
			before, raw := e.Summary(), diskBytes(t, e)
			a, b := transaction(e, "a"), transaction(e, "b")
			switch kind {
			case "double-spend":
				b.Nullifiers = a.Nullifiers
			case "output":
				b.Outputs[0].Commitment = a.Outputs[0].Commitment
			case "anchor":
				b.Anchor[0] ^= 1
			case "chain":
				b.ChainID = "another-chain"
			case "expiry":
				b.ExpiryHeight = 0
			}
			reproof(&b)
			if kind == "proof" {
				b.Proof[0] ^= 1
			}
			if _, err := e.PreviewBlock(1, []protocol.Envelope{a, b}); err == nil {
				t.Fatal("bad proposal accepted")
			}
			if e.Summary() != before || !bytes.Equal(raw, diskBytes(t, e)) {
				t.Fatal("partial preview published")
			}
		})
	}
}

func TestCommitPreviewRejectsAlteredDescription(t *testing.T) {
	for _, field := range []string{"base", "height", "id", "root", "apphash", "fees", "count", "chain", "result-height", "spent"} {
		t.Run(field, func(t *testing.T) {
			e := openTestDisk(t, t.TempDir())
			txs := []protocol.Envelope{transaction(e, "a")}
			p, err := e.PreviewBlock(1, txs)
			if err != nil {
				t.Fatal(err)
			}
			bad := p
			switch field {
			case "base":
				bad.BaseAppHash[0] ^= 1
			case "height":
				bad.Height++
			case "id":
				bad.BlockID[0] ^= 1
			case "root":
				bad.Result.Root[0] ^= 1
			case "apphash":
				bad.Result.AppHash[0] ^= 1
			case "fees":
				bad.Result.PublicFees++
			case "count":
				bad.Result.CommitmentCount++
			case "chain":
				bad.Result.ChainID = "other"
			case "result-height":
				bad.Result.Height++
			case "spent":
				bad.Result.SpentCount++
			}
			before, raw := e.Summary(), diskBytes(t, e)
			if _, err = e.CommitPreview(bad, txs); err == nil {
				t.Fatal("altered preview trusted")
			}
			if e.Summary() != before || !bytes.Equal(raw, diskBytes(t, e)) {
				t.Fatal("mismatch wrote state")
			}
			if _, err = e.CommitPreview(p, txs); err != nil {
				t.Fatal("rejection poisoned engine", err)
			}
		})
	}
}

func TestCommitPreviewRejectsChangedTransaction(t *testing.T) {
	e := openTestDisk(t, t.TempDir())
	tx := transaction(e, "a")
	p, err := e.PreviewBlock(1, []protocol.Envelope{tx})
	if err != nil {
		t.Fatal(err)
	}
	before, raw := e.Summary(), diskBytes(t, e)
	tx.Fee++
	reproof(&tx) // Still valid in the test model, but not the previewed block.
	if _, err = e.CommitPreview(p, []protocol.Envelope{tx}); !errors.Is(err, ErrPreviewMismatch) {
		t.Fatal(err)
	}
	if e.Summary() != before || !bytes.Equal(raw, diskBytes(t, e)) {
		t.Fatal("changed bytes accepted")
	}
}

func TestBlockDigestBindsChainHeightOrderAndProofBytes(t *testing.T) {
	e := testEngine(t)
	a, b := transaction(e, "a"), transaction(e, "b")
	base, err := blockDigest(e.chainID, 1, []protocol.Envelope{a, b})
	if err != nil {
		t.Fatal(err)
	}
	proofChanged := a.Clone()
	proofChanged.Proof[0] ^= 1
	for _, tc := range []struct {
		chain  string
		height uint64
		txs    []protocol.Envelope
	}{
		{"other", 1, []protocol.Envelope{a, b}}, {e.chainID, 2, []protocol.Envelope{a, b}},
		{e.chainID, 1, []protocol.Envelope{b, a}}, {e.chainID, 1, []protocol.Envelope{a}},
		{e.chainID, 1, []protocol.Envelope{proofChanged, b}},
	} {
		h, err := blockDigest(tc.chain, tc.height, tc.txs)
		if err != nil || h == base {
			t.Fatal("unbound field", err)
		}
	}
}

func TestCommitPreviewDoesNotBypassUnavailableVerifier(t *testing.T) {
	e := testEngine(t)
	txs := []protocol.Envelope{transaction(e, "test")}
	p, err := e.PreviewBlock(1, txs)
	if err != nil {
		t.Fatal(err)
	}
	closed, err := OpenPersistent(e.chainID, t.TempDir(), nil, UnavailableVerifier{})
	if err != nil {
		t.Fatal(err)
	}
	defer closed.Close()
	before, raw := closed.Summary(), diskBytes(t, closed)
	if _, err = closed.PreviewBlock(1, txs); !errors.Is(err, ErrProofBackendUnavailable) {
		t.Fatal(err)
	}
	if _, err = closed.CommitPreview(p, txs); !errors.Is(err, ErrProofBackendUnavailable) {
		t.Fatal("forged preview bypassed verifier", err)
	}
	if closed.Summary() != before || !bytes.Equal(raw, diskBytes(t, closed)) {
		t.Fatal("payment accepted")
	}
}

type previewCountingVerifier struct{ calls atomic.Int32 }

func (v *previewCountingVerifier) Verify(tx protocol.Envelope) error {
	v.calls.Add(1)
	return (testOnlyChecksumVerifier{}).Verify(tx)
}
func TestCommitPreviewReverifiesProof(t *testing.T) {
	v := &previewCountingVerifier{}
	e, err := New(diskChain, nil, v)
	if err != nil {
		t.Fatal(err)
	}
	txs := []protocol.Envelope{transaction(e, "reverify")}
	p, err := e.PreviewBlock(1, txs)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = e.CommitPreview(p, txs); err != nil || v.calls.Load() != 2 {
		t.Fatal(v.calls.Load(), err)
	}
	if _, err = e.CommitPreview(p, txs); !errors.Is(err, ErrStalePreview) {
		t.Fatal("duplicate commit", err)
	}
}

func TestPreviewAndCommitAcrossRestart(t *testing.T) {
	dir := t.TempDir()
	e := openTestDisk(t, dir)
	txs := []protocol.Envelope{transaction(e, "restart")}
	p, err := e.PreviewBlock(1, txs)
	if err != nil {
		t.Fatal(err)
	}
	before, raw := e.Summary(), diskBytes(t, e)
	_ = e.Close()
	e = openTestDisk(t, dir)
	if e.Summary() != before || !bytes.Equal(raw, diskBytes(t, e)) {
		t.Fatal("uncommitted candidate survived")
	}
	got, err := e.CommitPreview(p, txs) // Description may survive; proof is revalidated.
	if err != nil || got != p.Result {
		t.Fatal(got, err)
	}
	raw = diskBytes(t, e)
	_ = e.Close()
	e = openTestDisk(t, dir)
	if e.Summary() != got || !bytes.Equal(raw, diskBytes(t, e)) {
		t.Fatal("committed candidate lost")
	}
	if _, err = e.CommitPreview(p, txs); !errors.Is(err, ErrStalePreview) {
		t.Fatal(err)
	}
}

func TestCommitPreviewStorageFailureStopsEngine(t *testing.T) {
	for _, kind := range []string{"write", "short-write", "sync"} {
		t.Run(kind, func(t *testing.T) {
			dir := t.TempDir()
			e := openTestDisk(t, dir)
			p, err := e.PreviewBlock(1, nil)
			if err != nil {
				t.Fatal(err)
			}
			before := e.Summary()
			switch kind {
			case "write":
				e.journal.write = func([]byte) (int, error) { return 0, io.ErrClosedPipe }
			case "short-write":
				e.journal.write = func(b []byte) (int, error) { return e.journal.f.Write(b[:len(b)/2]) }
			case "sync":
				e.journal.sync = func() error { return errors.New("test sync failure") }
			}
			if _, err = e.CommitPreview(p, nil); !errors.Is(err, ErrStorageUnavailable) {
				t.Fatal(err)
			}
			if e.Summary() != before || e.StorageStatus().Available {
				t.Fatal("failed disk write advanced state")
			}
			if _, err = e.PreviewBlock(1, nil); !errors.Is(err, ErrStorageUnavailable) {
				t.Fatal(err)
			}
			if _, err = e.CommitPreview(p, nil); !errors.Is(err, ErrStorageUnavailable) {
				t.Fatal(err)
			}
			_ = e.Close()
			if kind == "sync" {
				reopened := openTestDisk(t, dir)
				if reopened.Summary() != p.Result {
					t.Fatal("complete uncertain write not recovered")
				}
			}
		})
	}
}

func TestConcurrentPreviewAndCommit(t *testing.T) {
	e := openTestDisk(t, t.TempDir())
	txs := []protocol.Envelope{transaction(e, "concurrent")}
	p, err := e.PreviewBlock(1, txs)
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	results := make(chan error, 16)
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			got, err := e.PreviewBlock(1, txs)
			if err == nil && got != p {
				err = errors.New("divergent preview")
			}
			results <- err
		}()
	}
	wg.Wait()
	for i := 0; i < 16; i++ {
		if err := <-results; err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); _, err := e.CommitPreview(p, txs); results <- err }()
	}
	wg.Wait()
	close(results)
	accepted := 0
	for err := range results {
		if err == nil {
			accepted++
		} else if !errors.Is(err, ErrStalePreview) {
			t.Fatal(err)
		}
	}
	if accepted != 1 || e.Summary() != p.Result {
		t.Fatal("competing commit", accepted)
	}
}

func TestPreviewRejectsBoundsAndOverflow(t *testing.T) {
	e := testEngine(t)
	if _, err := e.PreviewBlock(2, nil); !errors.Is(err, ErrHeight) {
		t.Fatal(err)
	}
	if _, err := e.PreviewBlock(1, make([]protocol.Envelope, MaxBlockTransactions+1)); !errors.Is(err, ErrBlockLimit) {
		t.Fatal(err)
	}
	x := transaction(e, "large")
	x.Proof = make([]byte, protocol.MaxProofBytes)
	txs := make([]protocol.Envelope, 40)
	for i := range txs {
		txs[i] = x
	}
	if _, err := e.PreviewBlock(1, txs); !errors.Is(err, ErrBlockLimit) {
		t.Fatal(err)
	}
	e.s.height = math.MaxUint64
	if _, err := e.PreviewBlock(0, nil); !errors.Is(err, ErrHeight) {
		t.Fatal(err)
	}
	if _, err := e.CommitPreview(BlockPreview{}, nil); !errors.Is(err, ErrStalePreview) {
		t.Fatal(err)
	}
}

func TestPreviewAfterCloseRejected(t *testing.T) {
	e := testEngine(t)
	p, err := e.PreviewBlock(1, nil)
	if err != nil {
		t.Fatal(err)
	}
	_ = e.Close()
	if _, err = e.PreviewBlock(1, nil); !errors.Is(err, ErrClosed) {
		t.Fatal(err)
	}
	if _, err = e.CommitPreview(p, nil); !errors.Is(err, ErrClosed) {
		t.Fatal(err)
	}
}

func TestPreviewDoesNotRetainCallerSlices(t *testing.T) {
	e := testEngine(t)
	x := transaction(e, "owned")
	original := x.Clone()
	p, err := e.PreviewBlock(1, []protocol.Envelope{x})
	if err != nil {
		t.Fatal(err)
	}
	x.Outputs[0].Ciphertext[0] ^= 1
	x.Nullifiers[0][0] ^= 1
	x.Proof[0] ^= 1
	got, err := e.CommitPreview(p, []protocol.Envelope{original})
	if err != nil || got != p.Result {
		t.Fatal("retained caller-owned buffers", err)
	}
}

func TestBlockDigestKnownEmptyVector(t *testing.T) {
	h, err := blockDigest(diskChain, 1, nil)
	if err != nil || h.String() != "90a481f9e6e45ea4989956ecde0f45f4a04c6bf1c2192346973f7c0863e448d5" {
		t.Fatal(h, err)
	}
}
