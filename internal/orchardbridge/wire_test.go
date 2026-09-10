package orchardbridge

import (
	"bytes"
	"encoding/binary"
	"errors"
	"io"
	"math"
	"testing"
)

// This is intentionally NOT an Orchard proof. Acceptance substitutes remain
// confined to _test.go and are never linked into a shipped worker or node.
func synthetic(n int) *Envelope {
	e := &Envelope{Expiry: 100, Fee: 1000, ValueBalance: 1000, Actions: make([]Action, n), Proof: make([]byte, proofSize(n))}
	for i := range e.Actions {
		a := &e.Actions[i]
		a.Nullifier[0] = byte(i + 1)
		a.Commitment[0] = byte(i + 17)
		a.ValueCommitment[0] = byte(i + 33)
		a.RandomizedKey[0] = byte(i + 49)
		a.EphemeralKey[0] = byte(i + 65)
		a.NoteCiphertext[579] = byte(i + 1)
		a.OutCiphertext[79] = byte(i + 2)
		a.Signature[63] = byte(i + 3)
	}
	return e
}
func syntheticBytes(t testing.TB) []byte {
	t.Helper()
	b, err := Encode(synthetic(2))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestWireRoundTrip(t *testing.T) {
	for n := MinActions; n <= MaxActions; n++ {
		b, err := Encode(synthetic(n))
		if err != nil {
			t.Fatal(err)
		}
		if len(b) != wireSize(n) {
			t.Fatal("size")
		}
		e, err := Decode(b)
		if err != nil {
			t.Fatal(err)
		}
		round, err := Encode(e)
		if err != nil || !bytes.Equal(b, round) {
			t.Fatal("noncanonical roundtrip")
		}
	}
}
func TestWireEveryTruncation(t *testing.T) {
	b := syntheticBytes(t)
	for i := 0; i < len(b); i++ {
		if _, err := Decode(b[:i]); err == nil {
			t.Fatalf("accepted prefix %d", i)
		}
	}
}
func TestWireRejectsTrailingAndOversize(t *testing.T) {
	b := syntheticBytes(t)
	if _, err := Decode(append(b, 0)); err == nil {
		t.Fatal("trailer")
	}
	if _, err := Decode(make([]byte, MaxEnvelopeSize+1)); !errors.Is(err, ErrBounds) {
		t.Fatal(err)
	}
}
func TestWireMutationPolicies(t *testing.T) {
	cases := map[string]func([]byte){
		"magic":                func(b []byte) { b[0] ^= 1 },
		"zero_actions":         func(b []byte) { b[64] = 0 },
		"one_action":           func(b []byte) { b[64] = 1 },
		"large_actions":        func(b []byte) { b[64] = 255 },
		"disabled_flags":       func(b []byte) { b[65] = 0 },
		"unknown_flags":        func(b []byte) { b[65] = 7 },
		"expiry_zero":          func(b []byte) { clear(b[8:16]) },
		"negative_balance":     func(b []byte) { binary.BigEndian.PutUint64(b[24:32], math.MaxUint64) },
		"balance_fee_mismatch": func(b []byte) { b[23] ^= 1 },
		"fee_overflow":         func(b []byte) { binary.BigEndian.PutUint64(b[16:24], math.MaxUint64) },
		"proof_length":         func(b []byte) { binary.BigEndian.PutUint32(b[HeaderSize+2*ActionSize:], math.MaxUint32) },
		"duplicate_nf": func(b []byte) {
			copy(b[HeaderSize+ActionSize+32:HeaderSize+ActionSize+64], b[HeaderSize+32:HeaderSize+64])
		},
		"duplicate_cm": func(b []byte) {
			copy(b[HeaderSize+ActionSize+96:HeaderSize+ActionSize+128], b[HeaderSize+96:HeaderSize+128])
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			b := syntheticBytes(t)
			mutate(b)
			if _, err := Decode(b); err == nil {
				t.Fatal("accepted malformed envelope")
			}
		})
	}
}
func TestWireCopiesInputAndOutput(t *testing.T) {
	b := syntheticBytes(t)
	original := bytes.Clone(b)
	e, err := Decode(b)
	if err != nil {
		t.Fatal(err)
	}
	clear(b)
	encoded, err := Encode(e)
	if err != nil || !bytes.Equal(encoded, original) {
		t.Fatal("borrowed input")
	}
	e.Proof[0] ^= 1
	e.Actions[0].NoteCiphertext[0] ^= 1
	if !bytes.Equal(encoded, original) {
		t.Fatal("borrowed output")
	}
}
func TestEncodeInvalid(t *testing.T) {
	if _, err := Encode(nil); err == nil {
		t.Fatal("nil")
	}
	for _, n := range []int{0, 1, MaxActions + 1} {
		if _, err := Encode(synthetic(n)); err == nil {
			t.Fatal(n)
		}
	}
	e := synthetic(2)
	e.Proof = nil
	if _, err := Encode(e); err == nil {
		t.Fatal("proof")
	}
}
func TestFrameRoundTrip(t *testing.T) {
	var b bytes.Buffer
	raw := syntheticBytes(t)
	if err := writeFrame(&b, raw); err != nil {
		t.Fatal(err)
	}
	got, err := readFrame(&b, maxFrame)
	if err != nil || !bytes.Equal(got, raw) {
		t.Fatal("frame", err)
	}
}
func TestFrameOversizeBeforeAllocation(t *testing.T) {
	var b [4]byte
	binary.BigEndian.PutUint32(b[:], math.MaxUint32)
	if _, err := readFrame(bytes.NewReader(b[:]), maxFrame); !errors.Is(err, ErrBounds) {
		t.Fatal(err)
	}
	if _, err := readFrame(bytes.NewReader(make([]byte, 4)), maxFrame); !errors.Is(err, ErrBounds) {
		t.Fatal(err)
	}
}
func TestFrameTruncated(t *testing.T) {
	for _, b := range [][]byte{{}, {0}, {0, 0, 0}, {0, 0, 0, 4, 1, 2}} {
		if _, err := readFrame(bytes.NewReader(b), maxFrame); err == nil {
			t.Fatal("truncation")
		}
	}
}

