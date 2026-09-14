package labnet

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestReferenceCheckpointRequestBoundsBeforeAccess(t *testing.T) {
	n := &Network{}
	path := filepath.Join(t.TempDir(), "absent.journal")
	valid := StorageCheckpoint{AppHash: Hash{1}}
	for _, c := range []StorageCheckpoint{{}, {Height: recordLimit + 1, AppHash: Hash{1}}} {
		o := SyncOptions{Journal: path, Limit: 1}
		if r, err := n.SynchronizeAtCheckpoint(context.Background(), o, c); !errors.Is(err, ErrBounds) || r != (SyncResult{}) {
			t.Fatal("invalid base checkpoint accepted for sync")
		}
		if r, err := n.SubmitAtCheckpoint(context.Background(), o, []byte{1}, c); !errors.Is(err, ErrBounds) || r.BaseCheckpointMatched || r.Status != "not_submitted" || r.Confirmed {
			t.Fatal("invalid base checkpoint accepted for submit")
		}
	}
	o := SyncOptions{Journal: path, Limit: 1, Create: true}
	if _, err := n.SynchronizeAtCheckpoint(context.Background(), o, valid); !errors.Is(err, ErrBounds) {
		t.Fatal("new journal accepted with retained starting checkpoint")
	}
	if _, err := n.SubmitAtCheckpoint(context.Background(), o, []byte{1}, valid); !errors.Is(err, ErrBounds) {
		t.Fatal("submit accepted journal creation")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("invalid request created journal")
	}
	// Existing explicit creation remains legal without a retained checkpoint.
	if err := validateReferenceCheckpoint(o, nil); err != nil {
		t.Fatal(err)
	}
	o.Create = false
	if err := validateReferenceCheckpoint(o, &valid); err != nil {
		t.Fatal("explicit height-zero checkpoint rejected", err)
	}
}

func TestReferenceCheckpointMissingContextAndNetwork(t *testing.T) {
	valid := StorageCheckpoint{AppHash: Hash{1}}
	o := SyncOptions{Limit: 1}
	var n *Network
	if _, err := n.SynchronizeAtCheckpoint(context.Background(), o, valid); !errors.Is(err, ErrBounds) {
		t.Fatal("nil network accepted")
	}
	n = &Network{}
	if _, err := n.SynchronizeAtCheckpoint(nil, o, valid); !errors.Is(err, ErrBounds) {
		t.Fatal("nil context accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := n.SubmitAtCheckpoint(ctx, o, []byte{1}, valid); !errors.Is(err, ErrBounds) {
		t.Fatal("cancelled request accepted")
	}
}

func TestUnpinnedResultsNeverClaimRetainedCheckpoint(t *testing.T) {
	for _, result := range []any{SyncResult{}, Submission{Status: "not_submitted"}} {
		raw, err := json.Marshal(result)
		if err != nil || !strings.Contains(string(raw), `"base_checkpoint_matched":false`) {
			t.Fatal("unpinned result omitted explicit base-check state")
		}
	}
}
