package merkle

import (
	"crypto/sha256"
	"github.com/youq616/Zevune/internal/protocol"
	"testing"
)

func leaf(h protocol.Hash) protocol.Hash { return sha256.Sum256(append([]byte{0}, h[:]...)) }
func pair(a, b protocol.Hash) protocol.Hash {
	x := append([]byte{1}, a[:]...)
	x = append(x, b[:]...)
	return sha256.Sum256(x)
}
func TestEmpty(t *testing.T) {
	if Root(nil) != sha256.Sum256(nil) {
		t.Fatal("bad empty root")
	}
}
func TestOneTwoThreeLeaves(t *testing.T) {
	a, b, c := protocol.Hash{1}, protocol.Hash{2}, protocol.Hash{3}
	if Root([]protocol.Hash{a}) != leaf(a) {
		t.Fatal("one")
	}
	if Root([]protocol.Hash{a, b}) != pair(leaf(a), leaf(b)) {
		t.Fatal("two")
	}
	if Root([]protocol.Hash{a, b, c}) != pair(pair(leaf(a), leaf(b)), leaf(c)) {
		t.Fatal("three")
	}
}
func TestOrderMatters(t *testing.T) {
	a, b := protocol.Hash{1}, protocol.Hash{2}
	if Root([]protocol.Hash{a, b}) == Root([]protocol.Hash{b, a}) {
		t.Fatal("order lost")
	}
}
