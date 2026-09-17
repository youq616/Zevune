//go:build pool_e2e && funded_e2e

package poolapp

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/poolbridge"
)

func startActiveFunded(t *testing.T, home string) (*fundedDriver, poolbridge.Hash) {
	t.Helper()
	exe := os.Getenv("ZEVUNE_FUNDED_SCENARIO")
	fi, err := os.Lstat(exe)
	if err != nil || !fi.Mode().IsRegular() || !filepath.IsAbs(exe) {
		t.Fatal("actual funded scenario executable required", err)
	}
	d := &fundedDriver{cmd: exec.Command(exe, home, "--active-segments-v1"), done: make(chan error, 1)}
	d.cmd.Env = []string{"RAYON_NUM_THREADS=2"}
	for _, env := range os.Environ() {
		name, _, ok := strings.Cut(env, "=")
		if ok && (strings.EqualFold(name, "SYSTEMROOT") || strings.EqualFold(name, "WINDIR") || strings.EqualFold(name, "TMP") || strings.EqualFold(name, "TEMP")) {
			d.cmd.Env = append(d.cmd.Env, env)
		}
	}
	d.cmd.Stderr = io.Discard
	d.in, err = d.cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	d.out, err = d.cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err = d.cmd.Start(); err != nil {
		t.Fatal(err)
	}
	go func() { d.done <- d.cmd.Wait() }()
	t.Cleanup(func() {
		_ = d.in.Close()
		select {
		case err := <-d.done:
			if err != nil {
				t.Errorf("active funded scenario exit: %v", err)
			}
		case <-time.After(10 * time.Second):
			_ = d.cmd.Process.Kill()
			<-d.done
			t.Error("active funded scenario stop timeout")
		}
		_ = d.out.Close()
	})
	ready := d.read(t)
	if len(ready) != 128 {
		t.Fatal("invalid active funded readiness")
	}
	var pin poolbridge.Hash
	copy(pin[:], ready[:32])
	d.state = fundedSummary(t, ready[32:])
	if d.state.Height != 0 || d.state.Commitments != 2 || d.state.Nullifiers != 0 || d.state.Fees != 0 {
		t.Fatal("unexpected active funded genesis")
	}
	return d, pin
}

func activeGrowthHash(height uint64) poolbridge.Hash {
	var n [8]byte
	binary.BigEndian.PutUint64(n[:], height)
	return sha256.Sum256(append([]byte("ZEVUNE-ACTIVE-GROWTH-NO-FUNDS\x00"), n[:]...))
}

func activeGrowthStatus(t *testing.T, ctx context.Context, c *poolbridge.Client) poolbridge.Summary {
	t.Helper()
	s, err := c.Status(ctx)
	if err != nil {
		t.Fatal("active worker status", err)
	}
	return s
}

func activeGrowthCapacity(t *testing.T, ctx context.Context, c *poolbridge.Client) poolbridge.ActiveStorage {
	t.Helper()
	s, err := c.ActiveCapacity(ctx)
	if err != nil {
		t.Fatal("active worker capacity", err)
	}
	return s
}

// While the worker owns the root lock, inspect segment bytes and genesis file
// metadata only: Windows rejects reads of the exclusively locked genesis file.
// The full header and complete physical history are checked after Close below.
// This checks non-mutation; the real worker still verifies authorization.
func activeGrowthDiskDigest(t *testing.T, path string) poolbridge.Hash {
	t.Helper()
	entries, err := os.ReadDir(path)
	if err != nil {
		t.Fatal(err)
	}
	h := sha256.New()
	for _, entry := range entries {
		file := filepath.Join(path, entry.Name())
		fi, err := os.Lstat(file)
		if err != nil || !fi.Mode().IsRegular() {
			t.Fatal("non-regular active journal entry", err)
		}
		_, _ = h.Write([]byte(entry.Name()))
		var n [8]byte
		binary.BigEndian.PutUint64(n[:], uint64(fi.Size()))
		_, _ = h.Write(n[:])
		if entry.Name() == "genesis" {
			binary.BigEndian.PutUint64(n[:], uint64(fi.ModTime().UnixNano()))
			_, _ = h.Write(n[:])
			continue
		}
		b, err := os.ReadFile(file)
		if err != nil || int64(len(b)) != fi.Size() {
			t.Fatal("active segment changed during byte inspection", err)
		}
		_, _ = h.Write(b)
	}
	var result poolbridge.Hash
	copy(result[:], h.Sum(nil))
	return result
}

