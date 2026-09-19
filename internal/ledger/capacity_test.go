package ledger

import (
	"bytes"
	"errors"
	"fmt"
	"reflect"
	"testing"

	"github.com/youq616/Zevune/internal/protocol"
)

type capacitySnapshot struct {
	state  state
	bytes  []byte
	size   int64
	blocks int
	tail   [32]byte
}

func snapshotCapacity(t *testing.T, e *Engine) capacitySnapshot {
	t.Helper()
	return capacitySnapshot{e.s.clone(), diskBytes(t, e), e.journal.size, e.journal.blocks, e.journal.tail}
}

func (before capacitySnapshot) requireUnchanged(t *testing.T, e *Engine) {
	t.Helper()
	if !reflect.DeepEqual(before.state, e.s) || !bytes.Equal(before.bytes, diskBytes(t, e)) ||
		before.size != e.journal.size || before.blocks != e.journal.blocks || before.tail != e.journal.tail {
		t.Fatal("capacity refusal changed state, journal bytes or journal accounting")
	}
	if e.storageErr != nil || !e.StorageStatus().Available {
		t.Fatal("capacity refusal made storage unavailable")
	}
}

// These unit tests position the in-memory accounting at the existing limits.
// They exercise deterministic capacity checks, not a real disk-full condition.
func TestPersistentCapacityRejectionLeavesEngineUsable(t *testing.T) {
	for _, kind := range []string{"bytes", "blocks"} {
		t.Run(kind, func(t *testing.T) {
			e := openTestDisk(t, t.TempDir())
			if kind == "bytes" {
				e.journal.size = MaxJournalBytes
			} else {
				e.journal.blocks = maxJournalBlocks
			}
			before := snapshotCapacity(t, e)
			e.journal.write = func([]byte) (int, error) {
				t.Fatal("capacity refusal entered write")
				return 0, nil
			}
			e.journal.sync = func() error {
				t.Fatal("capacity refusal entered sync")
				return nil
			}
			if _, err := e.PreviewBlock(1, nil); !errors.Is(err, ErrJournalCapacity) {
				t.Fatal("preview accepted a journal that cannot hold an empty block", err)
			}
			before.requireUnchanged(t, e)
			if _, err := e.ApplyBlock(1, nil); !errors.Is(err, ErrJournalCapacity) {
				t.Fatal("apply did not report deterministic capacity refusal", err)
			}
			before.requireUnchanged(t, e)
			if err := e.CheckTx(transaction(e, "still-readable")); err != nil {
				t.Fatal("capacity refusal poisoned read-only transaction checks", err)
			}
		})
	}
}

func TestPersistentCapacityIncludesFullFraming(t *testing.T) {
	for _, count := range []int{0, 1, 2} {
		for _, missing := range []int64{0, 1} {
			t.Run(fmt.Sprintf("transactions-%d/missing-bytes-%d", count, missing), func(t *testing.T) {
				e := openTestDisk(t, t.TempDir())
				txs := make([]protocol.Envelope, count)
				// Outer length + height + transaction count + chained checksum.
				needed := int64(4 + 8 + 4 + 32)
				for i := range txs {
					txs[i] = transaction(e, fmt.Sprintf("framing-%d", i))
					raw, err := txs[i].MarshalBinary()
					if err != nil {
						t.Fatal(err)
					}
					needed += int64(4 + len(raw)) // Each transaction has its own length.
				}
				e.journal.size = MaxJournalBytes - needed + missing
				e.journal.blocks = maxJournalBlocks - 1
				before := snapshotCapacity(t, e)
				p, err := e.PreviewBlock(1, txs)
				if missing != 0 {
					if !errors.Is(err, ErrJournalCapacity) {
						t.Fatal("preview omitted framing bytes", err)
					}
					before.requireUnchanged(t, e)
					if _, err = e.ApplyBlock(1, txs); !errors.Is(err, ErrJournalCapacity) {
						t.Fatal("apply omitted framing bytes", err)
					}
					before.requireUnchanged(t, e)
					return
				}
				if err != nil {
					t.Fatal("exactly fitting candidate rejected", err)
				}
				before.requireUnchanged(t, e)
				got, err := e.CommitPreview(p, txs)
				if err != nil || got != p.Result {
					t.Fatal("exactly fitting commit rejected", err)
				}
				if e.journal.size != MaxJournalBytes || e.journal.blocks != maxJournalBlocks ||
					int64(len(diskBytes(t, e))-len(before.bytes)) != needed || !e.StorageStatus().Available {
					t.Fatal("committed framing or capacity accounting differs from preview")
				}
			})
		}
	}
}

