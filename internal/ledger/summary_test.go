package ledger

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"math/rand"
	"sort"
	"testing"

	"github.com/youq616/Zevune/internal/protocol"
)

// Frozen M1 encoder, retained only as a compatibility and allocation baseline.
func legacyBufferedSummary(chain string, s *state) Summary {
	var b bytes.Buffer
	b.WriteString("VEIL-PROTOTYPE-APPHASH\x00")
	b.WriteByte(byte(len(chain)))
	b.WriteString(chain)
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
	return Summary{ChainID: chain, Height: s.height, Root: s.roots[len(s.roots)-1].Root, AppHash: sha256.Sum256(b.Bytes()), CommitmentCount: len(s.commitments), SpentCount: len(s.spent), PublicFees: s.fees}
}

func TestStreamingSummaryMatchesLegacy(t *testing.T) {
	rng := rand.New(rand.NewSource(912026)) // Synthetic public test data, not key generation.
	for iteration := 0; iteration < 100; iteration++ {
		s := state{height: rng.Uint64(), fees: rng.Uint64(), spent: map[protocol.Hash]struct{}{}}
		for i := 0; i < iteration; i++ {
			var c, n protocol.Hash
			_, _ = rng.Read(c[:])
			_, _ = rng.Read(n[:])
			s.commitments = append(s.commitments, c)
			s.spent[n] = struct{}{}
		}
		for i := 0; i < 1+iteration%RootWindow; i++ {
			var root protocol.Hash
			_, _ = rng.Read(root[:])
			s.roots = append(s.roots, RootRecord{Height: uint64(i), Root: root})
		}
		chain := fmt.Sprintf("compatibility-%d", iteration)
		if summarizeState(chain, &s) != legacyBufferedSummary(chain, &s) {
			t.Fatal("changed legacy app hash", iteration)
		}
	}
}

func summaryBenchmarkState(n int) state {
	s := state{height: 100, fees: 100, spent: map[protocol.Hash]struct{}{}, roots: []RootRecord{{Height: 100}}}
	for i := 0; i < n; i++ {
		h := sha256.Sum256([]byte(fmt.Sprintf("PUBLIC-SYNTHETIC-%d", i)))
		s.commitments = append(s.commitments, h)
		s.spent[h] = struct{}{}
	}
	return s
}

var summaryBenchmarkSink Summary

// Measures ONLY summary encoding on synthetic in-memory state: no ZK, network,
// disk sync, consensus, wallet or payments. It is not a transaction benchmark.
func BenchmarkSummaryEncoding(b *testing.B) {
	for _, n := range []int{1000, 10000} {
		s := summaryBenchmarkState(n)
		for _, tc := range []struct {
			name string
			fn   func(string, *state) Summary
		}{
			{"legacy-buffered", legacyBufferedSummary}, {"streaming", summarizeState},
		} {
			b.Run(fmt.Sprintf("entries-%d/%s", n, tc.name), func(b *testing.B) {
				b.ReportAllocs()
				for i := 0; i < b.N; i++ {
					summaryBenchmarkSink = tc.fn(diskChain, &s)
				}
			})
		}
	}
}