func activeGrowthCommit(t *testing.T, ctx context.Context, c *poolbridge.Client, path string, previous poolbridge.Summary, txs [][]byte, boundary bool) poolbridge.Summary {
	t.Helper()
	height := previous.Height + 1
	hash := activeGrowthHash(height)
	var preview poolbridge.Summary
	var before poolbridge.ActiveStorage
	var disk poolbridge.Hash
	if boundary {
		before = activeGrowthCapacity(t, ctx, c)
		disk = activeGrowthDiskDigest(t, path)
		var candidates [][]byte
		if len(txs) == 1 {
			broken := bytes.Clone(txs[0])
			broken[len(broken)-1] ^= 1
			candidates = [][]byte{broken, txs[0], txs[0]}
		}
		selected, err := c.SelectProposal(ctx, height, poolbridge.MaxProposalBytes, candidates)
		if err != nil || len(selected) != len(txs) || (len(txs) == 1 && !bytes.Equal(selected[0], txs[0])) {
			t.Fatal("boundary selection did not preserve the valid payment exactly once", err)
		}
		preview, err = c.Preview(ctx, height, hash, selected)
		if err != nil || preview.Height != height {
			t.Fatal("boundary preview rejected", err)
		}
		if activeGrowthStatus(t, ctx, c) != previous || activeGrowthCapacity(t, ctx, c) != before || activeGrowthDiskDigest(t, path) != disk {
			t.Fatal("selection or preview changed committed state, segment bytes or genesis metadata")
		}
	}
	finalized, tag, err := c.Finalize(ctx, height, hash, txs)
	if err != nil || finalized.Height != height {
		t.Fatalf("real worker finalization at height %d: %v", height, err)
	}
	if boundary {
		if finalized != preview || activeGrowthStatus(t, ctx, c) != previous || activeGrowthCapacity(t, ctx, c) != before || activeGrowthDiskDigest(t, path) != disk {
			t.Fatal("boundary finalization differs from preview or persisted before commit")
		}
		if _, err = c.Commit(ctx, poolbridge.Hash{}); !errors.Is(err, poolbridge.ErrRejected) {
			t.Fatal("forged tag accepted at the height boundary", err)
		}
		if _, err = c.SelectProposal(ctx, height, 0, nil); err != nil {
			t.Fatal("selection failed while a real finalization was pending", err)
		}
		if activeGrowthStatus(t, ctx, c) != previous || activeGrowthCapacity(t, ctx, c) != before || activeGrowthDiskDigest(t, path) != disk {
			t.Fatal("rejected commit or pending selection changed committed state")
		}
	}
	committed, err := c.Commit(ctx, tag)
	if err != nil || committed != finalized {
		t.Fatalf("real worker commit at height %d: %v", height, err)
	}
	return committed
}

func activeGrowthRejectSpent(t *testing.T, ctx context.Context, c *poolbridge.Client, path string, state poolbridge.Summary, txs [][]byte) {
	t.Helper()
	before := activeGrowthCapacity(t, ctx, c)
	disk := activeGrowthDiskDigest(t, path)
	for _, tx := range txs {
		if err := c.Check(ctx, tx); !errors.Is(err, poolbridge.ErrRejected) {
			t.Fatal("spent payment admitted by the real worker", err)
		}
		if _, err := c.Preview(ctx, state.Height+1, activeGrowthHash(state.Height+1), [][]byte{tx}); !errors.Is(err, poolbridge.ErrRejected) {
			t.Fatal("spent payment preview accepted", err)
		}
		if _, _, err := c.Finalize(ctx, state.Height+1, activeGrowthHash(state.Height+1), [][]byte{tx}); !errors.Is(err, poolbridge.ErrRejected) {
			t.Fatal("spent payment finalization accepted", err)
		}
	}
	selected, err := c.SelectProposal(ctx, state.Height+1, poolbridge.MaxProposalBytes, txs)
	if err != nil || len(selected) != 0 {
		t.Fatal("spent payment selected", err)
	}
	if activeGrowthStatus(t, ctx, c) != state || activeGrowthCapacity(t, ctx, c) != before || activeGrowthDiskDigest(t, path) != disk {
		t.Fatal("duplicate rejection changed committed state, segment bytes or genesis metadata")
	}
}

