package ledger

import (
	"bytes"
	"encoding/binary"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"testing"

	"github.com/youq616/Zevune/internal/protocol"
)

const diskChain = "veil-local-devnet-1"

func openTestDisk(t *testing.T, dir string) *Engine {
	t.Helper()
	e, err := OpenPersistent(diskChain, dir, nil, testOnlyChecksumVerifier{})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = e.Close() })
	return e
}

func diskBytes(t *testing.T, e *Engine) []byte {
	t.Helper()
	info, err := e.journal.f.Stat()
	if err != nil {
		t.Fatal(err)
	}
	b := make([]byte, int(info.Size()))
	if _, err = e.journal.f.ReadAt(b, 0); err != nil {
		t.Fatal(err)
	}
	return b
}

func TestPersistentEmptyRestart(t *testing.T) {
	dir := t.TempDir()
	e := openTestDisk(t, dir)
	if s := e.StorageStatus(); s.Mode != "journal" || s.Recovered || !s.Available {
		t.Fatal(s)
	}
	before := e.Summary()
	data := diskBytes(t, e)
	if err := e.Close(); err != nil {
		t.Fatal(err)
	}
	e2 := openTestDisk(t, dir)
	if e2.Summary() != before || !bytes.Equal(data, diskBytes(t, e2)) {
		t.Fatal("restart changed state or file")
	}
	if !e2.StorageStatus().Recovered {
		t.Fatal("missing recovery status")
	}
}

func TestPersistentReplayAndDoubleSpend(t *testing.T) {
	dir := t.TempDir()
	e := openTestDisk(t, dir)
	first := transaction(e, "disk-first")
	if _, err := e.ApplyBlock(1, []protocol.Envelope{first}); err != nil {
		t.Fatal(err)
	}
	for h := uint64(2); h <= 70; h++ {
		if _, err := e.ApplyBlock(h, nil); err != nil {
			t.Fatal(err)
		}
	}
	last := transaction(e, "disk-last")
	if _, err := e.ApplyBlock(71, []protocol.Envelope{last}); err != nil {
		t.Fatal(err)
	}
	before := e.Summary()
	data := diskBytes(t, e)
	_ = e.Close()
	e2 := openTestDisk(t, dir)
	if e2.Summary() != before || !bytes.Equal(data, diskBytes(t, e2)) {
		t.Fatal("replay mismatch")
	}
	duplicate := transaction(e2, "new-output")
	duplicate.Nullifiers = first.Nullifiers
	reproof(&duplicate)
	if !errors.Is(e2.CheckTx(duplicate), ErrDoubleSpend) {
		t.Fatal("spent marker lost on restart")
	}
	if _, err := e2.ApplyBlock(72, nil); err != nil {
		t.Fatal(err)
	}
}

func TestPersistentWrongConfigurationLeavesFile(t *testing.T) {
	dir := t.TempDir()
	e := openTestDisk(t, dir)
	before := diskBytes(t, e)
	_ = e.Close()
	for _, tc := range []struct {
		chain   string
		genesis []protocol.Hash
	}{
		{"another-chain", nil}, {diskChain, []protocol.Hash{{1}}},
	} {
		if e, err := OpenPersistent(tc.chain, dir, tc.genesis, UnavailableVerifier{}); err == nil {
			_ = e.Close()
			t.Fatal("configuration mismatch accepted")
		}
	}
	after, _ := os.ReadFile(filepath.Join(dir, "ledger.journal"))
	if !bytes.Equal(before, after) {
		t.Fatal("existing file overwritten")
	}
}

func TestPersistentRevalidatesProofsOnReplay(t *testing.T) {
	dir := t.TempDir()
	e := openTestDisk(t, dir)
	if _, err := e.ApplyBlock(1, []protocol.Envelope{transaction(e, "synthetic")}); err != nil {
		t.Fatal(err)
	}
	_ = e.Close()
	if x, err := OpenPersistent(diskChain, dir, nil, UnavailableVerifier{}); err == nil {
		_ = x.Close()
		t.Fatal("test proof accepted by executable verifier")
	}
}

