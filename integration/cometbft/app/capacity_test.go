package app

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"os"
	"path/filepath"
	"testing"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/youq616/Zevune/internal/ledger"
)

// Write a valid legacy journal fixture with the existing 10,000-record limit.
// Empty blocks need no accepting verifier. A single fixture write avoids 10,000
// fsyncs in this regression; Open still validates every frame and replays every
// block through the production ledger before any ABCI assertion is made.
func fullJournalFixture(t *testing.T, dir string) {
	t.Helper()
	a := open(t, dir)
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "ledger.journal")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(data) < 36 || int(binary.BigEndian.Uint32(data[:4])) != len(data)-36 {
		t.Fatal("unexpected genesis fixture framing")
	}
	var previous [32]byte
	copy(previous[:], data[len(data)-32:])
	for height := uint64(1); height <= 10000; height++ {
		var frame [48]byte
		binary.BigEndian.PutUint32(frame[:4], 12)
		binary.BigEndian.PutUint64(frame[4:12], height)
		// frame[12:16] is the empty transaction count.
		digest := sha256.New()
		_, _ = digest.Write([]byte("ZEVUNE-LOCAL-JOURNAL\x00\x01"))
		_, _ = digest.Write(previous[:])
		_, _ = digest.Write(frame[:16])
		copy(previous[:], digest.Sum(nil))
		copy(frame[16:], previous[:])
		data = append(data, frame[:]...)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestJournalCapacityRejectsProposalsWithoutPendingState(t *testing.T) {
	dir := t.TempDir()
	fullJournalFixture(t, dir)
	path := filepath.Join(dir, "ledger.journal")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	a := open(t, dir)
	before := info(t, a)
	if before.LastBlockHeight != 10000 {
		t.Fatal("full journal did not replay")
	}
	if _, err := a.PrepareProposal(ctx, &abci.RequestPrepareProposal{Height: 10001}); !errors.Is(err, ledger.ErrJournalCapacity) {
		t.Fatal("PrepareProposal accepted a block that cannot be persisted", err)
	}
	processed, err := a.ProcessProposal(ctx, &abci.RequestProcessProposal{Height: 10001})
	if err != nil || processed.Status != abci.ResponseProcessProposal_REJECT {
		t.Fatal("ProcessProposal accepted a block that cannot be persisted", err)
	}
	if _, err := a.FinalizeBlock(ctx, request(10001)); !errors.Is(err, ledger.ErrJournalCapacity) {
		t.Fatal("FinalizeBlock accepted a block that cannot be persisted", err)
	}
	if a.pending != nil {
		t.Fatal("rejected finalization retained a pending commit")
	}
	if _, err := a.Commit(ctx, &abci.RequestCommit{}); err == nil {
		t.Fatal("Commit accepted a rejected finalization")
	}
	if _, err := a.engine.ApplyBlock(10001, nil); !errors.Is(err, ledger.ErrJournalCapacity) {
		t.Fatal("direct apply did not report deterministic capacity refusal", err)
	}
	after := info(t, a)
	if before.LastBlockHeight != after.LastBlockHeight || !bytes.Equal(before.LastBlockAppHash, after.LastBlockAppHash) {
		t.Fatal("capacity refusal changed committed state")
	}
	status, err := a.Query(ctx, &abci.RequestQuery{Path: "/status"})
	if err != nil || status.Code != 0 || status.Height != before.LastBlockHeight || !a.engine.StorageStatus().Available {
		t.Fatal("capacity refusal disabled committed status queries", err)
	}
	// Windows also enforces the exclusive journal byte lock against a new read
	// handle in this process. Compare complete bytes only after releasing it.
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	afterData, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(data, afterData) {
		t.Fatal("capacity refusal changed journal bytes", err)
	}
}