type partialWriter struct{ bytes.Buffer }

func (w *partialWriter) Write(p []byte) (int, error) {
	if len(p) > 3 {
		p = p[:3]
	}
	return w.Buffer.Write(p)
}
func TestFramePartialWrites(t *testing.T) {
	var w partialWriter
	raw := syntheticBytes(t)
	if err := writeFrame(&w, raw); err != nil {
		t.Fatal(err)
	}
	b, err := readFrame(&w, maxFrame)
	if err != nil || !bytes.Equal(b, raw) {
		t.Fatal(err)
	}
}

type zeroWriter struct{}

func (zeroWriter) Write([]byte) (int, error) { return 0, nil }
func TestFrameZeroWrite(t *testing.T) {
	if !errors.Is(writeFrame(zeroWriter{}, []byte{1}), io.ErrShortWrite) {
		t.Fatal("short write")
	}
}
func TestFrameWriteBounds(t *testing.T) {
	if !errors.Is(writeFrame(io.Discard, nil), ErrBounds) {
		t.Fatal("empty")
	}
	if !errors.Is(writeFrame(io.Discard, make([]byte, maxFrame+1)), ErrBounds) {
		t.Fatal("oversize")
	}
}
func FuzzDecodeEnvelope(f *testing.F) {
	f.Add(syntheticBytes(f))
	f.Add([]byte{})
	f.Add([]byte(WireMagic))
	f.Fuzz(func(t *testing.T, b []byte) {
		e, err := Decode(b)
		if err != nil {
			return
		}
		round, err := Encode(e)
		if err != nil || !bytes.Equal(b, round) {
			t.Fatal("decoder accepted noncanonical bytes")
		}
	})
}
func FuzzReadFrame(f *testing.F) {
	f.Add([]byte{0, 0, 0, 1, 9})
	f.Add([]byte{255, 255, 255, 255})
	f.Fuzz(func(t *testing.T, b []byte) {
		raw, err := readFrame(bytes.NewReader(b), maxFrame)
		if err == nil && (len(raw) == 0 || len(raw) > maxFrame) {
			t.Fatal("limit")
		}
	})
}
func BenchmarkDecodeMaxEnvelope(b *testing.B) {
	raw, err := Encode(synthetic(MaxActions))
	if err != nil {
		b.Fatal(err)
	}
	b.ReportAllocs()
	b.SetBytes(int64(len(raw)))
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if _, err := Decode(raw); err != nil {
			b.Fatal(err)
		}
	}
}

func TestFrameInvalidLimit(t *testing.T) {
	for _, limit := range []int{-1, 0, maxFrame + 1} {
		if _, err := readFrame(bytes.NewReader([]byte{255, 255, 255, 255}), limit); !errors.Is(err, ErrBounds) {
			t.Fatal(err)
		}
	}
}