func TestPersistentUnavailableVerifierNeverWritesTransaction(t *testing.T) {
	dir := t.TempDir()
	e, err := OpenPersistent(diskChain, dir, nil, UnavailableVerifier{})
	if err != nil {
		t.Fatal(err)
	}
	defer e.Close()
	before := e.Summary()
	data := diskBytes(t, e)
	if _, err = e.ApplyBlock(1, []protocol.Envelope{transaction(e, "reject")}); !errors.Is(err, ErrProofBackendUnavailable) {
		t.Fatal(err)
	}
	if e.Summary() != before || !bytes.Equal(data, diskBytes(t, e)) {
		t.Fatal("rejected payment changed state")
	}
}

func TestPersistentInvalidWholeBlockDoesNotWrite(t *testing.T) {
	e := openTestDisk(t, t.TempDir())
	before := e.Summary()
	data := diskBytes(t, e)
	good := transaction(e, "good")
	bad := transaction(e, "bad")
	bad.Proof = []byte{0}
	if _, err := e.ApplyBlock(1, []protocol.Envelope{good, bad}); err == nil {
		t.Fatal("invalid block accepted")
	}
	if e.Summary() != before || !bytes.Equal(data, diskBytes(t, e)) {
		t.Fatal("partial block was committed")
	}
}

func TestPersistentShortWriteStopsFurtherOperations(t *testing.T) {
	dir := t.TempDir()
	e := openTestDisk(t, dir)
	before := e.Summary()
	e.journal.write = func(b []byte) (int, error) { return e.journal.f.Write(b[:len(b)/2]) }
	if _, err := e.ApplyBlock(1, nil); !errors.Is(err, ErrStorageUnavailable) {
		t.Fatal(err)
	}
	if e.Summary() != before {
		t.Fatal("memory advanced on write failure")
	}
	if _, err := e.ApplyBlock(1, nil); !errors.Is(err, ErrStorageUnavailable) {
		t.Fatal(err)
	}
	if err := e.CheckTx(transaction(e, "a")); !errors.Is(err, ErrStorageUnavailable) {
		t.Fatal(err)
	}
	if e.StorageStatus().Available {
		t.Fatal("failed storage marked available")
	}
	_ = e.Close()
	if x, err := OpenPersistent(diskChain, dir, nil, UnavailableVerifier{}); err == nil {
		_ = x.Close()
		t.Fatal("partial tail silently discarded")
	}
}

func TestPersistentSyncFailureHasExplicitUncertainOutcome(t *testing.T) {
	dir := t.TempDir()
	e := openTestDisk(t, dir)
	before := e.Summary()
	e.journal.sync = func() error { return errors.New("injected sync failure") }
	if _, err := e.ApplyBlock(1, nil); !errors.Is(err, ErrStorageUnavailable) {
		t.Fatal(err)
	}
	if e.Summary() != before {
		t.Fatal("memory advanced before confirmed sync")
	}
	_ = e.Close()
	// A failed sync is not a guarantee that bytes did not reach disk. Reopen must
	// validate the on-disk record, not blindly retry or claim rollback.
	e2 := openTestDisk(t, dir)
	if e2.Summary().Height != 1 {
		t.Fatal("complete record not recovered")
	}
}

func TestPersistentLimitFailureLeavesMemoryUnchanged(t *testing.T) {
	for _, kind := range []string{"bytes", "blocks"} {
		t.Run(kind, func(t *testing.T) {
			e := openTestDisk(t, t.TempDir())
			before := e.Summary()
			data := diskBytes(t, e)
			if kind == "bytes" {
				e.journal.size = MaxJournalBytes
			} else {
				e.journal.blocks = maxJournalBlocks
			}
			if _, err := e.ApplyBlock(1, nil); err == nil {
				t.Fatal("limit ignored")
			}
			if e.Summary() != before || !bytes.Equal(data, diskBytes(t, e)) {
				t.Fatal("limit failure wrote state")
			}
		})
	}
}

