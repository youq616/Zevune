//go:build pool_e2e

package poolapp

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"path/filepath"
	"testing"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/youq616/Zevune/internal/poolbridge"
)

func TestRealProposalSelectionAndAtomicRejection(t *testing.T) {
	ctx := context.Background()
	a := open(t, filepath.Join(t.TempDir(), "pool.journal"), true)
	tx := fixture(t)
	broken := bytes.Clone(tx)
	broken[len(broken)-1] ^= 1
	initial := info(t, a)
	if _, err := a.InitChain(ctx, &abci.RequestInitChain{ChainId: "wrong-chain", InitialHeight: 1}); err == nil {
		t.Fatal("wrong genesis accepted")
	}
	for _, q := range []*abci.RequestQuery{{Path: "/private"}, {Path: "/status", Prove: true}, {Path: "/status", Height: 999}} {
		r, err := a.Query(ctx, q)
		if err != nil || r.Code == 0 {
			t.Fatal("unsupported query accepted", err)
		}
	}
	selected, err := a.PrepareProposal(ctx, &abci.RequestPrepareProposal{Height: 1, MaxTxBytes: 100000, Txs: [][]byte{broken, tx, tx}})
	if err != nil || len(selected.Txs) != 1 || !bytes.Equal(selected.Txs[0], tx) {
		t.Fatal("proposal selection accepted invalid or duplicate transaction", err)
	}
	empty, err := a.PrepareProposal(ctx, &abci.RequestPrepareProposal{Height: 1, MaxTxBytes: int64(len(tx) - 1), Txs: [][]byte{tx}})
	if err != nil || len(empty.Txs) != 0 {
		t.Fatal("proposal byte budget exceeded", err)
	}
	hash := sha256.Sum256([]byte("proposal-rejection-test"))
	for _, txs := range [][][]byte{{tx, broken}, {tx, tx}} {
		r, err := a.ProcessProposal(ctx, &abci.RequestProcessProposal{Height: 1, Hash: hash[:], Txs: txs})
		if err != nil || r.Status != abci.ResponseProcessProposal_REJECT {
			t.Fatal("invalid block approved", err)
		}
		if _, err = a.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Hash: hash[:], Txs: txs}); err == nil {
			t.Fatal("invalid block finalized")
		}
		current := info(t, a)
		if current.LastBlockHeight != 0 || !bytes.Equal(current.LastBlockAppHash, initial.LastBlockAppHash) {
			t.Fatal("rejected block mutated committed state")
		}
	}
	// Failed proposals/finalization must not reserve nullifiers or a pending slot.
	if _, err = a.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Hash: hash[:], Txs: [][]byte{tx}}); err != nil {
		t.Fatal(err)
	}
	// Exercise the real Rust pending-slot check, not only the Go adapter cache.
	if _, err = a.client.Commit(ctx, poolbridge.Hash{}); !errors.Is(err, poolbridge.ErrRejected) {
		t.Fatal("Rust accepted a forged commit tag", err)
	}
	if info(t, a).LastBlockHeight != 0 {
		t.Fatal("forged commit advanced state")
	}
	if _, err = a.Commit(ctx, &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if info(t, a).LastBlockHeight != 1 {
		t.Fatal("valid block did not commit after rejection")
	}
}
