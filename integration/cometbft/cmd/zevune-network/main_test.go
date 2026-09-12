package main

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/youq616/Zevune/internal/poolbridge"
)

func TestMalformedCommandsNeverCreateOrOverwrite(t *testing.T) {
	home := filepath.Join(t.TempDir(), "must-not-exist")
	for _, args := range [][]string{nil, {"reset"}, {"init", "--home", home}, {"init", "--no-real-funds", "--no-real-funds"}, {"init", "--no-real-funds=false"}, {"run", "--no-real-funds", "--skip-proof"}, {"version", "extra"}, {"sync", "--no-real-funds", "--endpoint=http://evil:9999"}} {
		var out bytes.Buffer
		if execute(context.Background(), args, bytes.NewReader(nil), &out) == nil {
			t.Fatalf("accepted malformed args %v", args)
		}
		if _, e := os.Stat(home); !os.IsNotExist(e) {
			t.Fatal("malformed input mutated disk")
		}
	}
	var out bytes.Buffer
	if execute(context.Background(), []string{"version"}, nil, &out) != nil || !bytes.Contains(out.Bytes(), []byte(`"real_funds_allowed":false`)) {
		t.Fatal("version safety scope")
	}
}
func TestBoundedPublicTransactionFiles(t *testing.T) {
	d := t.TempDir()
	p := filepath.Join(d, "transaction")
	for _, size := range []int{0, poolbridge.MaxTransactionBytes + 1} {
		os.WriteFile(p, make([]byte, size), 0600)
		if _, e := transactionFile(p); e == nil {
			t.Fatal("invalid length accepted")
		}
	}
	if err := os.WriteFile(p, make([]byte, poolbridge.MaxTransactionBytes), 0600); err != nil {
		t.Fatal(err)
	}
	if raw, err := transactionFile(p); err != nil || len(raw) != poolbridge.MaxTransactionBytes {
		t.Fatal("exact envelope size limit rejected")
	}
	os.WriteFile(p, []byte{1, 2, 3}, 0600)
	if b, e := transactionFile(p); e != nil || len(b) != 3 {
		t.Fatal("bounded input")
	}
	if _, e := transactionFile(d); e == nil {
		t.Fatal("directory accepted")
	}
}
