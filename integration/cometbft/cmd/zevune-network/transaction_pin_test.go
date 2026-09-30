package main

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTransactionPinCanonicalAndSameRaw(t *testing.T) {
	raw := []byte("synthetic public content, not a valid payment")
	expected := sha256.Sum256(raw)
	pin, err := parseTransactionPin(hex.EncodeToString(expected[:]))
	if err != nil || pin != expected || matchTransactionPin(raw, pin) != nil {
		t.Fatal("matching pin rejected", err)
	}
	for _, text := range []string{"", "0", strings.Repeat("0", 64), strings.Repeat("A", 64), strings.Repeat("gg", 32), " " + hex.EncodeToString(expected[:])} {
		if _, err := parseTransactionPin(text); err != errTransactionPin {
			t.Fatal("bad pin accepted")
		}
	}
	if matchTransactionPin(raw, [32]byte{}) != errTransactionPin {
		t.Fatal("empty expected accepted")
	}
	raw[0] ^= 1
	if matchTransactionPin(raw, pin) != errTransactionPin {
		t.Fatal("modified same-size raw accepted")
	}
}

func TestTransactionPinRealFileReplacement(t *testing.T) {
	path := filepath.Join(t.TempDir(), "public.tx")
	initial := []byte("first synthetic data")
	if err := os.WriteFile(path, initial, 0600); err != nil {
		t.Fatal(err)
	}
	pin := sha256.Sum256(initial)
	if err := os.WriteFile(path, []byte("other synthetic data"), 0600); err != nil {
		t.Fatal(err)
	}
	// The pin is applied to bytes actually read now, not a cached path digest.
	raw, err := os.ReadFile(path)
	if err != nil || matchTransactionPin(raw, pin) != errTransactionPin {
		t.Fatal("replacement not refused", err)
	}
}
