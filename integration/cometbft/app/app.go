// Package app adapts the NO-FUNDS ledger to CometBFT ABCI 2.0.
// Only empty blocks are supported. This is not a private payment protocol.
package app

import (
 "bytes"
 "context"
 "encoding/json"
 "errors"
 "fmt"
 "math"
 "sync"

 abci "github.com/cometbft/cometbft/abci/types"
 "github.com/youq616/Zevune/internal/ledger"
)

const Version = "0.2.0-consensus-dev"
const AppVersion uint64 = 1
const DisabledCode uint32 = 1

var ErrPaymentsDisabled = errors.New("payments are disabled: real proof and wallet integration is incomplete")

// Application has no injected verifier, signing key, payment admin or external
// ABCI listener. Consensus uses local ABCI connections in the node process.
type Application struct {
 abci.BaseApplication
 mu sync.Mutex
 engine *ledger.Engine
 chain string
 pending *candidate
}
type candidate struct { hash []byte; preview ledger.BlockPreview }
var _ abci.Application = (*Application)(nil)

func Open(chain, dir string) (*Application, error) {
 e, err := ledger.OpenPersistent(chain, dir, nil, ledger.UnavailableVerifier{})
 if err != nil { return nil, err }
 return &Application{engine: e, chain: chain}, nil
}
func (a *Application) Close() error {
 a.mu.Lock(); defer a.mu.Unlock()
 return a.engine.Close()
}
func (a *Application) ready() error {
 if !a.engine.StorageStatus().Available { return ledger.ErrStorageUnavailable }
 return nil
}
func (a *Application) Info(_ context.Context, _ *abci.RequestInfo) (*abci.ResponseInfo, error) {
 a.mu.Lock(); defer a.mu.Unlock()
 if err := a.ready(); err != nil { return nil, err }
 s := a.engine.Summary()
 if s.Height > math.MaxInt64 { return nil, ledger.ErrHeight }
 return &abci.ResponseInfo{Data: "Zevune NO-FUNDS consensus laboratory", Version: Version,
 AppVersion: AppVersion, LastBlockHeight: int64(s.Height), LastBlockAppHash: append([]byte(nil), s.AppHash[:]...)}, nil
}
func (a *Application) InitChain(_ context.Context, r *abci.RequestInitChain) (*abci.ResponseInitChain, error) {
 a.mu.Lock(); defer a.mu.Unlock()
 if err := a.ready(); err != nil { return nil, err }
 if r == nil || r.ChainId != a.chain || r.InitialHeight != 1 || len(r.AppStateBytes) != 0 {
 return nil, errors.New("unsupported genesis: exact chain, initial height 1 and empty app state required")
 }
 if a.engine.Summary().Height != 0 || a.pending != nil { return nil, ledger.ErrHeight }
 if len(r.Validators) != 4 { return nil, errors.New("laboratory requires four genesis validators") }
 seen := make(map[string]bool)
 for _, v := range r.Validators {
 key := v.PubKey.GetEd25519()
 if v.Power != 10 || len(key) != 32 || seen[string(key)] { return nil, errors.New("invalid laboratory validator set") }
 seen[string(key)] = true
 }
 if r.ConsensusParams == nil || (r.ConsensusParams.Abci != nil && r.ConsensusParams.Abci.VoteExtensionsEnableHeight != 0) {
 return nil, errors.New("vote extensions must remain disabled")
 }
 s := a.engine.Summary()
 return &abci.ResponseInitChain{AppHash: append([]byte(nil), s.AppHash[:]...)}, nil
}
func (a *Application) CheckTx(context.Context, *abci.RequestCheckTx) (*abci.ResponseCheckTx, error) {
 return &abci.ResponseCheckTx{Code: DisabledCode, Codespace: "zevune", Log: ErrPaymentsDisabled.Error()}, nil
}
func (a *Application) PrepareProposal(_ context.Context, r *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error) {
 a.mu.Lock(); defer a.mu.Unlock()
 if err := a.ready(); err != nil { return nil, err }
 if r == nil || r.Height <= 0 { return nil, ledger.ErrHeight }
 if _, err := a.engine.PreviewBlock(uint64(r.Height), nil); err != nil { return nil, err }
 // Drop every mempool input, rather than accidentally inheriting BaseApplication.
 return &abci.ResponsePrepareProposal{Txs: [][]byte{}}, nil
}
func (a *Application) ProcessProposal(_ context.Context, r *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error) {
 a.mu.Lock(); defer a.mu.Unlock()
 out := &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}
 if r == nil || r.Height <= 0 || len(r.Txs) != 0 { return out, nil }
 if _, err := a.engine.PreviewBlock(uint64(r.Height), nil); err != nil { return out, nil }
 out.Status = abci.ResponseProcessProposal_ACCEPT
 return out, nil
}
// FinalizeBlock calculates the result but MUST NOT persist it. Commit is the
// only persistence boundary. Info/Query always expose the last committed state.
func (a *Application) FinalizeBlock(_ context.Context, r *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error) {
 a.mu.Lock(); defer a.mu.Unlock()
 if err := a.ready(); err != nil { return nil, err }
 if r == nil || r.Height <= 0 || len(r.Hash) != 32 { return nil, errors.New("invalid finalization height/hash") }
 if len(r.Txs) != 0 { return nil, ErrPaymentsDisabled }
 if a.pending != nil {
 if a.pending.preview.Height != uint64(r.Height) || !bytes.Equal(a.pending.hash, r.Hash) {
 return nil, errors.New("different block already awaiting Commit")
 }
 return finalizeResult(a.pending.preview), nil
 }
 p, err := a.engine.PreviewBlock(uint64(r.Height), nil)
 if err != nil { return nil, err }
 a.pending = &candidate{hash: append([]byte(nil), r.Hash...), preview: p}
 return finalizeResult(p), nil
}
func finalizeResult(p ledger.BlockPreview) *abci.ResponseFinalizeBlock {
 return &abci.ResponseFinalizeBlock{AppHash: append([]byte(nil), p.Result.AppHash[:]...), TxResults: []*abci.ExecTxResult{}}
}
func (a *Application) Commit(context.Context, *abci.RequestCommit) (*abci.ResponseCommit, error) {
 a.mu.Lock(); defer a.mu.Unlock()
 if a.pending == nil { return nil, errors.New("Commit without FinalizeBlock") }
 if _, err := a.engine.CommitPreview(a.pending.preview, nil); err != nil {
 return nil, fmt.Errorf("durable application commit failed: %w", err)
 }
 a.pending = nil
 return &abci.ResponseCommit{RetainHeight: 0}, nil
}
func (a *Application) Query(_ context.Context, r *abci.RequestQuery) (*abci.ResponseQuery, error) {
 a.mu.Lock(); defer a.mu.Unlock()
 if err := a.ready(); err != nil { return nil, err }
 s := a.engine.Summary()
 if r == nil || r.Path != "/status" || r.Prove || len(r.Data) != 0 || (r.Height != 0 && r.Height != int64(s.Height)) {
 return &abci.ResponseQuery{Code: DisabledCode, Log: "only current /status without proof is supported"}, nil
 }
 b, err := json.Marshal(struct {
 Version string `json:"software_version"`
 Mode string `json:"mode"`
 Payments bool `json:"payments_enabled"`
 Privacy bool `json:"network_privacy_implemented"`
 Ledger ledger.Summary `json:"ledger"`
 Storage ledger.StorageStatus `json:"storage"`
 }{Version, "local_empty_block_consensus", false, false, s, a.engine.StorageStatus()})
 return &abci.ResponseQuery{Code: 0, Height: int64(s.Height), Value: b}, err
}
func (a *Application) VerifyVoteExtension(_ context.Context, r *abci.RequestVerifyVoteExtension) (*abci.ResponseVerifyVoteExtension, error) {
 status := abci.ResponseVerifyVoteExtension_REJECT
 if r != nil && len(r.VoteExtension) == 0 { status = abci.ResponseVerifyVoteExtension_ACCEPT }
 return &abci.ResponseVerifyVoteExtension{Status: status}, nil
}
func (a *Application) OfferSnapshot(context.Context, *abci.RequestOfferSnapshot) (*abci.ResponseOfferSnapshot, error) {
 return &abci.ResponseOfferSnapshot{Result: abci.ResponseOfferSnapshot_REJECT}, nil
}
func (a *Application) ApplySnapshotChunk(context.Context, *abci.RequestApplySnapshotChunk) (*abci.ResponseApplySnapshotChunk, error) {
 return &abci.ResponseApplySnapshotChunk{Result: abci.ResponseApplySnapshotChunk_ABORT}, nil
}