// Count actual on-disk complete frames and their public metadata. This is
// independent physical accounting, not a replacement cryptographic verifier.
// Call only after the worker has exited and released its genesis root lock.
func activeGrowthCheckDisk(t *testing.T, path string, pin poolbridge.Hash, initial poolbridge.Summary, capacity poolbridge.ActiveStorage, payments map[uint64][]byte) poolbridge.Hash {
	t.Helper()
	header, err := os.ReadFile(filepath.Join(path, "genesis"))
	if err != nil || len(header) != 140 || string(header[:8]) != "ZVOPOL03" || !bytes.Equal(header[40:72], pin[:]) || binary.BigEndian.Uint32(header[72:76]) != 2 {
		t.Fatal("active header is not bound to the two-allocation 03 genesis", err)
	}
	entries, err := os.ReadDir(path)
	if err != nil || len(entries) != int(capacity.Segments)+1 {
		t.Fatal("active physical segment count differs from worker capacity", err)
	}
	logical := uint64(len(header))
	var records, paid, lastLength uint64
	previous := initial.AppHash
	for index := uint32(0); index < capacity.Segments; index++ {
		name := filepath.Join(path, fmt.Sprintf("%08d.journal", index))
		fi, err := os.Lstat(name)
		if err != nil || !fi.Mode().IsRegular() || fi.Size() < poolbridge.EmptyRecordBytes || fi.Size() > poolbridge.ActiveSegmentBytes {
			t.Fatal("invalid physical active segment", err)
		}
		b, err := os.ReadFile(name)
		if err != nil {
			t.Fatal(err)
		}
		logical += uint64(len(b))
		for offset := 0; offset < len(b); {
			if len(b)-offset < 4 {
				t.Fatal("active segment split a record prefix")
			}
			n := int(binary.BigEndian.Uint32(b[offset : offset+4]))
			if n < 114 || n > len(b)-offset-36 {
				t.Fatal("active segment split or corrupted a complete record")
			}
			frameSize := uint64(n + 36)
			if offset == 0 && index != 0 && lastLength+frameSize <= poolbridge.ActiveSegmentBytes {
				t.Fatal("active segment rotated before the next frame required rotation")
			}
			body := b[offset+4 : offset+4+n]
			checksum := sha256.Sum256(body)
			height := records + 1
			blockHash := activeGrowthHash(height)
			if string(body[:8]) != "ZVOBLK01" || binary.BigEndian.Uint64(body[8:16]) != height || !bytes.Equal(body[16:48], blockHash[:]) || !bytes.Equal(body[48:80], previous[:]) || !bytes.Equal(b[offset+4+n:offset+36+n], checksum[:]) {
				t.Fatal("actual journal records do not form the submitted public history")
			}
			count := binary.BigEndian.Uint16(body[112:114])
			if tx, ok := payments[height]; ok {
				if count != 1 || n != 118+len(tx) || binary.BigEndian.Uint32(body[114:118]) != uint32(len(tx)) || !bytes.Equal(body[118:], tx) {
					t.Fatal("actual paid record differs from the genuine submitted payment")
				}
				paid++
			} else if count != 0 || n != 114 {
				t.Fatal("nonempty record counted as an empty growth block")
			}
			copy(previous[:], body[80:112])
			records++
			offset += n + 36
		}
		lastLength = uint64(len(b))
	}
	if records != capacity.Summary.Height || paid != uint64(len(payments)) || logical != capacity.LogicalBytes || lastLength != uint64(capacity.TailBytes) || previous != capacity.Summary.AppHash {
		t.Fatal("physical history, logical bytes or final state differs from real worker capacity")
	}
	return sha256.Sum256(header)
}

