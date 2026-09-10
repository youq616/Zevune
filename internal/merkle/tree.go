// Package merkle contains a public, SHA-256 framing tree for state-machine tests.
// It is NOT a zero-knowledge-friendly note tree or a production cryptographic choice.
package merkle

import (
	"crypto/sha256"
	"github.com/youq616/Zevune/internal/protocol"
	"math/bits"
)

func Root(leaves []protocol.Hash) protocol.Hash {
	if len(leaves) == 0 {
		return sha256.Sum256(nil)
	}
	if len(leaves) == 1 {
		b := make([]byte, 33)
		copy(b[1:], leaves[0][:])
		return sha256.Sum256(b)
	}
	k := 1 << (bits.Len(uint(len(leaves)-1)) - 1)
	left, right := Root(leaves[:k]), Root(leaves[k:])
	b := make([]byte, 65)
	b[0] = 1
	copy(b[1:33], left[:])
	copy(b[33:], right[:])
	return sha256.Sum256(b)
}
