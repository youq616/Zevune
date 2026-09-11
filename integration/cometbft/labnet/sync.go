package labnet

import (
	"bytes"
	"context"
	"crypto/sha256"
	"time"

	"github.com/cometbft/cometbft/types"
	"github.com/youq616/Zevune/integration/cometbft/poolapp"
	"github.com/youq616/Zevune/internal/poolbridge"
)

// A fixed validator set is an explicit laboratory constraint. This verifier is
// not a dynamic-set light client, an eclipse defense, or a long-range defense
// after quorum key compromise. Genesis/config pins must come independently.
func (n *Network) validateHeader(s *types.SignedHeader, height int64, now time.Time) error {
	if s == nil || s.Header == nil || s.Commit == nil || height < 1 || height > maxHeight || s.Height != height || s.ValidateBasic(poolapp.ChainID) != nil {
		return ErrCertificate
	}
	if len(s.Header.AppHash) != 32 || s.Header.Version.App != poolapp.AppVersion || !bytes.Equal(s.Header.Hash(), s.Commit.BlockID.Hash) || !bytes.Equal(s.Header.ValidatorsHash, n.validators.Hash()) || !bytes.Equal(s.Header.NextValidatorsHash, n.validators.Hash()) || !bytes.Equal(s.Header.ConsensusHash, n.genesis.ConsensusParams.Hash()) {
		return ErrCertificate
	}
	if s.Header.Time.Before(n.genesis.GenesisTime) || s.Header.Time.After(now.Add(10*time.Second)) {
		return ErrCertificate
	}
	if n.validators.VerifyCommit(poolapp.ChainID, s.Commit.BlockID, height, s.Commit) != nil {
		return ErrCertificate
	}
	return nil
}
func (n *Network) header(ctx context.Context, remote rpcSource, height int64) (*types.SignedHeader, error) {
	result, err := remote.Commit(ctx, &height)
	if err != nil || result == nil {
		return nil, ErrResponse
	}
	s := &result.SignedHeader
	if err = n.validateHeader(s, height, time.Now()); err != nil {
		return nil, err
	}
	return s, nil
}

type SyncOptions struct {
	Endpoint     string
	Worker       string
	WorkerSHA256 Hash
	Journal      string
	Create       bool   // explicit new reference journal only; reopen never creates.
	Limit        uint64 // at most 128 complete, independently verified blocks per call.
}

type SyncResult struct {
	Scope                 string `json:"scope"`
	Height                uint64 `json:"height"`
	AppHash               string `json:"app_hash"`
	Root                  string `json:"root"`
	NewBlocks             uint64 `json:"new_blocks"`
	ObservedSignedTip     uint64 `json:"observed_signed_tip"`
	CaughtUpToObservedTip bool   `json:"caught_up_to_observed_tip"`
	Payments              bool   `json:"real_funds_allowed"`
}

func resultFor(s poolbridge.Summary, initial, tip uint64) SyncResult {
	return SyncResult{Scope: "fixed_validator_local_test_network", Height: s.Height, AppHash: HashText(s.AppHash), Root: HashText(s.Root), NewBlocks: s.Height - initial, ObservedSignedTip: tip, CaughtUpToObservedTip: s.Height+1 == tip}
}

