//go:build operator_e2e

package labnet

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"sync/atomic"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/poolbridge"
)

// Genuine Rust replay and Orchard authorization. The HTTP trap is intentionally
// NOT a consensus mock: it only counts forbidden early requests and always fails.
func TestRealReferenceCheckpointBeforeRPC(t *testing.T) {
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
	network, err := Load(filepath.Join(home, configName), configPin)
	if err != nil {
		t.Fatal(err)
	}
	journal := filepath.Join(home, "node0", "pool.journal")
	initialBytes, err := os.ReadFile(journal)
	if err != nil {
		t.Fatal(err)
	}
	prefix := filepath.Join(root, "old-prefix.journal")
	if err := os.WriteFile(prefix, initialBytes, 0600); err != nil {
		t.Fatal(err)
	}
	owner, err := poolbridge.Start(ctx, network.workerOptions(worker, workerPin, journal, false))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = owner.Close() })
	raw := driver.call(t, 1, nil)
	_, tag, err := owner.Finalize(ctx, 1, Hash{7}, [][]byte{raw})
	if err != nil {
		t.Fatal(err)
	}
	current, err := owner.Commit(ctx, tag)
	if err != nil {
		t.Fatal(err)
	}
	if err := owner.Close(); err != nil {
		t.Fatal(err)
	}
	committedBytes, err := os.ReadFile(journal)
	if err != nil {
		t.Fatal(err)
	}
	corrupt := filepath.Join(root, "corrupt.journal")
	badBytes := bytes.Clone(committedBytes)
	badBytes[len(badBytes)-1] ^= 1
	if err := os.WriteFile(corrupt, badBytes, 0600); err != nil {
		t.Fatal(err)
	}
	var calls, lockChecks atomic.Int64
	var probeLock, lockWasFree atomic.Bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		if probeLock.Load() {
			// The original owner must still hold the SAME journal lock when
			// RPC begins, not merely during a separate earlier inspection.
			lockChecks.Add(1)
			probeCtx, probeCancel := context.WithTimeout(context.Background(), 10*time.Second)
			otherOwner, err := poolbridge.Start(probeCtx, network.workerOptions(worker, workerPin, journal, false))
			if err == nil {
				lockWasFree.Store(true)
				_ = otherOwner.Close()
			}
			probeCancel()
		}
		http.Error(w, "test trap", http.StatusServiceUnavailable)
	}))
	defer server.Close()
	o := SyncOptions{Endpoint: server.URL, Worker: worker, WorkerSHA256: workerPin, Journal: journal, Limit: 3}
	base := StorageCheckpoint{Height: current.Height, AppHash: current.AppHash}
	zero := StorageCheckpoint{Height: initial.Height, AppHash: initial.AppHash}
	other := base
	other.AppHash[0] ^= 1
	unchanged := func(path string, want []byte) {
		t.Helper()
		data, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(data, want) {
			t.Fatal("checkpoint operation changed source bytes", err)
		}
	}
	for _, tc := range []struct {
		name     string
		path     string
		pin      StorageCheckpoint
		data     []byte
		mismatch bool
	}{
		{"old-valid-prefix", prefix, base, initialBytes, true},
		{"newer-than-exact-pin", journal, zero, committedBytes, true},
		{"same-height-wrong-state", journal, other, committedBytes, true},
		{"corrupt-correct-pin", corrupt, base, badBytes, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			request := o
			request.Journal = tc.path
			before := calls.Load()
			r, err := network.SynchronizeAtCheckpoint(ctx, request, tc.pin)
			if err == nil || r != (SyncResult{}) || (tc.mismatch && !errors.Is(err, ErrStorageCheckpoint)) {
				t.Fatal("sync accepted a wrong/corrupt starting state", err)
			}
			s, err := network.SubmitAtCheckpoint(ctx, request, raw, tc.pin)
			if err == nil || s.Status != "not_submitted" || s.Confirmed || s.BaseCheckpointMatched || (tc.mismatch && !errors.Is(err, ErrStorageCheckpoint)) {
				t.Fatal("submit accepted a wrong/corrupt starting state", err)
			}
			if calls.Load() != before {
				t.Fatal("RPC contacted before retained checkpoint/replay acceptance")
			}
			unchanged(tc.path, tc.data)
		})
	}
	// Passing a correct pin does not make this deliberately invalid RPC trusted.
	probeLock.Store(true)
	before := calls.Load()
	if r, err := network.SynchronizeAtCheckpoint(ctx, o, base); err == nil || r != (SyncResult{}) || calls.Load() == before {
		t.Fatal("matching checkpoint did not enter the original RPC verification path", err)
	}
	before = calls.Load()
	if s, err := network.SubmitAtCheckpoint(ctx, o, raw, base); err == nil || s.Status != "not_submitted" || !s.BaseCheckpointMatched || s.Confirmed || calls.Load() == before {
		t.Fatal("matching base bypassed peer checks or invented confirmation", err)
	}
	probeLock.Store(false)
	if lockChecks.Load() < 2 || lockWasFree.Load() {
		t.Fatal("journal lock was not held across base validation and RPC")
	}
	unchanged(journal, committedBytes)
	// An explicitly selected genesis checkpoint is checked and can match.
	request := o
	request.Journal = prefix
	before = calls.Load()
	if _, err := network.SynchronizeAtCheckpoint(ctx, request, zero); err == nil || errors.Is(err, ErrStorageCheckpoint) || calls.Load() == before {
		t.Fatal("height zero treated as an absent/invalid checkpoint", err)
	}
	// This control proves the old prefix itself genuinely replays; failure above
	// is due to the retained pin, not an unrelated inability to start the worker.
	before = calls.Load()
	if _, err := network.Synchronize(ctx, request); err == nil || calls.Load() == before {
		t.Fatal("legacy unpinned reference did not reach the rejecting peer", err)
	}
	unchanged(prefix, initialBytes)
	request.Journal = filepath.Join(root, "missing.journal")
	for _, create := range []bool{false, true} {
		request.Create = create
		before = calls.Load()
		if _, err := network.SynchronizeAtCheckpoint(ctx, request, base); err == nil || calls.Load() != before {
			t.Fatal("retained checkpoint allowed a missing/new journal", err)
		}
		if _, err := os.Stat(request.Journal); !os.IsNotExist(err) {
			t.Fatal("retained-checkpoint request created data")
		}
	}
	owner, err = poolbridge.Start(ctx, network.workerOptions(worker, workerPin, journal, false))
	if err != nil {
		t.Fatal(err)
	}
	before = calls.Load()
	if _, err := network.SynchronizeAtCheckpoint(ctx, o, base); err == nil || calls.Load() != before {
		t.Fatal("checkpoint gate bypassed journal owner's lock")
	}
	if err := owner.Close(); err != nil {
		t.Fatal(err)
	}
	unchanged(journal, committedBytes)
	// Full valid CLI configuration prevents missing unrelated arguments from
	// masking accidentally ignored optional/empty checkpoint flags.
	txfile := filepath.Join(root, "signed-payment.tx")
	if err := os.WriteFile(txfile, raw, 0600); err != nil {
		t.Fatal(err)
	}
	common := []string{"--no-real-funds", "--worker", worker, "--worker-sha256", HashText(workerPin),
		"--config", filepath.Join(home, configName), "--config-sha256", HashText(configPin), "--endpoint", server.URL, "--journal", journal}
	for _, command := range []string{"sync", "submit"} {
		args := append([]string{command}, common...)
		if command == "submit" {
			args = append(args, "--tx", txfile)
		}
		for _, flags := range [][]string{
			{"--expected-height", "", "--expected-app-hash", ""},
			{"--expected-height", ""}, {"--expected-app-hash", ""},
			{"--expected-height", strconv.FormatUint(other.Height, 10), "--expected-app-hash", HashText(other.AppHash)},
		} {
			before = calls.Load()
			output := operator(t, append(append([]string(nil), args...), flags...), false)
			if calls.Load() != before {
				t.Fatal("CLI contacted peer with invalid/mismatched checkpoint")
			}
			if len(output) != 0 {
				var receipt Submission
				if command != "submit" || json.Unmarshal(output, &receipt) != nil || receipt.Status != "not_submitted" || receipt.Confirmed || receipt.BaseCheckpointMatched {
					t.Fatal("CLI emitted checkpoint success on rejection")
				}
			}
			unchanged(journal, committedBytes)
		}
	}
}

