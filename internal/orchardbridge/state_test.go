package orchardbridge

import (
	"context"
	"errors"
	"math"
	"testing"
	"time"
)

type testState struct {
	height         uint64
	hash           Hash
	anchor         Hash
	spent, outputs map[Hash]bool
	changing       bool
	calls          int
}

func (s *testState) Height() uint64 {
	s.calls++
	if s.changing && s.calls > 1 {
		return s.height + 1
	}
	return s.height
}
func (s *testState) AppHash() Hash             { return s.hash }
func (s *testState) HasAnchor(h Hash) bool     { return s.anchor == h }
func (s *testState) IsSpent(h Hash) bool       { return s.spent[h] }
func (s *testState) HasCommitment(h Hash) bool { return s.outputs[h] }

func TestAuthorizationZeroCannotCheckState(t *testing.T) {
	if _, err := (Authorization{}).CheckCommittedState(&testState{}); !errors.Is(err, ErrState) {
		t.Fatal(err)
	}
}
func TestStateChecksRejectAndPreserveOrder(t *testing.T) {
	w := helper(t, "valid", time.Second)
	raw := syntheticBytes(t)
	auth, err := w.VerifyAuthorization(context.Background(), raw)
	if err != nil {
		t.Fatal(err)
	}
	state := &testState{height: 7, hash: Hash{19}}
	e, err := auth.CheckCommittedState(state)
	if err != nil {
		t.Fatal(err)
	}
	if e.BaseHeight != 7 || e.BaseAppHash != state.hash || e.Fee != 1000 || e.Nullifiers[0][0] != 1 || e.Nullifiers[1][0] != 2 {
		t.Fatal("effects/order")
	}
	if state.height != 7 || len(state.spent) != 0 || len(state.outputs) != 0 {
		t.Fatal("mutated state")
	}
	cases := []CommittedState{
		nil, &testState{height: 100}, &testState{height: math.MaxUint64},
		&testState{anchor: Hash{1}}, &testState{spent: map[Hash]bool{{1}: true}},
		&testState{outputs: map[Hash]bool{{17}: true}}, &testState{changing: true},
	}
	for i, s := range cases {
		if _, err := auth.CheckCommittedState(s); err == nil {
			t.Fatal("accepted", i)
		}
	}
	e.Nullifiers[0][0] = 99
	again, err := auth.CheckCommittedState(state)
	if err != nil || again.Nullifiers[0][0] != 1 {
		t.Fatal("effect aliases")
	}
}
func TestStateTamperedAuthorizationRejected(t *testing.T) {
	raw := syntheticBytes(t)
	a := Authorization{raw: raw, digest: Hash{1}}
	if _, err := a.CheckCommittedState(&testState{}); !errors.Is(err, ErrState) {
		t.Fatal(err)
	}
}
