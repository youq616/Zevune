package main

import (
	"context"
	"crypto/sha256"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestTransactionPinFlagSyntaxBeforeConfigurationAndIO(t *testing.T) {
	root := t.TempDir()
	for _, text := range []string{"", "bad", "0000000000000000000000000000000000000000000000000000000000000000"} {
		args := []string{"submit", "--no-real-funds", "--worker", filepath.Join(root, "no-worker"),
			"--config", filepath.Join(root, "no-config"), "--tx-sha256", text}
		if err := execute(context.Background(), args, nil, io.Discard); err != errTransactionPin {
			t.Fatalf("hash syntax did not precede configuration: %v", err)
		}
	}
	for _, command := range []string{"sync", "storage", "run"} {
		args := []string{command, "--no-real-funds", "--worker", filepath.Join(root, "no-worker"), "--tx-sha256", "11"}
		if execute(context.Background(), args, nil, io.Discard) == nil {
			t.Fatal("pin flag accepted outside submit")
		}
	}
}

func TestTransactionPinRetainsOriginalBoundedFileRead(t *testing.T) {
	p := filepath.Join(t.TempDir(), "pending.tx")
	b := []byte("bounded synthetic bytes; not a proof fixture")
	if err := os.WriteFile(p, b, 0600); err != nil {
		t.Fatal(err)
	}
	raw, err := transactionFile(p)
	if err != nil || matchTransactionPin(raw, sha256.Sum256(b)) != nil {
		t.Fatal("original read compatibility", err)
	}
	b[0] ^= 1
	if err := os.WriteFile(p, b, 0600); err != nil {
		t.Fatal(err)
	}
	changed, err := transactionFile(p)
	if err != nil || matchTransactionPin(changed, sha256.Sum256(raw)) != errTransactionPin {
		t.Fatal("content replacement accepted", err)
	}
	if err := os.WriteFile(p, make([]byte, 28135), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := transactionFile(p); err == nil {
		t.Fatal("original size limit changed")
	}
}
