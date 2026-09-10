package app

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"testing"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/cometbft/cometbft/types"
)

const testChain = "zevune-consensus-lab-1"

var ctx = context.Background()

func open(t *testing.T, dir string) *Application {
	t.Helper()
	a, err := Open(testChain, dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = a.Close() })
	return a
}
func request(height int64) *abci.RequestFinalizeBlock {
	return &abci.RequestFinalizeBlock{Height: height, Hash: bytes.Repeat([]byte{byte(height)}, 32)}
}
func info(t *testing.T, a *Application) *abci.ResponseInfo {
	t.Helper()
	r, err := a.Info(ctx, &abci.RequestInfo{})
	if err != nil {
		t.Fatal(err)
	}
	return r
}
func genesis() *abci.RequestInitChain {
	vs := make([]abci.ValidatorUpdate, 4)
	for i := range vs {
		vs[i] = abci.Ed25519ValidatorUpdate(bytes.Repeat([]byte{byte(i + 1)}, 32), 10)
	}
	p := types.DefaultConsensusParams().ToProto()
	return &abci.RequestInitChain{ChainId: testChain, InitialHeight: 1, ConsensusParams: &p, Validators: vs}
}
func TestGenesisValidation(t *testing.T) {
	a := open(t, t.TempDir())
	r, err := a.InitChain(ctx, genesis())
	if err != nil || len(r.AppHash) != 32 {
		t.Fatal(r, err)
	}
	for _, mutate := range []func(*abci.RequestInitChain){
		func(r *abci.RequestInitChain) { r.ChainId = "another" },
		func(r *abci.RequestInitChain) { r.InitialHeight = 2 },
		func(r *abci.RequestInitChain) { r.AppStateBytes = []byte("{}") },
		func(r *abci.RequestInitChain) { r.Validators = r.Validators[:3] },
		func(r *abci.RequestInitChain) { r.Validators[1] = r.Validators[0] },
		func(r *abci.RequestInitChain) { r.Validators[0].Power = 1 },
		func(r *abci.RequestInitChain) { r.ConsensusParams = nil },
	} {
		r := genesis()
		mutate(r)
		if _, err := a.InitChain(ctx, r); err == nil {
			t.Fatal("bad genesis accepted")
		}
	}
}
func TestFinalizeIsNotDurableAndCommitIs(t *testing.T) {
	dir := t.TempDir()
	a := open(t, dir)
	before := info(t, a)
	stat, _ := os.Stat(filepath.Join(dir, "ledger.journal"))
	p, err := a.FinalizeBlock(ctx, request(1))
	if err != nil {
		t.Fatal(err)
	}
	again := info(t, a)
	afterStat, _ := os.Stat(filepath.Join(dir, "ledger.journal"))
	if again.LastBlockHeight != 0 || !bytes.Equal(again.LastBlockAppHash, before.LastBlockAppHash) || stat.Size() != afterStat.Size() {
		t.Fatal("FinalizeBlock persisted state")
	}
	_ = a.Close()
	a = open(t, dir)
	if info(t, a).LastBlockHeight != 0 {
		t.Fatal("uncommitted preview recovered")
	}
	p2, err := a.FinalizeBlock(ctx, request(1))
	if err != nil || !bytes.Equal(p.AppHash, p2.AppHash) {
		t.Fatal(err)
	}
	if _, err = a.Commit(ctx, &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	_ = a.Close()
	a = open(t, dir)
	got := info(t, a)
	if got.LastBlockHeight != 1 || !bytes.Equal(got.LastBlockAppHash, p.AppHash) {
		t.Fatal("commit lost on restart")
	}
}
func TestProposalChecksNeverWrite(t *testing.T) {
	a := open(t, t.TempDir())
	before := info(t, a)
	p, err := a.PrepareProposal(ctx, &abci.RequestPrepareProposal{Height: 1, Txs: [][]byte{[]byte("not a proof")}, MaxTxBytes: 1024})
	if err != nil || len(p.Txs) != 0 {
		t.Fatal(p, err)
	}
	for _, r := range []*abci.RequestProcessProposal{nil, {Height: 0}, {Height: 2}, {Height: 1, Txs: [][]byte{[]byte("x")}}} {
		p, err := a.ProcessProposal(ctx, r)
		if err != nil || p.Status != abci.ResponseProcessProposal_REJECT {
			t.Fatal(p, err)
		}
	}
	p2, err := a.ProcessProposal(ctx, &abci.RequestProcessProposal{Height: 1})
	if err != nil || p2.Status != abci.ResponseProcessProposal_ACCEPT {
		t.Fatal(p2, err)
	}
	after := info(t, a)
	if after.LastBlockHeight != before.LastBlockHeight || !bytes.Equal(after.LastBlockAppHash, before.LastBlockAppHash) {
		t.Fatal("proposal wrote state")
	}
}
func TestEveryTransactionEntryRemainsClosed(t *testing.T) {
	a := open(t, t.TempDir())
	for _, raw := range [][]byte{nil, {}, []byte("valid looking transaction"), make([]byte, 65536)} {
		r, err := a.CheckTx(ctx, &abci.RequestCheckTx{Tx: raw})
		if err != nil || r.Code == 0 {
			t.Fatal("CheckTx accepted", err)
		}
		f := request(1)
		f.Txs = [][]byte{raw}
		if _, err := a.FinalizeBlock(ctx, f); err == nil {
			t.Fatal("FinalizeBlock accepted transaction")
		}
	}
	if _, err := a.Commit(ctx, &abci.RequestCommit{}); err == nil {
		t.Fatal("Commit without preview")
	}
}
func TestRepeatedFinalizeCopiesAndBindsHash(t *testing.T) {
	a := open(t, t.TempDir())
	r := request(1)
	result, err := a.FinalizeBlock(ctx, r)
	if err != nil {
		t.Fatal(err)
	}
	original := append([]byte(nil), result.AppHash...)
	result.AppHash[0] ^= 255
	r.Hash[0] ^= 255
	if _, err := a.FinalizeBlock(ctx, r); err == nil {
		t.Fatal("changed block accepted")
	}
	again, err := a.FinalizeBlock(ctx, request(1))
	if err != nil || !bytes.Equal(again.AppHash, original) {
		t.Fatal(err)
	}
	if _, err := a.Commit(ctx, &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if _, err := a.Commit(ctx, &abci.RequestCommit{}); err == nil {
		t.Fatal("duplicate Commit accepted")
	}
	if _, err := a.FinalizeBlock(ctx, request(1)); err == nil {
		t.Fatal("old height accepted")
	}
}
func TestQueryOnlyCommittedStateAndNoProofClaims(t *testing.T) {
	a := open(t, t.TempDir())
	_, _ = a.FinalizeBlock(ctx, request(1))
	r, err := a.Query(ctx, &abci.RequestQuery{Path: "/status"})
	if err != nil || r.Code != 0 || r.Height != 0 || r.ProofOps != nil {
		t.Fatal(r, err)
	}
	var status map[string]any
	if err = json.Unmarshal(r.Value, &status); err != nil {
		t.Fatal(err)
	}
	if status["payments_enabled"] != false || status["network_privacy_implemented"] != false {
		t.Fatal(status)
	}
	for _, q := range []*abci.RequestQuery{nil, {Path: "/status", Prove: true}, {Path: "/status", Height: 2}, {Path: "/private"}} {
		r, err := a.Query(ctx, q)
		if err != nil || r.Code == 0 {
			t.Fatal(r, err)
		}
	}
}
func TestSnapshotsAndExtensionsFailClosed(t *testing.T) {
	a := open(t, t.TempDir())
	r, _ := a.OfferSnapshot(ctx, &abci.RequestOfferSnapshot{})
	if r.Result != abci.ResponseOfferSnapshot_REJECT {
		t.Fatal(r)
	}
	c, _ := a.ApplySnapshotChunk(ctx, &abci.RequestApplySnapshotChunk{})
	if c.Result != abci.ResponseApplySnapshotChunk_ABORT {
		t.Fatal(c)
	}
	v, _ := a.VerifyVoteExtension(ctx, &abci.RequestVerifyVoteExtension{VoteExtension: []byte("unsupported")})
	if v.Status != abci.ResponseVerifyVoteExtension_REJECT {
		t.Fatal(v)
	}
}
func TestConcurrentInfoAndFinalize(t *testing.T) {
	a := open(t, t.TempDir())
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 20; j++ {
				if _, err := a.Info(ctx, &abci.RequestInfo{}); err != nil {
					t.Error(err)
				}
			}
		}()
	}
	for h := int64(1); h <= 5; h++ {
		if _, err := a.FinalizeBlock(ctx, request(h)); err != nil {
			t.Fatal(err)
		}
		if _, err := a.Commit(ctx, &abci.RequestCommit{}); err != nil {
			t.Fatal(err)
		}
	}
	wg.Wait()
}
func TestClosedApplicationFails(t *testing.T) {
	a := open(t, t.TempDir())
	_ = a.Close()
	if _, err := a.Info(ctx, &abci.RequestInfo{}); err == nil {
		t.Fatal("closed Info")
	}
	if _, err := a.FinalizeBlock(ctx, request(1)); err == nil {
		t.Fatal("closed Finalize")
	}
}