func TestActiveSegmentedLedger100000BlocksBoundaryPaymentsAndRestart(t *testing.T) {
	// No shortened iteration count, direct state mutation, prebuilt journal or
	// acceptance double: every height crosses the actual worker IPC and fsync.
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Minute)
	defer cancel()
	root := t.TempDir()
	walletHome := filepath.Join(root, "wallets")
	if err := os.Mkdir(walletHome, 0700); err != nil {
		t.Fatal(err)
	}
	driver, pin := startActiveFunded(t, walletHome)
	manifest := filepath.Join(walletHome, "test-genesis.bin")
	genesis, err := os.ReadFile(manifest)
	if err != nil || len(genesis) != 312 || string(genesis[:8]) != "ZVTGEN03" || sha256.Sum256(genesis) != pin {
		t.Fatal("scenario did not explicitly create a pinned active genesis", err)
	}
	t.Setenv("ZEVUNE_TEST_GENESIS", manifest)
	t.Setenv("ZEVUNE_TEST_GENESIS_SHA256", hex.EncodeToString(pin[:]))
	path := filepath.Join(root, "active-ledger")
	o, err := options(path, true)
	if err != nil {
		t.Fatal(err)
	}
	o.StartupTimeout = 5 * time.Minute
	o.RequestTimeout = time.Minute
	start := func(create bool) *poolbridge.Client {
		t.Helper()
		o.Create = create
		c, err := poolbridge.Start(ctx, o)
		if err != nil {
			t.Fatal("actual active worker startup or complete replay", err)
		}
		t.Cleanup(func() { _ = c.Close() })
		if c.Profile() != poolbridge.ActiveSegmentsV1 {
			t.Fatal("pinned 03 genesis did not select the active IPC profile")
		}
		return c
	}
	c := start(true)
	if poolbridge.ActiveSegmentBytes != 1_048_576 || c.Profile().MaxHeight() != 1_000_000 || c.Profile().MaxJournalBytes() != 1_073_741_824 {
		t.Fatal("growth test did not use the fixed active-segments-v1 production policy")
	}
	initial := activeGrowthStatus(t, ctx, c)
	if initial != driver.state {
		t.Fatal("independent real scenario and worker disagree at genesis")
	}
	capacity := activeGrowthCapacity(t, ctx, c)
	if capacity.Summary != initial || capacity.LogicalBytes != 140 || capacity.Segments != 0 || capacity.TailBytes != 0 {
		t.Fatal("active genesis capacity is not exact")
	}
	if _, err = poolbridge.BlockBytes(10_001, activeGrowthHash(10_001), nil); !errors.Is(err, poolbridge.ErrBounds) {
		t.Fatal("legacy block encoder silently adopted the active height limit", err)
	}
	state := initial
	payments := make(map[uint64][]byte)
	logical := capacity.LogicalBytes
	started := time.Now()
	for height := uint64(1); height <= 100_000; height++ {
		if err = ctx.Err(); err != nil {
			t.Fatalf("growth deadline at height %d: %v", height, err)
		}
		var txs [][]byte
		if height == 9_999 || height == 10_001 {
			op, sender := byte(1), byte(0)
			if height == 10_001 {
				op, sender = 3, 1
			}
			tx := driver.call(t, op, nil)
			if len(tx) < 40 || string(tx[:8]) != "ZVORLAB2" || !bytes.Equal(tx[8:40], pin[:]) {
				t.Fatal("real boundary payment lost the active genesis signing domain")
			}
			if restored := driver.call(t, 4, []byte{sender}); !bytes.Equal(restored, tx) {
				t.Fatal("encrypted wallet recovery lost the exact boundary payment")
			}
			txs = [][]byte{tx}
			payments[height] = tx
		}
		boundary := height >= 9_999 && height <= 10_002
		state = activeGrowthCommit(t, ctx, c, path, state, txs, boundary)
		logical += poolbridge.EmptyRecordBytes
		for _, tx := range txs {
			logical += 4 + uint64(len(tx))
		}
		if height <= 10_002 {
			// Wallets scan at explicit checkpoints, not once per empty block.
			// The scenario still obtains every record via its normal prepare/commit.
			raw, err := c.BlockBytes(height, activeGrowthHash(height), txs)
			if err != nil {
				t.Fatal(err)
			}
			driver.state = fundedSummary(t, driver.call(t, 2, raw))
			if driver.state != state {
				t.Fatal("independent genuine replay differs at the active height boundary")
			}
		}
		if height == 9_999 || height == 10_001 {
			balances, fees := [3]uint64{39_000, 60_000, 0}, uint64(1_000)
			if height == 10_001 {
				balances, fees = [3]uint64{39_000, 19_000, 40_000}, 2_000
			}
			balancesFunded(t, driver.call(t, 0, nil), balances, fees)
			before := activeGrowthCapacity(t, ctx, c)
			if err = c.Close(); err != nil {
				t.Fatal(err)
			}
			c = start(false)
			if activeGrowthStatus(t, ctx, c) != state || activeGrowthCapacity(t, ctx, c) != before {
				t.Fatal("boundary restart changed the complete replay result")
			}
			restored := driver.call(t, 5, nil)
			balancesFunded(t, restored, balances, fees)
			if fundedSummary(t, restored[:96]) != state {
				t.Fatal("wallet full-history recovery differs from the restarted worker")
			}
			spent := [][]byte{payments[9_999]}
			if height == 10_001 {
				spent = append(spent, payments[10_001])
			}
			// Both payments remain within expiry at these checks.
			activeGrowthRejectSpent(t, ctx, c, path, state, spent)
		}
		if height == 10_002 {
			balancesFunded(t, driver.call(t, 6, nil), [3]uint64{39_000, 19_000, 40_000}, 2_000)
			t.Log("ACTIVE_BOUNDARY heights=9999,10000,10001,10002; selection, preview, finalize and commit agree; real A->B then recovered B->C, full wallet history, exact outbox recovery and pre-expiry duplicate rejection passed")
		}
		if height%25_000 == 0 {
			capacity = activeGrowthCapacity(t, ctx, c)
			if capacity.Summary != state || capacity.LogicalBytes != logical {
				t.Fatal("committed logical capacity differs from complete submitted frames")
			}
			t.Logf("ACTIVE_GROWTH_PROGRESS committed_blocks=%d paid_blocks=%d logical_bytes=%d segments=%d elapsed_ms=%d", height, len(payments), capacity.LogicalBytes, capacity.Segments, time.Since(started).Milliseconds())
		}
	}
	growthMS := time.Since(started).Milliseconds()
	capacity = activeGrowthCapacity(t, ctx, c)
	if capacity.Summary != state || state.Height != 100_000 || state.Fees != 2_000 || state.Commitments != 6 || state.Nullifiers != 4 || capacity.LogicalBytes != logical || capacity.Segments < 10 {
		t.Fatal("100000 real commits or repeated default-size rotations were not observed")
	}
	if err = c.Close(); err != nil {
		t.Fatal(err)
	}
	headerDigest := activeGrowthCheckDisk(t, path, pin, initial, capacity, payments)
	replayStart := time.Now()
	c = start(false)
	if activeGrowthStatus(t, ctx, c) != state || activeGrowthCapacity(t, ctx, c) != capacity {
		t.Fatal("100000-block full replay did not recover exact committed state and capacity")
	}
	replayMS := time.Since(replayStart).Milliseconds()
	state = activeGrowthCommit(t, ctx, c, path, state, nil, true)
	continued := activeGrowthCapacity(t, ctx, c)
	if state.Height != 100_001 || continued.Summary != state || continued.LogicalBytes != logical+poolbridge.EmptyRecordBytes {
		t.Fatal("normal commit after full 100000-block replay failed")
	}
	if err = c.Close(); err != nil {
		t.Fatal(err)
	}
	if activeGrowthCheckDisk(t, path, pin, initial, continued, payments) != headerDigest {
		t.Fatal("immutable genesis header changed across replay and continued commit")
	}
	t.Logf("ACTIVE_GROWTH_RESULT committed_blocks=100000 empty_blocks=99998 paid_blocks=2 logical_bytes=%d segments=%d segment_limit_bytes=%d growth_elapsed_ms=%d replay_elapsed_ms=%d continued_height=%d", capacity.LogicalBytes, capacity.Segments, poolbridge.ActiveSegmentBytes, growthMS, replayMS, state.Height)
	t.Log("growth counts are actual local worker commits, not four-node consensus heights; about 15 MB of records does not prove growth beyond 64 MiB or the commitment limit; timing includes durable writes and boundary proof/wallet checks, not payment latency or throughput")
}
