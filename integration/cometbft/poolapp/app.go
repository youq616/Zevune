// Package poolapp connects actual Orchard state to ABCI. It is an isolated
// empty-genesis, NO-FUNDS laboratory, not a deployable payment network.
package poolapp

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/youq616/Zevune/internal/poolbridge"
	"sync"
)

const ChainID = poolbridge.Network
const Version = "0.3.1-funded-consensus-lab"
const AppVersion uint64 = 2

type Application struct {
	abci.BaseApplication
	mu      sync.Mutex
	client  *poolbridge.Client
	genesis poolbridge.Hash
	pending *candidate
	failed  bool
}
type candidate struct {
	tag    poolbridge.Hash
	result poolbridge.Summary
	count  int
}

var _ abci.Application = (*Application)(nil)

func Open(ctx context.Context, o poolbridge.Options) (*Application, error) {
	c, e := poolbridge.Start(ctx, o)
	if e != nil {
		return nil, e
	}
	return &Application{client: c, genesis: o.TestGenesisSHA256}, nil
}
func (a *Application) Close() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.failed = true
	return a.client.Close()
}
func (a *Application) ready() error {
	if a.failed {
		return poolbridge.ErrUnavailable
	}
	return nil
}
func (a *Application) failure(e error) error {
	if e != nil && !errors.Is(e, poolbridge.ErrRejected) && !errors.Is(e, poolbridge.ErrBounds) {
		a.failed = true
		_ = a.client.Close()
	}
	return e
}
func invalid(e error) bool {
	return errors.Is(e, poolbridge.ErrRejected) || errors.Is(e, poolbridge.ErrBounds)
}
func (a *Application) Info(ctx context.Context, _ *abci.RequestInfo) (*abci.ResponseInfo, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if e := a.ready(); e != nil {
		return nil, e
	}
	s, e := a.client.Status(ctx)
	if e != nil {
		return nil, a.failure(e)
	}
	return &abci.ResponseInfo{Data: "Zevune NO-FUNDS Orchard consensus lab", Version: Version, AppVersion: AppVersion, LastBlockHeight: int64(s.Height), LastBlockAppHash: append([]byte(nil), s.AppHash[:]...)}, nil
}
func (a *Application) InitChain(ctx context.Context, r *abci.RequestInitChain) (*abci.ResponseInitChain, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if e := a.ready(); e != nil {
		return nil, e
	}
	if r == nil || r.ChainId != ChainID || r.InitialHeight != 1 || !validGenesisState(r.AppStateBytes, a.genesis) || len(r.Validators) != 4 || r.ConsensusParams == nil {
		return nil, poolbridge.ErrRejected
	}
	if r.ConsensusParams.Abci != nil && r.ConsensusParams.Abci.VoteExtensionsEnableHeight != 0 {
		return nil, poolbridge.ErrRejected
	}
	seen := map[string]bool{}
	for _, v := range r.Validators {
		key := v.PubKey.GetEd25519()
		if v.Power != 10 || len(key) != 32 || seen[string(key)] {
			return nil, poolbridge.ErrRejected
		}
		seen[string(key)] = true
	}
	s, e := a.client.Status(ctx)
	if e != nil {
		return nil, a.failure(e)
	}
	if s.Height != 0 || a.pending != nil {
		return nil, poolbridge.ErrRejected
	}
	return &abci.ResponseInitChain{AppHash: append([]byte(nil), s.AppHash[:]...)}, nil
}
func (a *Application) CheckTx(ctx context.Context, r *abci.RequestCheckTx) (*abci.ResponseCheckTx, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if e := a.ready(); e != nil {
		return nil, e
	}
	if r == nil {
		return &abci.ResponseCheckTx{Code: 1}, nil
	}
	e := a.client.Check(ctx, r.Tx)
	if invalid(e) {
		return &abci.ResponseCheckTx{Code: 1, Codespace: "zevune", Log: "protocol transaction rejected"}, nil
	}
	if e != nil {
		return nil, a.failure(e)
	}
	return &abci.ResponseCheckTx{Code: 0, GasWanted: 1}, nil
}
func (a *Application) PrepareProposal(ctx context.Context, r *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if e := a.ready(); e != nil {
		return nil, e
	}
	if r == nil || r.Height <= 0 || r.MaxTxBytes < 0 {
		return nil, poolbridge.ErrBounds
	}
	chosen := [][]byte{}
	size := int64(0)
	// The real block hash does not exist yet. This marker is used ONLY for
	// read-only validity checks, never for FinalizeBlock or Commit.
	marker := sha256.Sum256([]byte("ZEVUNE-PROPOSAL-PREFLIGHT"))
	if _, e := a.client.Preview(ctx, uint64(r.Height), marker, nil); e != nil {
		return nil, a.failure(e)
	}
	for i, tx := range r.Txs {
		if i >= 64 || len(chosen) >= poolbridge.MaxTransactions {
			break
		}
		if len(tx) == 0 || len(tx) > poolbridge.MaxTransactionBytes || int64(len(tx)) > r.MaxTxBytes-size {
			continue
		}
		trial := append(append([][]byte(nil), chosen...), tx)
		if _, e := a.client.Preview(ctx, uint64(r.Height), marker, trial); invalid(e) {
			continue
		} else if e != nil {
			return nil, a.failure(e)
		}
		chosen = trial
		size += int64(len(tx))
	}
	return &abci.ResponsePrepareProposal{Txs: chosen}, nil
}
func (a *Application) ProcessProposal(ctx context.Context, r *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if e := a.ready(); e != nil {
		return nil, e
	}
	out := &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}
	if r == nil || r.Height <= 0 || len(r.Hash) != 32 {
		return out, nil
	}
	var hash poolbridge.Hash
	copy(hash[:], r.Hash)
	_, e := a.client.Preview(ctx, uint64(r.Height), hash, r.Txs)
	if invalid(e) {
		return out, nil
	}
	if e != nil {
		return nil, a.failure(e)
	}
	out.Status = abci.ResponseProcessProposal_ACCEPT
	return out, nil
}
func finalResult(p *candidate) *abci.ResponseFinalizeBlock {
	results := make([]*abci.ExecTxResult, p.count)
	for i := range results {
		results[i] = &abci.ExecTxResult{Code: 0, GasWanted: 1, GasUsed: 1}
	}
	return &abci.ResponseFinalizeBlock{AppHash: append([]byte(nil), p.result.AppHash[:]...), TxResults: results}
}
func (a *Application) FinalizeBlock(ctx context.Context, r *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if e := a.ready(); e != nil {
		return nil, e
	}
	if r == nil || r.Height <= 0 || len(r.Hash) != 32 {
		return nil, poolbridge.ErrBounds
	}
	var hash poolbridge.Hash
	copy(hash[:], r.Hash)
	raw, e := poolbridge.BlockBytes(uint64(r.Height), hash, r.Txs)
	if e != nil {
		return nil, e
	}
	tag := sha256.Sum256(raw)
	if a.pending != nil {
		if a.pending.tag != tag {
			return nil, poolbridge.ErrRejected
		}
		return finalResult(a.pending), nil
	}
	s, returned, e := a.client.Finalize(ctx, uint64(r.Height), hash, r.Txs)
	if e != nil {
		return nil, a.failure(e)
	}
	if returned != tag || s.Height != uint64(r.Height) {
		return nil, a.failure(poolbridge.ErrProtocol)
	}
	a.pending = &candidate{tag: tag, result: s, count: len(r.Txs)}
	return finalResult(a.pending), nil
}
func (a *Application) Commit(ctx context.Context, _ *abci.RequestCommit) (*abci.ResponseCommit, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if e := a.ready(); e != nil {
		return nil, e
	}
	if a.pending == nil {
		return nil, poolbridge.ErrRejected
	}
	s, e := a.client.Commit(ctx, a.pending.tag)
	if e != nil {
		a.failed = true
		_ = a.client.Close()
		return nil, e
	}
	if s != a.pending.result {
		return nil, a.failure(poolbridge.ErrProtocol)
	}
	a.pending = nil
	return &abci.ResponseCommit{RetainHeight: 0}, nil
}
func (a *Application) Query(ctx context.Context, r *abci.RequestQuery) (*abci.ResponseQuery, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if e := a.ready(); e != nil {
		return nil, e
	}
	if r == nil || r.Path != "/status" || r.Prove || len(r.Data) != 0 {
		return &abci.ResponseQuery{Code: 1}, nil
	}
	s, e := a.client.Status(ctx)
	if e != nil {
		return nil, a.failure(e)
	}
	if r.Height != 0 && r.Height != int64(s.Height) {
		return &abci.ResponseQuery{Code: 1}, nil
	}
	mode := "local_zero_value_orchard_consensus"
	if a.genesis != (poolbridge.Hash{}) {
		mode = "local_fixed_supply_funded_orchard_lab"
	}
	b, e := json.Marshal(struct {
		Version  string             `json:"software_version"`
		Mode     string             `json:"mode"`
		Payments bool               `json:"payments_enabled"`
		Privacy  bool               `json:"network_privacy_implemented"`
		Ledger   poolbridge.Summary `json:"ledger"`
	}{Version, mode, false, false, s})
	return &abci.ResponseQuery{Code: 0, Height: int64(s.Height), Value: b}, e
}
func (a *Application) VerifyVoteExtension(_ context.Context, r *abci.RequestVerifyVoteExtension) (*abci.ResponseVerifyVoteExtension, error) {
	s := abci.ResponseVerifyVoteExtension_REJECT
	if r != nil && len(r.VoteExtension) == 0 {
		s = abci.ResponseVerifyVoteExtension_ACCEPT
	}
	return &abci.ResponseVerifyVoteExtension{Status: s}, nil
}
func (a *Application) OfferSnapshot(context.Context, *abci.RequestOfferSnapshot) (*abci.ResponseOfferSnapshot, error) {
	return &abci.ResponseOfferSnapshot{Result: abci.ResponseOfferSnapshot_REJECT}, nil
}
func (a *Application) ApplySnapshotChunk(context.Context, *abci.RequestApplySnapshotChunk) (*abci.ResponseApplySnapshotChunk, error) {
	return &abci.ResponseApplySnapshotChunk{Result: abci.ResponseApplySnapshotChunk_ABORT}, nil
}
