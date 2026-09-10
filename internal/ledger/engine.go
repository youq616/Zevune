// Package ledger is a single-process state-machine prototype with optional local journaling.
// ApplyBlock is NOT a consensus protocol and does not establish economic finality.
package ledger

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"github.com/youq616/Zevune/internal/merkle"
	"github.com/youq616/Zevune/internal/protocol"
	"io"
	"math"
	"sort"
	"sync"
)

const (
	RootWindow           = 64
	MaxBlockTransactions = 128
	MaxBlockBytes        = 2 * 1024 * 1024
)

var (
	ErrWrongChain      = errors.New("wrong chain")
	ErrExpired         = errors.New("expired transaction")
	ErrUnknownAnchor   = errors.New("anchor is not in retained committed roots")
	ErrDoubleSpend     = errors.New("duplicate or spent nullifier")
	ErrDuplicateOutput = errors.New("duplicate output commitment")
	ErrHeight          = errors.New("unexpected block height")
	ErrBlockLimit      = errors.New("block exceeds prototype bounds")
)

type RootRecord struct {
	Height uint64
	Root   protocol.Hash
}
type state struct {
	height      uint64
	fees        uint64
	commitments []protocol.Hash
	outputs     map[protocol.Hash]struct{}
	spent       map[protocol.Hash]struct{}
	roots       []RootRecord
}

func (s state) clone() state {
	c := s
	c.commitments = append([]protocol.Hash(nil), s.commitments...)
	c.roots = append([]RootRecord(nil), s.roots...)
	c.outputs = make(map[protocol.Hash]struct{}, len(s.outputs))
	for k := range s.outputs {
		c.outputs[k] = struct{}{}
	}
	c.spent = make(map[protocol.Hash]struct{}, len(s.spent))
	for k := range s.spent {
		c.spent[k] = struct{}{}
	}
	return c
}

type Engine struct {
	mu         sync.RWMutex
	chainID    string
	verifier   Verifier
	s          state
	journal    *journal
	closed     bool
	storageErr error
}
type Summary struct {
	ChainID         string        `json:"chain_id"`
	Height          uint64        `json:"height"`
	Root            protocol.Hash `json:"prototype_note_root"`
	AppHash         protocol.Hash `json:"prototype_app_hash"`
	CommitmentCount int           `json:"commitments"`
	SpentCount      int           `json:"spent_nullifiers"`
	PublicFees      uint64        `json:"public_fees"`
}

// New accepts public synthetic genesis commitments ONLY for integration tests.
// No proof of genesis issuance or total supply is implemented here.
func New(chain string, genesis []protocol.Hash, v Verifier) (*Engine, error) {
	if !protocol.ValidChainID(chain) {
		return nil, ErrWrongChain
	}
	if v == nil {
		return nil, ErrProofBackendUnavailable
	}
	if len(genesis) > 1024 {
		return nil, ErrBlockLimit
	}
	s := state{commitments: append([]protocol.Hash(nil), genesis...), outputs: map[protocol.Hash]struct{}{}, spent: map[protocol.Hash]struct{}{}}
	for _, c := range genesis {
		if _, ok := s.outputs[c]; ok {
			return nil, ErrDuplicateOutput
		}
		s.outputs[c] = struct{}{}
	}
	s.roots = []RootRecord{{Height: 0, Root: merkle.Root(s.commitments)}}
	return &Engine{chainID: chain, verifier: v, s: s}, nil
}
func (e *Engine) cheapChecks(s *state, t protocol.Envelope, height uint64) error {
	if err := t.ValidateShape(); err != nil {
		return err
	}
	if t.ChainID != e.chainID {
		return ErrWrongChain
	}
	if t.ExpiryHeight < height {
		return ErrExpired
	}
	known := false
	for _, r := range s.roots {
		if r.Root == t.Anchor {
			known = true
			break
		}
	}
	if !known {
		return ErrUnknownAnchor
	}
	seen := make(map[protocol.Hash]bool, len(t.Nullifiers))
	for _, n := range t.Nullifiers {
		if _, ok := s.spent[n]; ok || seen[n] {
			return ErrDoubleSpend
		}
		seen[n] = true
	}
	outs := make(map[protocol.Hash]bool, len(t.Outputs))
	for _, o := range t.Outputs {
		if _, ok := s.outputs[o.Commitment]; ok || outs[o.Commitment] {
			return ErrDuplicateOutput
		}
		outs[o.Commitment] = true
	}
	if t.Fee > math.MaxUint64-s.fees {
		return fmt.Errorf("fee accumulator overflow")
	}
	return nil
}

// CheckTx is read-only preflight. It does not reserve nullifiers or guarantee inclusion.
func (e *Engine) CheckTx(t protocol.Envelope) error {
	t = t.Clone()
	e.mu.RLock()
	defer e.mu.RUnlock()
	if err := e.usableLocked(); err != nil {
		return err
	}
	if e.s.height == math.MaxUint64 {
		return ErrHeight
	}
	if err := e.cheapChecks(&e.s, t, e.s.height+1); err != nil {
		return err
	}
	return e.verifier.Verify(t.Clone())
}

