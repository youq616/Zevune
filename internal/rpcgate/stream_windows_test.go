package rpcgate

import (
	"os"
	"testing"
)

func TestWindowsSynchronousPipeFailsCapabilityCheck(t *testing.T) {
	r, w, err := os.Pipe() // deliberately synchronous CreatePipe, NOT gatetest.Pipe
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	defer w.Close()
	if _, err := OpenInput(r); err == nil {
		t.Fatal("synchronous stdin accepted")
	}
	if _, err := OpenOutput(w); err == nil {
		t.Fatal("synchronous stdout accepted")
	}
}
