package rpcgate

import (
	"os"
	"syscall"
	"testing"

	"github.com/youq616/Zevune/internal/rpcgate/gatetest"
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

func TestWindowsOverlappedWrongDirectionFailsBeforeIO(t *testing.T) {
	for _, read := range []bool{false, true} {
		r, w, err := gatetest.Pipe()
		if err != nil {
			t.Fatal(err)
		}
		// Keep the opposite endpoint open through the assertion: this is a
		// direction check on a live overlapped pipe, not a broken-pipe error.
		if read {
			in, err := OpenInput(w)
			if in != nil || err != ErrConfiguration {
				t.Errorf("write-only pipe accepted as Input: %v", err)
				if in != nil {
					in.Close()
				}
			}
		} else {
			out, err := OpenOutput(r)
			if out != nil || err != ErrConfiguration {
				t.Errorf("read-only pipe accepted as Output: %v", err)
				if out != nil {
					out.Close()
				}
			}
		}
		r.Close()
		w.Close()
	}
}

func TestWindowsAccessQueryFailsClosed(t *testing.T) {
	for _, read := range []bool{false, true} {
		if err := streamAccess(syscall.InvalidHandle, read); err != ErrConfiguration {
			t.Fatal("invalid handle query accepted", err)
		}
	}
}
