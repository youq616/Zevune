//go:build operator_e2e

package labnet

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// Real binaries, genuine Orchard payments and full replay, not a snapshot mock.
// Local commits in this test deliberately do NOT claim network consensus.
func TestRealJournalCopyRestoreAndAdversarialReplay(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Minute)
	defer cancel()
	root := t.TempDir()
	wallets := filepath.Join(root, "wallets")
	if err := os.Mkdir(wallets, 0700); err != nil {
		t.Fatal(err)
	}
	driver := launch(t, requiredExecutable(t, "ZEVUNE_FUNDED_SCENARIO"), wallets)
	ready := driver.frame(t)
	if len(ready) != 128 {
		t.Fatal("scenario hello")
	}
	var assetPin Hash
	copy(assetPin[:], ready[:32])
	initial := parseSummary(t, ready[32:])
	worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
	workerPin := executablePin(t, worker)
	home := filepath.Join(root, "network")
	configPin, err := Initialize(ctx, InitOptions{Home: home, Worker: worker, WorkerSHA256: workerPin,
		AssetManifest: filepath.Join(wallets, "test-genesis.bin"), AssetSHA256: assetPin})
	if err != nil {
		t.Fatal(err)
	}
	n, err := Load(filepath.Join(home, configName), configPin)
	if err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(home, "node0", "pool.journal")
	genesisBytes, err := os.ReadFile(source)
	if err != nil {
		t.Fatal(err)
	}
	base := StorageCopyOptions{Worker: worker, WorkerPin: workerPin, Source: source,
		Expected: StorageCheckpoint{Height: initial.Height, AppHash: initial.AppHash}}
	genesisCopy := base
	genesisCopy.Destination = filepath.Join(root, "genesis-copy.journal")
	if r, err := n.CopyStorageAtCheckpoint(ctx, genesisCopy); err != nil || r.Height != 0 || !r.ExpectedCheckpointMatched {
		t.Fatal("explicit genesis checkpoint copy failed", err)
	}
	owner, err := poolbridge.Start(ctx, n.workerOptions(worker, workerPin, source, false))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = owner.Close() })
	locked := base
	locked.Destination = filepath.Join(root, "must-not-copy-owned.journal")
	if r, err := n.CopyStorageAtCheckpoint(ctx, locked); err == nil || r != (StorageCopyReport{}) {
		t.Fatal("running journal was accepted for offline copy")
	}
	if _, err := os.Lstat(locked.Destination); !os.IsNotExist(err) {
		t.Fatal("locked source created output")
	}
	raw := driver.call(t, 1, nil)
	block, err := poolbridge.BlockBytes(1, Hash{7}, [][]byte{raw})
	if err != nil {
		t.Fatal(err)
	}
	_, tag, err := owner.Finalize(ctx, 1, Hash{7}, [][]byte{raw})
	if err != nil {
		t.Fatal(err)
	}
	current, err := owner.Commit(ctx, tag)
	if err != nil {
		t.Fatal(err)
	}
	if got := parseSummary(t, driver.call(t, 2, block)); got != current {
		t.Fatal("independent scenario state differs")
	}
	if err := owner.Close(); err != nil {
		t.Fatal(err)
	}
	base.Expected = StorageCheckpoint{Height: current.Height, AppHash: current.AppHash}
	sourceBytes, err := os.ReadFile(source)
	if err != nil {
		t.Fatal(err)
	}
	copyCommand := func(src, dst string) StorageCopyReport {
		t.Helper()
		args := []string{"storage-copy", "--no-real-funds", "--worker", worker, "--worker-sha256", HashText(workerPin),
			"--config", filepath.Join(home, configName), "--config-sha256", HashText(configPin),
			"--journal", src, "--output", dst, "--expected-height", strconv.FormatUint(current.Height, 10),
			"--expected-app-hash", HashText(current.AppHash)}
		var r StorageCopyReport
		if err := json.Unmarshal(operator(t, args, true), &r); err != nil {
			t.Fatal(err)
		}
		if r.Height != current.Height || r.AppHash != HashText(current.AppHash) || r.JournalSHA256 != HashText(sha256.Sum256(sourceBytes)) ||
			r.JournalBytes != uint64(len(sourceBytes)) || !r.ExpectedCheckpointMatched || !r.FileSynced ||
			r.DirectorySynced != (runtime.GOOS != "windows") || r.ConsensusVerified || r.RealFundsAllowed {
			t.Fatal("copy receipt mismatch or overclaim")
		}
		b, err := os.ReadFile(dst)
		if err != nil || !bytes.Equal(b, sourceBytes) {
			t.Fatal("published backup not byte-exact", err)
		}
		srcInfo, _ := os.Stat(src)
		dstInfo, _ := os.Stat(dst)
		if os.SameFile(srcInfo, dstInfo) {
			t.Fatal("backup aliases original storage")
		}
		return r
	}
	backup, restored := filepath.Join(root, "backup.journal"), filepath.Join(root, "restored.journal")
	copyCommand(source, backup)
	copyCommand(backup, restored)

	// Failed requests never overwrite existing user destinations or change source.
	for _, c := range []StorageCopyOptions{
		{Worker: worker, WorkerPin: workerPin, Source: source, Destination: backup, Expected: base.Expected},
		{Worker: worker, WorkerPin: workerPin, Source: source, Destination: source, Expected: base.Expected},
		{Worker: worker, WorkerPin: workerPin, Source: source, Destination: filepath.Join(root, "wrong-pin"), Expected: StorageCheckpoint{Height: 1, AppHash: Hash{99}}},
		{Worker: worker, WorkerPin: workerPin, Source: genesisCopy.Destination, Destination: filepath.Join(root, "rollback"), Expected: base.Expected},
	} {
		if r, err := n.CopyStorageAtCheckpoint(ctx, c); err == nil || r != (StorageCopyReport{}) {
			t.Fatal("bad copy request succeeded")
		}
	}
	if got, err := os.ReadFile(backup); err != nil || !bytes.Equal(got, sourceBytes) {
		t.Fatal("existing backup overwritten")
	}

	// Adversarial final gate: rewrite an actual payment's binding signature and
	// recompute both the record checksum and entire file digest. Real replay must
	// reject it; the caller's expected tip is not substituted with attacker data.
	bad := bytes.Clone(sourceBytes)
	headerLength := len(genesisBytes)
	recordLength := int(binary.BigEndian.Uint32(bad[headerLength : headerLength+4]))
	end := headerLength + 4 + recordLength
	if end+32 != len(bad) {
		t.Fatal("unexpected journal framing")
	}
	bad[end-1] ^= 1
	checksum := sha256.Sum256(bad[headerLength+4 : end])
	copy(bad[end:], checksum[:])
	staged := filepath.Join(root, "forged-stage.journal")
	if err := os.WriteFile(staged, bad, 0600); err != nil {
		t.Fatal(err)
	}
	stagedInfo, _ := journalInfo(staged)
	if r, err := n.verifyCopiedJournal(ctx, base, staged, stagedInfo, sha256.Sum256(bad)); err == nil || !reflect.DeepEqual(r, StorageReport{}) {
		t.Fatal("checksum-repaired invalid proof/signature passed staged replay")
	}
	// Correct cryptography under a different caller pin is also insufficient.
	validInfo, _ := journalInfo(backup)
	wrong := base
	wrong.Expected.AppHash[0] ^= 1
	if _, err := n.verifyCopiedJournal(ctx, wrong, backup, validInfo, sha256.Sum256(sourceBytes)); !errors.Is(err, ErrStorageCheckpoint) {
		t.Fatal("staged replay did not enforce independent checkpoint", err)
	}

	// Continue on the restored independent file without resetting signer state.
	// No validator signing files are involved in this local state-machine test.
	resumed, err := poolbridge.Start(ctx, n.workerOptions(worker, workerPin, restored, false))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = resumed.Close() })
	if err := resumed.Check(ctx, raw); !errors.Is(err, poolbridge.ErrRejected) {
		t.Fatal("restored journal forgot spent note", err)
	}
	raw2 := driver.call(t, 3, nil)
	block2, err := poolbridge.BlockBytes(2, Hash{8}, [][]byte{raw2})
	if err != nil {
		t.Fatal(err)
	}
	_, tag2, err := resumed.Finalize(ctx, 2, Hash{8}, [][]byte{raw2})
	if err != nil {
		t.Fatal(err)
	}
	next, err := resumed.Commit(ctx, tag2)
	if err != nil || next.Height != 2 || next.Fees != 2000 {
		t.Fatal("restored journal cannot continue real payment", err)
	}
	if got := parseSummary(t, driver.call(t, 2, block2)); got != next {
		t.Fatal("continued payment diverged from independent replay")
	}
	if err := resumed.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := n.InspectStorageAtCheckpoint(ctx, worker, workerPin, restored, StorageCheckpoint{Height: next.Height, AppHash: next.AppHash}); err != nil {
		t.Fatal("reopen after restored payment failed", err)
	}
	for _, path := range []string{source, backup} {
		if got, err := os.ReadFile(path); err != nil || !bytes.Equal(got, sourceBytes) {
			t.Fatal("continuing restored copy mutated its source/backup")
		}
	}
	leftovers, err := filepath.Glob(filepath.Join(root, ".zevune-copy-*"))
	if err != nil || len(leftovers) != 0 {
		t.Fatal("normal copy path leaked owned scratch files")
	}
}