// ApplyBlock validates an already-ordered block. When opened with OpenPersistent,
// the journal is synced before exposing the new in-memory state. This is not
// an RPC, mempool, validator signature, or finality certificate.
// The full-state copy is deliberately simple and O(history); it is NOT scalable storage.
func (e *Engine) ApplyBlock(height uint64, txs []protocol.Envelope) (Summary, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	staged, owned, err := e.stageBlockLocked(height, txs)
	if err != nil {
		return Summary{}, err
	}
	return e.commitStateLocked(height, owned, staged)
}

// stageBlockLocked is the single validation path for preview, direct apply and
// checked commit. The caller holds e.mu; neither e.s nor the journal is changed.
func (e *Engine) stageBlockLocked(height uint64, txs []protocol.Envelope) (state, []protocol.Envelope, error) {
	if err := e.usableLocked(); err != nil {
		return state{}, nil, err
	}
	if e.s.height == math.MaxUint64 || height != e.s.height+1 {
		return state{}, nil, ErrHeight
	}
	if len(txs) > MaxBlockTransactions {
		return state{}, nil, ErrBlockLimit
	}
	size := 0
	owned := make([]protocol.Envelope, len(txs))
	for i, t := range txs {
		b, err := t.MarshalBinary()
		if err != nil {
			return state{}, nil, err
		}
		size += len(b)
		if size > MaxBlockBytes {
			return state{}, nil, ErrBlockLimit
		}
		owned[i] = t.Clone()
	}
	staged := e.s.clone()
	for i, t := range owned {
		if err := e.cheapChecks(&staged, t, height); err != nil {
			return state{}, nil, fmt.Errorf("transaction %d: %w", i, err)
		}
		if err := e.verifier.Verify(t.Clone()); err != nil {
			return state{}, nil, fmt.Errorf("transaction %d: %w", i, err)
		}
		for _, n := range t.Nullifiers {
			staged.spent[n] = struct{}{}
		}
		for _, o := range t.Outputs {
			staged.outputs[o.Commitment] = struct{}{}
			staged.commitments = append(staged.commitments, o.Commitment)
		}
		staged.fees += t.Fee
	}
	staged.height = height
	staged.roots = append(staged.roots, RootRecord{Height: height, Root: merkle.Root(staged.commitments)})
	if len(staged.roots) > RootWindow {
		staged.roots = append([]RootRecord(nil), staged.roots[len(staged.roots)-RootWindow:]...)
	}
	return staged, owned, nil
}

// commitStateLocked is reached only after validation and optional preview checks.
// A sync failure has an uncertain disk outcome; memory must not advance.
func (e *Engine) commitStateLocked(height uint64, owned []protocol.Envelope, staged state) (Summary, error) {
	if e.journal != nil {
		if err := e.journal.appendBlock(height, owned); err != nil {
			e.storageErr = err // No further writes after an uncertain disk outcome.
			return Summary{}, fmt.Errorf("%w: %v", ErrStorageUnavailable, err)
		}
	}
	e.s = staged
	return e.summaryLocked(), nil
}
func (e *Engine) Summary() Summary       { e.mu.RLock(); defer e.mu.RUnlock(); return e.summaryLocked() }
func (e *Engine) summaryLocked() Summary { return summarizeState(e.chainID, &e.s) }

func summarizeState(chain string, s *state) Summary {
	h := sha256.New()
	io.WriteString(h, "VEIL-PROTOTYPE-APPHASH\x00")
	h.Write([]byte{byte(len(chain))})
	io.WriteString(h, chain)
	_ = binary.Write(h, binary.BigEndian, protocol.Version)
	io.WriteString(h, protocol.CircuitID)
	_ = binary.Write(h, binary.BigEndian, s.height)
	_ = binary.Write(h, binary.BigEndian, s.fees)
	_ = binary.Write(h, binary.BigEndian, uint64(len(s.commitments)))
	for _, c := range s.commitments {
		h.Write(c[:])
	}
	sorted := make([]protocol.Hash, 0, len(s.spent))
	for n := range s.spent {
		sorted = append(sorted, n)
	}
	sort.Slice(sorted, func(i, j int) bool { return bytes.Compare(sorted[i][:], sorted[j][:]) < 0 })
	_ = binary.Write(h, binary.BigEndian, uint64(len(sorted)))
	for _, n := range sorted {
		h.Write(n[:])
	}
	_ = binary.Write(h, binary.BigEndian, uint64(len(s.roots)))
	for _, r := range s.roots {
		_ = binary.Write(h, binary.BigEndian, r.Height)
		h.Write(r.Root[:])
	}
	var appHash protocol.Hash
	copy(appHash[:], h.Sum(nil))
	return Summary{ChainID: chain, Height: s.height, Root: s.roots[len(s.roots)-1].Root, AppHash: appHash, CommitmentCount: len(s.commitments), SpentCount: len(s.spent), PublicFees: s.fees}
}
