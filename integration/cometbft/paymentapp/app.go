package paymentapp

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	abci "github.com/cometbft/cometbft/abci/types"
	"math"
	"sync"
)

const ChainID = "zevune-payment-lab-1"
const AppVersion uint64 = 3
const MaxTxBytes = 32768
const MaxBlockTxs = 8

type Application struct {
	abci.BaseApplication
	mu      sync.Mutex
	bridge  *Bridge
	genesis string
	pending *Block
}

func Open(executable, genesisPath, home, genesisID string) (*Application, error) {
	b, err := OpenBridge(executable, genesisPath, home)
	if err != nil {
		return nil, err
	}
	a := &Application{bridge: b, genesis: genesisID}
	s, err := a.summary(context.Background())
	if err != nil || s.GenesisID != genesisID || s.ChainID != ChainID || s.RealFundsAllowed {
		_ = b.Close()
		return nil, errors.New("payment genesis handshake failed")
	}
	return a, nil
}
func (a *Application) Close() error { return a.bridge.Close() }
func (a *Application) summary(ctx context.Context) (Summary, error) {
	var s Summary
	err := a.bridge.Call(ctx, map[string]any{"op": "info"}, &s)
	return s, err
}
func (a *Application) Info(ctx context.Context, _ *abci.RequestInfo) (*abci.ResponseInfo, error) {
	s, err := a.summary(ctx)
	if err != nil {
		return nil, err
	}
	if s.Height > math.MaxInt64 {
		return nil, errors.New("height overflow")
	}
	h, err := hex.DecodeString(s.AppHash)
	if err != nil || len(h) != 32 {
		return nil, errors.New("invalid app hash")
	}
	return &abci.ResponseInfo{Data: "Zevune local test-asset payment laboratory", Version: "0.3.0-dev", AppVersion: AppVersion, LastBlockHeight: int64(s.Height), LastBlockAppHash: h}, nil
}
func (a *Application) InitChain(ctx context.Context, r *abci.RequestInitChain) (*abci.ResponseInitChain, error) {
	var genesis struct {
		ID string `json:"shielded_genesis_id"`
	}
	if r.ChainId != ChainID || r.InitialHeight != 1 || len(r.Validators) != 4 || json.Unmarshal(r.AppStateBytes, &genesis) != nil || genesis.ID != a.genesis {
		return nil, errors.New("unsupported payment genesis")
	}
	s, err := a.summary(ctx)
	if err != nil {
		return nil, err
	}
	if s.Height != 0 {
		return nil, errors.New("cannot reinitialize committed chain")
	}
	h, err := hex.DecodeString(s.AppHash)
	if err != nil {
		return nil, err
	}
	return &abci.ResponseInitChain{AppHash: h}, nil
}
func (a *Application) CheckTx(ctx context.Context, r *abci.RequestCheckTx) (*abci.ResponseCheckTx, error) {
	if len(r.Tx) > MaxTxBytes {
		return &abci.ResponseCheckTx{Code: 1, Log: "transaction rejected"}, nil
	}
	var response any
	err := a.bridge.Call(ctx, map[string]any{"op": "check", "tx": hex.EncodeToString(r.Tx)}, &response)
	if errors.Is(err, ErrRejected) {
		return &abci.ResponseCheckTx{Code: 1, Log: "transaction rejected"}, nil
	}
	if err != nil {
		return nil, err
	}
	return &abci.ResponseCheckTx{Code: 0}, nil
}
func block(height int64, hash []byte, txs [][]byte) (Block, error) {
	if height <= 0 || len(hash) != 32 || len(txs) > MaxBlockTxs {
		return Block{}, ErrRejected
	}
	out := Block{Height: uint64(height), Hash: hex.EncodeToString(hash), Txs: make([]string, 0, len(txs))}
	for _, tx := range txs {
		if len(tx) > MaxTxBytes {
			return Block{}, ErrRejected
		}
		out.Txs = append(out.Txs, hex.EncodeToString(tx))
	}
	return out, nil
}
func (a *Application) Preview(ctx context.Context, b Block) (Summary, error) {
	var s Summary
	err := a.bridge.Call(ctx, map[string]any{"op": "preview", "block": b}, &s)
	return s, err
}
func (a *Application) PrepareProposal(ctx context.Context, r *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error) {
	selected := make([][]byte, 0, MaxBlockTxs)
	var bytes int64
	for _, tx := range r.Txs {
		if len(selected) == MaxBlockTxs {
			break
		}
		if len(tx) > MaxTxBytes || bytes+int64(len(tx)) > r.MaxTxBytes {
			continue
		}
		trial := append(append([][]byte{}, selected...), tx)
		b, err := block(r.Height, make([]byte, 32), trial)
		if err != nil {
			return nil, err
		}
		if _, err = a.Preview(ctx, b); errors.Is(err, ErrRejected) {
			continue
		} else if err != nil {
			return nil, err
		}
		selected = trial
		bytes += int64(len(tx))
	}
	return &abci.ResponsePrepareProposal{Txs: selected}, nil
}
func (a *Application) ProcessProposal(ctx context.Context, r *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error) {
	b, err := block(r.Height, r.Hash, r.Txs)
	if err == nil {
		_, err = a.Preview(ctx, b)
	}
	if errors.Is(err, ErrRejected) {
		return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
	}
	if err != nil {
		return nil, err
	}
	return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_ACCEPT}, nil
}
func (a *Application) FinalizeBlock(ctx context.Context, r *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	b, err := block(r.Height, r.Hash, r.Txs)
	if err != nil {
		return nil, err
	}
	var s Summary
	if err = a.bridge.Call(ctx, map[string]any{"op": "stage", "block": b}, &s); err != nil {
		return nil, err
	}
	a.pending = &b
	hash, err := hex.DecodeString(s.AppHash)
	if err != nil {
		return nil, err
	}
	results := make([]*abci.ExecTxResult, len(r.Txs))
	for i := range results {
		results[i] = &abci.ExecTxResult{Code: 0}
	}
	return &abci.ResponseFinalizeBlock{AppHash: hash, TxResults: results}, nil
}
func (a *Application) Commit(ctx context.Context, _ *abci.RequestCommit) (*abci.ResponseCommit, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.pending == nil {
		return nil, errors.New("no staged payment block")
	}
	var s Summary
	err := a.bridge.Call(ctx, map[string]any{"op": "commit", "height": a.pending.Height, "hash": a.pending.Hash}, &s)
	if err != nil {
		return nil, err
	}
	a.pending = nil
	return &abci.ResponseCommit{}, nil
}
func (a *Application) Query(ctx context.Context, r *abci.RequestQuery) (*abci.ResponseQuery, error) {
	s, err := a.summary(ctx)
	if err != nil {
		return nil, err
	}
	if r.Prove || r.Height < 0 || (r.Height != 0 && uint64(r.Height) != s.Height) {
		return &abci.ResponseQuery{Code: 1, Log: "only current public queries without proof flag"}, nil
	}
	var value []byte
	switch r.Path {
	case "/payment/status":
		value, err = json.Marshal(s)
	case "/payment/export":
		var e Export
		err = a.bridge.Call(ctx, map[string]any{"op": "export"}, &e)
		if err == nil {
			value, err = json.Marshal(e)
			s = e.Summary
		}
	default:
		return &abci.ResponseQuery{Code: 1, Log: "unknown public query"}, nil
	}
	if err != nil {
		return nil, err
	}
	return &abci.ResponseQuery{Code: 0, Height: int64(s.Height), Value: value}, nil
}
func (a *Application) ListSnapshots(context.Context, *abci.RequestListSnapshots) (*abci.ResponseListSnapshots, error) {
	return &abci.ResponseListSnapshots{}, nil
}
func (a *Application) OfferSnapshot(context.Context, *abci.RequestOfferSnapshot) (*abci.ResponseOfferSnapshot, error) {
	return &abci.ResponseOfferSnapshot{Result: abci.ResponseOfferSnapshot_REJECT}, nil
}
func (a *Application) LoadSnapshotChunk(context.Context, *abci.RequestLoadSnapshotChunk) (*abci.ResponseLoadSnapshotChunk, error) {
	return &abci.ResponseLoadSnapshotChunk{}, nil
}
func (a *Application) ApplySnapshotChunk(context.Context, *abci.RequestApplySnapshotChunk) (*abci.ResponseApplySnapshotChunk, error) {
	return &abci.ResponseApplySnapshotChunk{Result: abci.ResponseApplySnapshotChunk_ABORT}, nil
}
func (a *Application) VerifyVoteExtension(_ context.Context, r *abci.RequestVerifyVoteExtension) (*abci.ResponseVerifyVoteExtension, error) {
	status := abci.ResponseVerifyVoteExtension_ACCEPT
	if len(r.VoteExtension) != 0 {
		status = abci.ResponseVerifyVoteExtension_REJECT
	}
	return &abci.ResponseVerifyVoteExtension{Status: status}, nil
}