// synchronize validates the post-state against the NEXT signed header BEFORE
// each disk commit. Invalid data never contaminates the saved reference state.
// A later error can leave earlier authenticated blocks saved; no rollback occurs.
func (n *Network) synchronize(ctx context.Context, remote rpcSource, store *poolbridge.Client, limit uint64) (SyncResult, error) {
	if limit == 0 || limit > maxSyncBlocks {
		return SyncResult{}, ErrBounds
	}
	status, err := remote.Status(ctx)
	if err != nil || status == nil {
		return SyncResult{}, ErrResponse
	}
	tip := status.SyncInfo.LatestBlockHeight
	if status.NodeInfo.Network != poolapp.ChainID || tip < 2 || tip > maxHeight {
		return SyncResult{}, ErrBehind
	}
	signedTip, err := n.header(ctx, remote, tip)
	if err != nil {
		return SyncResult{}, err
	}
	// Freshness is a bounded local test policy, not proof that a peer disclosed
	// the globally newest block. A peer may withhold data; no anonymity claimed.
	if time.Since(signedTip.Header.Time) > 15*time.Minute {
		return SyncResult{}, ErrBehind
	}
	state, err := store.Status(ctx)
	if err != nil {
		return SyncResult{}, err
	}
	initial := state.Height
	if state.Height >= uint64(tip) {
		return SyncResult{}, ErrBehind
	}
	current, err := n.header(ctx, remote, int64(state.Height)+1)
	if err != nil {
		return SyncResult{}, err
	}
	if !bytes.Equal(current.Header.AppHash, state.AppHash[:]) {
		return SyncResult{}, ErrCertificate
	}
	if initial == 0 && !bytes.Equal(n.genesis.AppHash, state.AppHash[:]) {
		return SyncResult{}, ErrConfiguration
	}
	if initial == 0 {
		if !current.Header.LastBlockID.IsZero() {
			return SyncResult{}, ErrCertificate
		}
	} else {
		previous, err := n.header(ctx, remote, int64(initial))
		if err != nil {
			return SyncResult{}, err
		}
		if !current.Header.LastBlockID.Equals(previous.Commit.BlockID) || current.Header.Time.Before(previous.Header.Time) {
			return SyncResult{}, ErrCertificate
		}
	}
	if int64(initial)+1 == tip && !bytes.Equal(current.Header.Hash(), signedTip.Header.Hash()) {
		return SyncResult{}, ErrCertificate
	}
	target := uint64(tip) - 1
	if target-initial > limit {
		target = initial + limit
	}
	for height := initial + 1; height <= target; height++ {
		if ctx.Err() != nil {
			return SyncResult{}, ctx.Err()
		}
		h := int64(height)
		block, err := remote.Block(ctx, &h)
		if err != nil || block == nil || block.Block == nil {
			return SyncResult{}, ErrResponse
		}
		if block.Block.Height != h || block.Block.ValidateBasic() != nil || !block.BlockID.Equals(current.Commit.BlockID) || !bytes.Equal(block.Block.Hash(), current.Header.Hash()) || !bytes.Equal(block.Block.Data.Hash(), current.Header.DataHash) || !bytes.Equal(current.Header.AppHash, state.AppHash[:]) {
			return SyncResult{}, ErrCertificate
		}
		if block.Block.Size() > int(n.genesis.ConsensusParams.Block.MaxBytes) {
			return SyncResult{}, ErrBounds
		}
		parts, err := block.Block.MakePartSet(types.BlockPartSizeBytes)
		if err != nil || !parts.Header().Equals(current.Commit.BlockID.PartSetHeader) {
			return SyncResult{}, ErrCertificate
		}
		next, err := n.header(ctx, remote, h+1)
		if err != nil {
			return SyncResult{}, err
		}
		if !next.Header.LastBlockID.Equals(current.Commit.BlockID) || next.Header.Time.Before(current.Header.Time) {
			return SyncResult{}, ErrCertificate
		}
		// Reject a peer presenting two different quorum-signed tips during this call.
		if h+1 == tip && !bytes.Equal(next.Header.Hash(), signedTip.Header.Hash()) {
			return SyncResult{}, ErrCertificate
		}
		if len(block.Block.Data.Txs) > poolbridge.MaxTransactions {
			return SyncResult{}, ErrBounds
		}
		txs := make([][]byte, len(block.Block.Data.Txs))
		for i, raw := range block.Block.Data.Txs {
			if len(raw) == 0 || len(raw) > poolbridge.MaxTransactionBytes {
				return SyncResult{}, ErrBounds
			}
			txs[i] = raw
		}
		var hash Hash
		copy(hash[:], block.BlockID.Hash)
		preview, err := store.Preview(ctx, height, hash, txs)
		if err != nil {
			return SyncResult{}, err
		}
		if preview.Height != height || !bytes.Equal(preview.AppHash[:], next.Header.AppHash) {
			return SyncResult{}, ErrCertificate
		}
		prepared, tag, err := store.Finalize(ctx, height, hash, txs)
		if err != nil {
			return SyncResult{}, err
		}
		if prepared != preview {
			return SyncResult{}, poolbridge.ErrProtocol
		}
		committed, err := store.Commit(ctx, tag)
		if err != nil {
			return SyncResult{}, err
		} // never auto-retry uncertain Commit
		if committed != prepared {
			return SyncResult{}, poolbridge.ErrProtocol
		}
		state, current = committed, next
	}
	return resultFor(state, initial, uint64(tip)), nil
}

func (n *Network) Synchronize(ctx context.Context, o SyncOptions) (SyncResult, error) {
	if ctx == nil || ctx.Err() != nil || n == nil || o.Limit == 0 || o.Limit > maxSyncBlocks {
		return SyncResult{}, ErrBounds
	}
	remote, err := newPeer(o.Endpoint)
	if err != nil {
		return SyncResult{}, err
	}
	defer remote.close()
	store, err := poolbridge.Start(ctx, n.workerOptions(o.Worker, o.WorkerSHA256, o.Journal, o.Create))
	if err != nil {
		return SyncResult{}, err
	}
	defer store.Close()
	return n.synchronize(ctx, remote, store, o.Limit)
}

type Submission struct {
	Status          string `json:"status"`
	TxID            string `json:"txid"`
	ReferenceHeight uint64 `json:"reference_height"`
	Confirmed       bool   `json:"confirmed"`
}

// Submit never takes a wallet password, signs a transaction, releases a wallet
// reservation, retries a broadcast, or treats a mempool receipt as finality.
func (n *Network) Submit(ctx context.Context, o SyncOptions, raw []byte) (Submission, error) {
	txid := sha256.Sum256(raw)
	out := Submission{Status: "not_submitted", TxID: HashText(txid)}
	if ctx == nil || ctx.Err() != nil || n == nil || o.Create || len(raw) == 0 || len(raw) > poolbridge.MaxTransactionBytes || o.Limit == 0 || o.Limit > maxSyncBlocks {
		return out, ErrBounds
	}
	remote, err := newPeer(o.Endpoint)
	if err != nil {
		return out, err
	}
	defer remote.close()
	store, err := poolbridge.Start(ctx, n.workerOptions(o.Worker, o.WorkerSHA256, o.Journal, false))
	if err != nil {
		return out, err
	}
	defer store.Close()
	synced, err := n.synchronize(ctx, remote, store, o.Limit)
	if err != nil {
		return out, err
	}
	out.ReferenceHeight = synced.Height
	if !synced.CaughtUpToObservedTip {
		return out, ErrSyncRequired
	}
	if err = store.Check(ctx, raw); err != nil {
		return out, err
	}
	response, err := remote.BroadcastTxSync(ctx, types.Tx(raw))
	if err != nil || response == nil || !bytes.Equal(response.Hash, txid[:]) {
		out.Status = "unknown_reconcile_before_retry"
		return out, ErrSubmission
	}
	if response.Code != 0 {
		// Rejection by one mempool is not global non-inclusion. Preserve the
		// local wallet reservation and explicitly inspect authenticated history.
		out.Status = "rejected_by_this_mempool_not_global_cancellation"
		return out, poolbridge.ErrRejected
	}
	out.Status = "accepted_to_mempool_not_confirmed"
	return out, nil
}
