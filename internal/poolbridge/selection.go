package poolbridge

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"math/bits"
)

const MaxProposalCandidates = 64
const MaxProposalBytes = MaxTransactions * MaxTransactionBytes

// selectionBytes owns all candidate bytes. This is a read-only selection request,
// not the block encoding and not a signed block or commit token.
func selectionBytes(height uint64, limit uint64, txs [][]byte) ([]byte, [][]byte, error) {
	return LegacyJournal.selectionBytes(height, limit, txs)
}
func (p StorageProfile) selectionBytes(height uint64, limit uint64, txs [][]byte) ([]byte, [][]byte, error) {
	if !p.valid() || height == 0 || height > p.MaxHeight() || limit > MaxProposalBytes || len(txs) > MaxProposalCandidates {
		return nil, nil, ErrBounds
	}
	size := 50
	for _, tx := range txs {
		if len(tx) > MaxTransactionBytes {
			return nil, nil, ErrBounds
		}
		size += 4 + len(tx)
	}
	b := make([]byte, 50, size)
	binary.BigEndian.PutUint64(b[:8], height)
	marker := sha256.Sum256([]byte("ZEVUNE-PROPOSAL-PREFLIGHT"))
	copy(b[8:40], marker[:])
	binary.BigEndian.PutUint64(b[40:48], limit)
	binary.BigEndian.PutUint16(b[48:50], uint16(len(txs)))
	offsets := make([]int, 0, len(txs))
	for _, tx := range txs {
		var n [4]byte
		binary.BigEndian.PutUint32(n[:], uint32(len(tx)))
		b = append(b, n[:]...)
		offsets = append(offsets, len(b))
		b = append(b, tx...)
	}
	owned := make([][]byte, len(txs))
	for i, offset := range offsets {
		owned[i] = b[offset : offset+len(txs[i]) : offset+len(txs[i])]
	}
	return b, owned, nil
}

// selectedBytes rejects impossible worker replies. Cryptographic validity is
// still independently enforced by ProcessProposal, FinalizeBlock and Commit.
func selectedBytes(txs [][]byte, mask, limit uint64) ([][]byte, error) {
	if len(txs) > MaxProposalCandidates || bits.OnesCount64(mask) > MaxTransactions ||
		(len(txs) < 64 && mask>>uint(len(txs)) != 0) {
		return nil, ErrProtocol
	}
	selected := make([][]byte, 0, bits.OnesCount64(mask))
	for i, tx := range txs {
		if mask&(uint64(1)<<uint(i)) == 0 {
			continue
		}
		if len(tx) == 0 || len(tx) > MaxTransactionBytes || uint64(len(tx)) > limit {
			return nil, ErrProtocol
		}
		limit -= uint64(len(tx))
		selected = append(selected, append([]byte(nil), tx...))
	}
	return selected, nil
}

// SelectProposal chooses at most 16 transactions from at most 64 candidates in
// one bounded worker request. Invalid candidates do not poison later candidates.
// No candidate state is persisted, nor is a successful selection a spend permit.
func (c *Client) SelectProposal(ctx context.Context, height uint64, limit uint64, txs [][]byte) ([][]byte, error) {
	b, owned, err := c.profile.selectionBytes(height, limit, txs)
	if err != nil {
		return nil, err
	}
	var mask uint64
	state, err := c.exchangeMask(ctx, 5, b, &mask)
	if err != nil {
		return nil, err
	}
	chosen, err := selectedBytes(owned, mask, limit)
	if err != nil || state.Height != height {
		_ = c.Close()
		return nil, ErrProtocol
	}
	return chosen, nil
}
