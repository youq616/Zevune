package ledger

import (
	"errors"
	"github.com/youq616/Zevune/internal/protocol"
)

var ErrProofBackendUnavailable = errors.New("real zero-knowledge verifier is not implemented; payments are disabled")

// Verifier is a trusted local implementation boundary, NOT a remotely trusted signer.
// A real implementation MUST verify membership, ownership/authorization, ranges,
// conservation including fees, unique/derived nullifiers, output construction and
// binding to chain/version/circuit, anchor, expiry, EVERY output and public effect.
// Returning nil without those checks is a critical money-creation vulnerability.
// No accepting verifier ships in executable code. Test doubles live ONLY in *_test.go.
type Verifier interface{ Verify(protocol.Envelope) error }
type UnavailableVerifier struct{}

func (UnavailableVerifier) Verify(protocol.Envelope) error { return ErrProofBackendUnavailable }