func TestPersistentCapacityRefusalAllowsSmallerCandidate(t *testing.T) {
	e := openTestDisk(t, t.TempDir())
	small := []protocol.Envelope{transaction(e, "small")}
	large := []protocol.Envelope{small[0], transaction(e, "extra")}
	raw, err := small[0].MarshalBinary()
	if err != nil {
		t.Fatal(err)
	}
	e.journal.size = MaxJournalBytes - int64(4+8+4+4+len(raw)+32)
	before := snapshotCapacity(t, e)
	if _, err = e.PreviewBlock(1, large); !errors.Is(err, ErrJournalCapacity) {
		t.Fatal("oversized preview accepted", err)
	}
	before.requireUnchanged(t, e)
	if _, err = e.ApplyBlock(1, large); !errors.Is(err, ErrJournalCapacity) {
		t.Fatal("oversized apply accepted", err)
	}
	before.requireUnchanged(t, e)
	if err = e.CheckTx(small[0]); err != nil {
		t.Fatal("refusal reserved a nullifier or poisoned the engine", err)
	}
	p, err := e.PreviewBlock(1, small)
	if err != nil {
		t.Fatal("smaller candidate cannot be previewed after refusal", err)
	}
	before.requireUnchanged(t, e)
	if got, err := e.ApplyBlock(1, small); err != nil || got != p.Result {
		t.Fatal("smaller candidate cannot be applied after refusal", err)
	}
	if err := e.CheckTx(large[1]); err != nil {
		t.Fatal("refused candidate's extra transaction changed committed state", err)
	}
}

func TestCommitRechecksCapacityBeforeIO(t *testing.T) {
	for _, kind := range []string{"bytes", "blocks"} {
		for _, commit := range []string{"preview", "staged"} {
			t.Run(kind+"/"+commit, func(t *testing.T) {
				e := openTestDisk(t, t.TempDir())
				p, err := e.PreviewBlock(1, nil)
				if err != nil {
					t.Fatal(err)
				}
				e.mu.Lock()
				staged, owned, err := e.stageBlockLocked(1, nil)
				e.mu.Unlock()
				if err != nil {
					t.Fatal(err)
				}
				size, blocks := e.journal.size, e.journal.blocks
				if kind == "bytes" {
					e.journal.size = MaxJournalBytes - 47 // Empty records need 48 bytes.
				} else {
					e.journal.blocks = maxJournalBlocks
				}
				before := snapshotCapacity(t, e)
				if commit == "preview" {
					_, err = e.CommitPreview(p, nil)
				} else {
					// Reach appendBlock's independent recheck after successful staging.
					e.mu.Lock()
					_, err = e.commitStateLocked(1, owned, staged)
					e.mu.Unlock()
				}
				if !errors.Is(err, ErrJournalCapacity) {
					t.Fatal("commit failed to recheck capacity before I/O", err)
				}
				before.requireUnchanged(t, e)
				// Restore the test-only accounting injection, then use the public path.
				e.journal.size, e.journal.blocks = size, blocks
				if _, err = e.CommitPreview(p, nil); err != nil {
					t.Fatal("deterministic commit refusal poisoned the engine", err)
				}
			})
		}
	}
}
