package protocol

import "errors"

var ErrInvalidTransition = errors.New("invalid state transition")

// StateTransition is the single protocol boundary for future state changes.
// Modules should validate through this layer instead of mutating state directly.
type StateTransition struct {
	BeforeRoot [32]byte
	AfterRoot  [32]byte
	Height     uint64
}

func (s StateTransition) Validate() error {
	if s.Height == 0 {
		return ErrInvalidTransition
	}
	if s.BeforeRoot == s.AfterRoot {
		return ErrInvalidTransition
	}
	return nil
}