func TestPersistentCorruptionRejectedWithoutRepair(t *testing.T) {
	originalDir := t.TempDir()
	e := openTestDisk(t, originalDir)
	_, _ = e.ApplyBlock(1, nil)
	original := diskBytes(t, e)
	_ = e.Close()
	for _, kind := range []string{"empty", "short-header", "short-body", "checksum", "length", "trailing"} {
		t.Run(kind, func(t *testing.T) {
			b := append([]byte(nil), original...)
			switch kind {
			case "empty":
				b = nil
			case "short-header":
				b = b[:2]
			case "short-body":
				b = b[:len(b)-1]
			case "checksum":
				b[len(b)-1] ^= 1
			case "length":
				binary.BigEndian.PutUint32(b[:4], uint32(maxFrameBytes+1))
			case "trailing":
				b = append(b, 1)
			}
			dir := t.TempDir()
			p := filepath.Join(dir, "ledger.journal")
			if err := os.WriteFile(p, b, 0600); err != nil {
				t.Fatal(err)
			}
			if x, err := OpenPersistent(diskChain, dir, nil, UnavailableVerifier{}); err == nil {
				_ = x.Close()
				t.Fatal("bad journal accepted")
			}
			after, err := os.ReadFile(p)
			if err != nil || !bytes.Equal(b, after) {
				t.Fatal("corrupt file was modified")
			}
		})
	}
}

func TestPersistentOversizeFileRejected(t *testing.T) {
	dir := t.TempDir()
	f, err := os.Create(filepath.Join(dir, "ledger.journal"))
	if err != nil {
		t.Fatal(err)
	}
	if err = f.Truncate(MaxJournalBytes + 1); err != nil {
		_ = f.Close()
		t.Fatal(err)
	}
	_ = f.Close()
	if x, err := OpenPersistent(diskChain, dir, nil, UnavailableVerifier{}); err == nil {
		_ = x.Close()
		t.Fatal("oversize accepted")
	}
}

func TestPersistentLockAndRelease(t *testing.T) {
	dir := t.TempDir()
	e := openTestDisk(t, dir)
	if x, err := OpenPersistent(diskChain, dir, nil, UnavailableVerifier{}); !errors.Is(err, ErrJournalLocked) {
		if x != nil {
			_ = x.Close()
		}
		t.Fatal(err)
	}
	_ = e.Close()
	_ = openTestDisk(t, dir)
}

func TestPersistentProcessLockHelper(t *testing.T) {
	dir := os.Getenv("ZEVUNE_TEST_JOURNAL_DIR")
	if dir == "" {
		return
	}
	e, err := OpenPersistent(diskChain, dir, nil, UnavailableVerifier{})
	if os.Getenv("ZEVUNE_TEST_EXPECT_LOCKED") == "1" {
		if !errors.Is(err, ErrJournalLocked) {
			os.Exit(21)
		}
		os.Exit(0)
	}
	if err != nil {
		os.Exit(22)
	}
	_, err = e.ApplyBlock(1, nil)
	if err != nil {
		os.Exit(23)
	}
	// Exit deliberately bypasses Close: exercises OS lock release and replay.
	os.Exit(0)
}

func TestPersistentCrossProcessLock(t *testing.T) {
	dir := t.TempDir()
	e := openTestDisk(t, dir)
	cmd := exec.Command(os.Args[0], "-test.run=^TestPersistentProcessLockHelper$")
	cmd.Env = append(os.Environ(), "ZEVUNE_TEST_JOURNAL_DIR="+dir, "ZEVUNE_TEST_EXPECT_LOCKED=1")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("lock helper: %v %s", err, out)
	}
	_ = e.Close()
}