// Real consensus success path is separate from the rejecting HTTP trap above.
// The original unpinned four-node A->B->C/restart test is left unchanged.
func TestRealPinnedReferencePayment(t *testing.T) {
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
	state := parseSummary(t, ready[32:])
	worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
	workerPin := executablePin(t, worker)
	home := filepath.Join(root, "network")
	configPin, err := Initialize(context.Background(), InitOptions{Home: home, Worker: worker, WorkerSHA256: workerPin,
		AssetManifest: filepath.Join(wallets, "test-genesis.bin"), AssetSHA256: assetPin})
	if err != nil {
		t.Fatal(err)
	}
	common := []string{"--no-real-funds", "--worker", worker, "--worker-sha256", HashText(workerPin),
		"--config", filepath.Join(home, configName), "--config-sha256", HashText(configPin)}
	ports := freePorts(t)
	for i := 0; i < 4; i++ {
		args := append(append([]string{"run"}, common...), "--node", strconv.Itoa(i), "--base-port", strconv.Itoa(ports), "--stop-on-stdin-eof")
		launch(t, requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR"), args...)
	}
	peer, err := newPeer(Endpoint(ports, 0))
	if err != nil {
		t.Fatal(err)
	}
	defer peer.close()
	awaitHeight(t, peer, 3)
	journal := filepath.Join(root, "reference.journal")
	syncArgs := append(append([]string{"sync"}, common...), "--endpoint", Endpoint(ports, 0), "--journal", journal)
	var synced SyncResult
	if err := json.Unmarshal(operator(t, append(append([]string(nil), syncArgs...), "--create"), true), &synced); err != nil || synced.BaseCheckpointMatched || synced.Payments {
		t.Fatal("unpinned creation reported a checked base", err)
	}
	pinArgs := func(height uint64, hash string) []string {
		return []string{"--expected-height", strconv.FormatUint(height, 10), "--expected-app-hash", hash}
	}
	// Pin derives from this test's preceding genuine signed synchronization.
	request := append(append([]string(nil), syncArgs...), pinArgs(synced.Height, synced.AppHash)...)
	if err := json.Unmarshal(operator(t, request, true), &synced); err != nil || !synced.BaseCheckpointMatched || synced.Payments {
		t.Fatal("valid base checkpoint prevented trusted sync", err)
	}
	state = replayScenario(t, peer, driver, state, synced.Height)
	if HashText(state.AppHash) != synced.AppHash {
		t.Fatal("independent scenario disagreed with reference")
	}
	raw := driver.call(t, 1, nil)
	txfile := filepath.Join(root, "payment.tx")
	if err := os.WriteFile(txfile, raw, 0600); err != nil {
		t.Fatal(err)
	}
	submitArgs := append(append([]string{"submit"}, common...), "--endpoint", Endpoint(ports, 0), "--journal", journal, "--tx", txfile)
	submitArgs = append(submitArgs, pinArgs(synced.Height, synced.AppHash)...)
	var receipt Submission
	if err := json.Unmarshal(operator(t, submitArgs, true), &receipt); err != nil || !receipt.BaseCheckpointMatched || receipt.Confirmed || receipt.Status != "accepted_to_mempool_not_confirmed" {
		t.Fatal("pinned submit failed or invented finality", err)
	}
	height := findInclusion(t, peer, raw, 1)
	awaitHeight(t, peer, height+1)
	// Submit may have saved newer blocks before broadcasting. Obtain its current
	// offline state for this test's subsequent call; this is not independent
	// checkpoint authentication and must not be described as such.
	inspectArgs := append(append([]string{"storage"}, common...), "--journal", journal)
	var base StorageReport
	if err := json.Unmarshal(operator(t, inspectArgs, true), &base); err != nil {
		t.Fatal(err)
	}
	request = append(append([]string(nil), syncArgs...), pinArgs(base.Height, base.AppHash)...)
	if err := json.Unmarshal(operator(t, request, true), &synced); err != nil || !synced.BaseCheckpointMatched {
		t.Fatal("post-payment pinned sync failed", err)
	}
	state = replayScenario(t, peer, driver, state, synced.Height)
	if HashText(state.AppHash) != synced.AppHash || state.Fees == 0 || state.Nullifiers == 0 {
		t.Fatal("real signed payment not replayed consistently")
	}
}
