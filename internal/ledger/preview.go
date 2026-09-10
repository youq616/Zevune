package ledger

import (
	"crypto/sha256"
	"encoding/binary"
	"errors"

	"github.com/youq616/Zevune/internal/protocol"
)

var (
	ErrStalePreview    = errors.New("preview no longer matches the committed ledger")
	ErrPreviewMismatch = errors.New("block bytes or result do not match preview")
)

// BlockPreview is a public, reproducible description of a candidate transition.
// It contains no authority: callers may forge it, so CommitPreview revalidates
// everything. It is NOT a consensus decision, signature, ZK proof or receipt.
// Height and BaseAppHash bind the candidate to one committed state. BlockID binds
// the ordered, full envelope bytes (including proofs), not just state effects.
// No private candidate state or journal is retained between calls.
type BlockPreview struct {
	Height      uint64        `json:"height"`
	BaseAppHash protocol.Hash `json:"base_app_hash"`
	BlockID     protocol.Hash `json:"prototype_block_id"`
	Result      Summary       `json:"result"`
}

// PreviewBlock validates and executes on a disposable state copy. It neither
// reserves nullifiers nor writes the journal. Multiple competing proposals can
// be previewed against the same committed state. Verifier must be deterministic,
// side-effect-free and concurrency-safe, as also required by concurrent CheckTx.
// The caller must not mutate txs or its nested slices during either method call.
func (e *Engine) PreviewBlock(height uint64, txs []protocol.Envelope) (BlockPreview, error) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	staged, owned, err := e.stageBlockLocked(height, txs)
	if err != nil {
		return BlockPreview{}, err
	}
	id, err := blockDigest(e.chainID, height, owned)
	if err != nil {
		return BlockPreview{}, err
	}
	return BlockPreview{
		Height: height, BaseAppHash: e.summaryLocked().AppHash, BlockID: id,
		Result: summarizeState(e.chainID, &staged),
	}, nil
}

// CommitPreview revalidates a candidate under the write lock, checks its base,
// exact bytes and resulting state, then uses the existing sync-before-publish
// path. A changed or stale preview never writes. Successful replay is NOT
// idempotent: a second commit of the same preview returns ErrStalePreview.
// Only a future trusted consensus adapter may decide when to call this method;
// it is intentionally not exposed by any HTTP or command-line payment endpoint.
func (e *Engine) CommitPreview(p BlockPreview, txs []protocol.Envelope) (Summary, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if err := e.usableLocked(); err != nil {
		return Summary{}, err
	}
	current := e.summaryLocked()
	if p.Height <= current.Height || p.Height-current.Height != 1 || p.BaseAppHash != current.AppHash {
		return Summary{}, ErrStalePreview
	}
	staged, owned, err := e.stageBlockLocked(p.Height, txs)
	if err != nil {
		return Summary{}, err
	}
	id, err := blockDigest(e.chainID, p.Height, owned)
	if err != nil {
		return Summary{}, err
	}
	result := summarizeState(e.chainID, &staged)
	if p.BlockID != id || p.Result != result {
		return Summary{}, ErrPreviewMismatch
	}
	return e.commitStateLocked(p.Height, owned, staged)
}

// blockDigest accepts only a bounded block. This separate prototype domain does
// not change v0 transaction IDs, the app hash, journal format or chain ID.
func blockDigest(chain string, height uint64, txs []protocol.Envelope) (protocol.Hash, error) {
	if !protocol.ValidChainID(chain) {
		return protocol.Hash{}, ErrWrongChain
	}
	if len(txs) > MaxBlockTransactions {
		return protocol.Hash{}, ErrBlockLimit
	}
	h := sha256.New()
	_, _ = h.Write([]byte("ZEVUNE-PROTOTYPE-BLOCK\x00\x01"))
	_, _ = h.Write([]byte{byte(len(chain))})
	_, _ = h.Write([]byte(chain))
	_ = binary.Write(h, binary.BigEndian, height)
	_ = binary.Write(h, binary.BigEndian, uint32(len(txs)))
	total := 0
	for _, tx := range txs {
		b, err := tx.MarshalBinary()
		if err != nil {
			return protocol.Hash{}, err
		}
		total += len(b)
		if total > MaxBlockBytes {
			return protocol.Hash{}, ErrBlockLimit
		}
		_ = binary.Write(h, binary.BigEndian, uint32(len(b)))
		_, _ = h.Write(b)
	}
	var out protocol.Hash
	copy(out[:], h.Sum(nil))
	return out, nil
}
