package orchardbridge

import "math"

// CommittedState MUST be an immutable snapshot owned by the consensus ledger.
// A transaction submitter must never supply this view. Holding a consistent
// snapshot and guarding its version again during atomic commit are the caller's
// responsibilities. This package does not provide a persistent Orchard tree.
type CommittedState interface {
	Height() uint64
	AppHash() Hash
	HasAnchor(Hash) bool
	IsSpent(Hash) bool
	HasCommitment(Hash) bool
}

// CheckedEffects is a PRE-COMMIT result tied to a snapshot. It is not a spend
// permission, durable commit, finality certificate, or replayable authorization.
// There is intentionally no method that directly applies it to a ledger.
type CheckedEffects struct {
	BaseHeight    uint64
	BaseAppHash   Hash
	PayloadDigest Hash
	Nullifiers    []Hash
	Commitments   []Hash
	Fee           uint64
}

func (a Authorization) CheckCommittedState(s CommittedState) (CheckedEffects, error) {
	var out CheckedEffects
	if s == nil || len(a.raw) == 0 || PayloadDigest(a.raw) != a.digest {
		return out, ErrState
	}
	e, err := Decode(a.raw)
	if err != nil {
		return out, err
	}
	height := s.Height()
	appHash := s.AppHash()
	if height == math.MaxUint64 || e.Expiry < height+1 || !s.HasAnchor(e.Anchor) {
		return out, ErrState
	}
	for _, action := range e.Actions {
		if s.IsSpent(action.Nullifier) || s.HasCommitment(action.Commitment) {
			return CheckedEffects{}, ErrState
		}
		out.Nullifiers = append(out.Nullifiers, action.Nullifier)
		out.Commitments = append(out.Commitments, action.Commitment)
	}
	if s.Height() != height || s.AppHash() != appHash {
		return CheckedEffects{}, ErrState
	}
	out.BaseHeight = height
	out.BaseAppHash = appHash
	out.PayloadDigest = a.digest
	out.Fee = e.Fee
	return out, nil
}
