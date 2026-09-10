// Package ledger is a single-process, in-memory state-machine prototype.
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
	mu       sync.RWMutex
	chainID  string
	verifier Verifier
	s        state
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
	if e.s.height == math.MaxUint64 {
		return ErrHeight
	}
	if err := e.cheapChecks(&e.s, t, e.s.height+1); err != nil {
		return err
	}
	return e.verifier.Verify(t.Clone())
}

// ApplyBlock atomically validates an already-ordered block in memory.
// It is NOT an RPC, mempool, durable commit, validator signature, or finality certificate.
// The full-state copy is deliberately simple and O(history); it is NOT scalable storage.
func (e *Engine) ApplyBlock(height uint64, txs []protocol.Envelope) (Summary, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.s.height == math.MaxUint64 || height != e.s.height+1 {
		return Summary{}, ErrHeight
	}
	if len(txs) > MaxBlockTransactions {
		return Summary{}, ErrBlockLimit
	}
	size := 0
	owned := make([]protocol.Envelope, len(txs))
	for i, t := range txs {
		b, err := t.MarshalBinary()
		if err != nil {
			return Summary{}, err
		}
		size += len(b)
		if size > MaxBlockBytes {
			return Summary{}, ErrBlockLimit
		}
		owned[i] = t.Clone()
	}
	staged := e.s.clone()
	for i, t := range owned {
		if err := e.cheapChecks(&staged, t, height); err != nil {
			return Summary{}, fmt.Errorf("transaction %d: %w", i, err)
		}
		if err := e.verifier.Verify(t.Clone()); err != nil {
			return Summary{}, fmt.Errorf("transaction %d: %w", i, err)
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
	e.s = staged
	return e.summaryLocked(), nil
}
func (e *Engine) Summary() Summary { e.mu.RLock(); defer e.mu.RUnlock(); return e.summaryLocked() }
func (e *Engine) summaryLocked() Summary {
	s := &e.s
	var b bytes.Buffer
	b.WriteString("VEIL-PROTOTYPE-APPHASH\x00")
	b.WriteByte(byte(len(e.chainID)))
	b.WriteString(e.chainID)
	_ = binary.Write(&b, binary.BigEndian, protocol.Version)
	b.WriteString(protocol.CircuitID)
	_ = binary.Write(&b, binary.BigEndian, s.height)
	_ = binary.Write(&b, binary.BigEndian, s.fees)
	_ = binary.Write(&b, binary.BigEndian, uint64(len(s.commitments)))
	for _, c := range s.commitments {
		b.Write(c[:])
	}
	sorted := make([]protocol.Hash, 0, len(s.spent))
	for n := range s.spent {
		sorted = append(sorted, n)
	}
	sort.Slice(sorted, func(i, j int) bool { return bytes.Compare(sorted[i][:], sorted[j][:]) < 0 })
	_ = binary.Write(&b, binary.BigEndian, uint64(len(sorted)))
	for _, n := range sorted {
		b.Write(n[:])
	}
	_ = binary.Write(&b, binary.BigEndian, uint64(len(s.roots)))
	for _, r := range s.roots {
		_ = binary.Write(&b, binary.BigEndian, r.Height)
		b.Write(r.Root[:])
	}
	return Summary{ChainID: e.chainID, Height: s.height, Root: s.roots[len(s.roots)-1].Root, AppHash: sha256.Sum256(b.Bytes()), CommitmentCount: len(s.commitments), SpentCount: len(s.spent), PublicFees: s.fees}
}