func TestPersistentRecoveryAfterProcessExit(t *testing.T) {
	dir := t.TempDir()
	cmd := exec.Command(os.Args[0], "-test.run=^TestPersistentProcessLockHelper$")
	cmd.Env = append(os.Environ(), "ZEVUNE_TEST_JOURNAL_DIR="+dir, "ZEVUNE_TEST_EXPECT_LOCKED=0")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("exit helper: %v %s", err, out)
	}
	e := openTestDisk(t, dir)
	if e.Summary().Height != 1 {
		t.Fatal("synced block lost after abrupt exit")
	}
}

func TestPersistentCloseIsIdempotent(t *testing.T) {
	e := openTestDisk(t, t.TempDir())
	if err := e.Close(); err != nil {
		t.Fatal(err)
	}
	if err := e.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := e.ApplyBlock(1, nil); !errors.Is(err, ErrClosed) {
		t.Fatal(err)
	}
	if err := e.CheckTx(transaction(e, "closed")); !errors.Is(err, ErrClosed) {
		t.Fatal(err)
	}
	if e.StorageStatus().Available {
		t.Fatal("closed is available")
	}
}

func TestPersistentConcurrentApplySerializes(t *testing.T) {
	e := openTestDisk(t, t.TempDir())
	var wg sync.WaitGroup
	results := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); _, err := e.ApplyBlock(1, nil); results <- err }()
	}
	wg.Wait()
	close(results)
	accepted := 0
	for err := range results {
		if err == nil {
			accepted++
		} else if !errors.Is(err, ErrHeight) {
			t.Fatal(err)
		}
	}
	if accepted != 1 {
		t.Fatal(accepted)
	}
}

func TestPersistentInvalidArguments(t *testing.T) {
	if _, err := OpenPersistent(diskChain, "", nil, UnavailableVerifier{}); err == nil {
		t.Fatal("empty dir")
	}
	if _, err := OpenPersistent("INVALID", t.TempDir(), nil, UnavailableVerifier{}); err == nil {
		t.Fatal("bad chain")
	}
	if _, err := OpenPersistent(diskChain, t.TempDir(), nil, nil); err == nil {
		t.Fatal("nil verifier")
	}
	dir := t.TempDir()
	if err := os.Mkdir(filepath.Join(dir, "ledger.journal"), 0700); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenPersistent(diskChain, dir, nil, UnavailableVerifier{}); err == nil {
		t.Fatal("directory accepted as file")
	}
}

func TestJournalBlockDecoderRejectsBadShapes(t *testing.T) {
	valid := make([]byte, 12)
	binary.BigEndian.PutUint64(valid, 1)
	for _, b := range [][]byte{nil, valid[:11], append(append([]byte(nil), valid...), 0), bytes.Repeat([]byte{255}, 12)} {
		if _, _, err := decodeBlock(b); err == nil {
			t.Fatal("bad block accepted")
		}
	}
	if h, txs, err := decodeBlock(valid); err != nil || h != 1 || len(txs) != 0 {
		t.Fatal(h, txs, err)
	}
}

func TestJournalWriteErrorDoesNotAdvanceDigest(t *testing.T) {
	e := openTestDisk(t, t.TempDir())
	tail := e.journal.tail
	size := e.journal.size
	e.journal.write = func([]byte) (int, error) { return 0, io.ErrClosedPipe }
	if _, err := e.ApplyBlock(1, nil); err == nil {
		t.Fatal("write failure hidden")
	}
	if e.journal.tail != tail || e.journal.size != size {
		t.Fatal("journal cursor advanced")
	}
}

func FuzzJournalBlockDecode(f *testing.F) {
	f.Add([]byte{})
	f.Add(make([]byte, 12))
	f.Add(bytes.Repeat([]byte{255}, 12))
	f.Fuzz(func(t *testing.T, b []byte) { _, _, _ = decodeBlock(b) })
}
