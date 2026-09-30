package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
)

var errTransactionPin = errors.New("transaction content pin rejected")

// Parse an explicitly requested content pin. This does not verify authorization.
// Empty is not a way to disable a present flag. Old absent-flag callers bypass it.
func parseTransactionPin(text string) ([32]byte, error) {
	var pin [32]byte
	if len(text) != 64 {
		return pin, errTransactionPin
	}
	raw, err := hex.DecodeString(text)
	if err != nil || hex.EncodeToString(raw) != text {
		return pin, errTransactionPin
	}
	copy(pin[:], raw)
	if pin == ([32]byte{}) {
		return pin, errTransactionPin
	}
	return pin, nil
}

// Check the very slice passed next to Submit, not a previous path hash. The
// original bounded file reader, same-start-state verification and current-state
// Check remain necessary; this pin cannot serve as cached spend permission.
func matchTransactionPin(raw []byte, expected [32]byte) error {
	if expected == ([32]byte{}) || sha256.Sum256(raw) != expected {
		return errTransactionPin
	}
	return nil
}
