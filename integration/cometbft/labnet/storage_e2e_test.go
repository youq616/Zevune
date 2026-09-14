//go:build operator_e2e

package labnet

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// Actual compiled CLI, real Rust journal owner, and genuine Orchard payment.
// No RPC is needed: the command is explicitly not a finality/freshness check.
func TestRealOfflineStorageInspectionAndLock(t *testing.T) {
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
	expected := parseSummary(t, ready[32:])
	worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
	workerPin := executablePin(t, worker)
	common := []string{"--no-real-funds", "--worker", worker, "--worker-sha256", HashText(workerPin)}
	home := filepath.Join(root, "network")
	initArgs := append([]string{"init"}, common...)
	initArgs = append(initArgs, "--home", home, "--genesis", filepath.Join(wallets, "test-genesis.bin"), "--genesis-sha256", HashText(assetPin))
	var initialized struct {
		Pin string `json:"config_sha256"`
	}
	if err := json.Unmarshal(operator(t, initArgs, true), &initialized); err != nil {
		t.Fatal(err)
	}
	common = append(common, "--config", filepath.Join(home, configName), "--config-sha256", initialized.Pin)
	journal := filepath.Join(home, "node0", "pool.journal")
	args := append([]string{"storage"}, common...)
	args = append(args, "--journal", journal)
	inspect := func(want poolbridge.Summary) StorageReport {
		t.Helper()
		before, err := os.ReadFile(journal)
		if err != nil {
			t.Fatal(err)
		}
		var report StorageReport
		if err := json.Unmarshal(operator(t, args, true), &report); err != nil {
			t.Fatal(err)
		}
		after, err := os.ReadFile(journal)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(before, after) || report.Height != want.Height || report.AppHash != HashText(want.AppHash) ||
			report.Commitments != want.Commitments || report.JournalBytes != uint64(len(before)) ||
			report.ConsensusVerified || report.NetworkAccessed || report.RealFundsAllowed || !report.EmptyBlockFitsLimits {
			t.Fatal("offline inspection changed data or overstated its result")
		}
		return report
	}
	initial := inspect(expected)
	for _, flag := range []string{"--create", "--endpoint=http://127.0.0.1:30000", "--limit=1", "--node=0", "--tx=transaction"} {
		invalid := append(append([]string(nil), args...), flag)
		if len(operator(t, invalid, false)) != 0 {
			t.Fatal("unsupported flag produced output")
		}
	}
	missing := filepath.Join(root, "missing.journal")
	missingArgs := append([]string{"storage"}, common...)
	missingArgs = append(missingArgs, "--journal", missing)
	if len(operator(t, missingArgs, false)) != 0 {
		t.Fatal("missing journal reported")
	}
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Fatal("inspection created data")
	}
	// Submit a real payment directly to a local ledger, NOT consensus. The
	// report must remain consensus_verified:false even when replay succeeds.
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	owner, err := poolbridge.Start(ctx, poolbridge.Options{Executable: worker, ExpectedSHA256: workerPin,
		Journal: journal, TestGenesis: filepath.Join(wallets, "test-genesis.bin"), TestGenesisSHA256: assetPin})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = owner.Close() })
	if len(operator(t, args, false)) != 0 {
		t.Fatal("inspection bypassed journal owner lock")
	}
	raw := driver.call(t, 1, nil)
	_, tag, err := owner.Finalize(ctx, 1, Hash{7}, [][]byte{raw})
	if err != nil {
		t.Fatal(err)
	}
	expected, err = owner.Commit(ctx, tag)
	if err != nil {
		t.Fatal(err)
	}
	if err := owner.Close(); err != nil {
		t.Fatal(err)
	}
	after := inspect(expected)
	if after.JournalBytes-initial.JournalBytes != 150+4+uint64(len(raw)) || after.RecordsRemaining+1 != initial.RecordsRemaining {
		t.Fatal("real encoded record differs from capacity report")
	}
	// A second network with the same keys/notes but a changed deployment nonce
	// cannot inspect the first journal using its incompatible trusted policy.
	manifest, err := os.ReadFile(filepath.Join(wallets, "test-genesis.bin"))
	if err != nil {
		t.Fatal(err)
	}
	if len(manifest) < 82 || string(manifest[:8]) != "ZVTGEN02" {
		t.Fatal("expected LAB2")
	}
	manifest[50] ^= 0x80
	if bytes.Equal(manifest[50:82], make([]byte, 32)) {
		manifest[51] = 1
	}
	otherManifest := filepath.Join(root, "other-genesis.bin")
	if err := os.WriteFile(otherManifest, manifest, 0600); err != nil {
		t.Fatal(err)
	}
	otherHome := filepath.Join(root, "other-network")
	otherInit := append([]string{"init"}, common[:5]...)
	otherInit = append(otherInit, "--home", otherHome, "--genesis", otherManifest, "--genesis-sha256", HashText(sha256.Sum256(manifest)))
	var other struct {
		Pin string `json:"config_sha256"`
	}
	if err := json.Unmarshal(operator(t, otherInit, true), &other); err != nil {
		t.Fatal(err)
	}
	wrongDomain := append([]string{"storage"}, common[:5]...)
	wrongDomain = append(wrongDomain, "--config", filepath.Join(otherHome, configName), "--config-sha256", other.Pin, "--journal", journal)
	if len(operator(t, wrongDomain, false)) != 0 {
		t.Fatal("wrong genesis replay produced report")
	}
	// Do not mutate the pinned source: malformed journal copies are isolated.
	corrupted := filepath.Join(root, "corrupt.journal")
	data, err := os.ReadFile(journal)
	if err != nil {
		t.Fatal(err)
	}
	data[len(data)-1] ^= 1
	if err := os.WriteFile(corrupted, data, 0600); err != nil {
		t.Fatal(err)
	}
	corruptArgs := append([]string{"storage"}, common...)
	corruptArgs = append(corruptArgs, "--journal", corrupted)
	if len(operator(t, corruptArgs, false)) != 0 {
		t.Fatal("corrupt replay produced report")
	}
	unchanged, err := os.ReadFile(corrupted)
	if err != nil || !bytes.Equal(data, unchanged) {
		t.Fatal("inspection repaired or truncated corrupt data")
	}
	inspect(expected)
}
