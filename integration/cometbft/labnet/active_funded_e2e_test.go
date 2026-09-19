//go:build operator_e2e

package labnet

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/youq616/Zevune/integration/cometbft/poolapp"
	"github.com/youq616/Zevune/internal/poolbridge"
)

// Active ledgers contain only the public genesis and regular segment files.
// Read the complete directory after workers release their file locks, including
// on Windows; no lock file is ignored when checking that inspection is read-only.
func activeStorageDirectoryBytes(t *testing.T, path string) map[string][]byte {
	t.Helper()
	entries, err := os.ReadDir(path)
	if err != nil {
		t.Fatal(err)
	}
	result := make(map[string][]byte, len(entries))
	for _, entry := range entries {
		info, err := entry.Info()
		if err != nil || !info.Mode().IsRegular() {
			t.Fatal("active storage fixture contains a nonregular entry", err)
		}
		raw, err := os.ReadFile(filepath.Join(path, entry.Name()))
		if err != nil {
			t.Fatal(err)
		}
		result[entry.Name()] = raw
	}
	return result
}

func replayActiveScenario(t *testing.T, p *peer, driver *process, state poolbridge.Summary, target uint64) poolbridge.Summary {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	for h := state.Height + 1; h <= target; h++ {
		height := int64(h)
		b, err := p.Block(ctx, &height)
		if err != nil || b == nil || b.Block == nil {
			t.Fatal("active scenario block retrieval", err)
		}
		txs := make([][]byte, len(b.Block.Data.Txs))
		for i, tx := range b.Block.Data.Txs {
			txs[i] = tx
		}
		var hash Hash
		copy(hash[:], b.BlockID.Hash)
		encoded, err := poolbridge.ActiveSegmentsV1.BlockBytes(h, hash, txs)
		if err != nil {
			t.Fatal(err)
		}
		state = parseSummary(t, driver.call(t, 2, encoded))
	}
	return state
}

func activeInitChainVersionChecks(t *testing.T, n *Network, worker string, workerPin Hash, journal string) {
	t.Helper()
	ctx := context.Background()
	a, err := poolapp.Open(ctx, n.workerOptions(worker, workerPin, journal, true))
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	before, err := a.Info(ctx, &abci.RequestInfo{})
	if err != nil || before.AppVersion != poolapp.ActiveAppVersion || before.LastBlockHeight != 0 {
		t.Fatal("active application did not advertise its pinned version", err)
	}
	params := n.genesis.ConsensusParams.ToProto()
	request := &abci.RequestInitChain{
		ChainId: poolapp.ChainID, InitialHeight: 1, ConsensusParams: &params,
		AppStateBytes: bytes.Clone(n.genesis.AppState),
	}
	for _, validator := range n.genesis.Validators {
		request.Validators = append(request.Validators, abci.Ed25519ValidatorUpdate(validator.PubKey.Bytes(), validator.Power))
	}
	for _, version := range []uint64{0, poolapp.AppVersion, poolapp.ActiveAppVersion + 1} {
		request.ConsensusParams.Version.App = version
		if _, err := a.InitChain(ctx, request); err == nil {
			t.Fatal("active InitChain accepted the wrong application version")
		}
	}
	saved := request.ConsensusParams.Version
	request.ConsensusParams.Version = nil
	if _, err := a.InitChain(ctx, request); err == nil {
		t.Fatal("active InitChain accepted an absent application version")
	}
	request.ConsensusParams.Version = saved
	request.ConsensusParams.Version.App = poolapp.ActiveAppVersion
	initialized, err := a.InitChain(ctx, request)
	if err != nil || !bytes.Equal(initialized.AppHash, before.LastBlockAppHash) {
		t.Fatal("version rejection changed state or prevented valid initialization", err)
	}
}

// This is a low-height genuine four-node payment/restart scenario. The separate
// normal worker/Go growth test supplies the 100000-block evidence; this test
// does not call that worker throughput result four-node consensus throughput.
func TestActiveFundedFourNodePaymentRestart(t *testing.T) {
	root := t.TempDir()
	walletHome := filepath.Join(root, "private-wallets")
	if err := os.Mkdir(walletHome, 0700); err != nil {
		t.Fatal(err)
	}
	driver := launch(t, requiredExecutable(t, "ZEVUNE_FUNDED_SCENARIO"), walletHome, "--active-segments-v1")
	ready := driver.frame(t)
	if len(ready) != 128 {
		t.Fatal("active scenario initial frame")
	}
	var assetPin Hash
	copy(assetPin[:], ready[:32])
	state := parseSummary(t, ready[32:])
	worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
	workerPin := executablePin(t, worker)
	home := filepath.Join(root, "network")
	common := []string{"--no-real-funds", "--worker", worker, "--worker-sha256", HashText(workerPin)}
	initArgs := append([]string{"init"}, common...)
	initArgs = append(initArgs, "--home", home, "--genesis", filepath.Join(walletHome, "test-genesis.bin"), "--genesis-sha256", HashText(assetPin))
	var initialized struct {
		Pin string `json:"config_sha256"`
	}
	if err := json.Unmarshal(operator(t, initArgs, true), &initialized); err != nil {
		t.Fatal(err)
	}
	pin, err := ParseHash(initialized.Pin)
	if err != nil {
		t.Fatal(err)
	}
	config := filepath.Join(home, configName)
	network, err := Load(config, pin)
	if err != nil || network.Profile() != poolbridge.ActiveSegmentsV1 || network.config.Version != 2 || network.genesis.ConsensusParams.Version.App != poolapp.ActiveAppVersion {
		t.Fatal("active network configuration was not pinned", err)
	}
	activeInitChainVersionChecks(t, network, worker, workerPin, filepath.Join(root, "init-chain-ledger"))
	for i := 0; i < 4; i++ {
		info, err := os.Lstat(filepath.Join(home, fmt.Sprintf("node%d/pool.journal", i)))
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			t.Fatal("active network did not create directory ledgers", err)
		}
	}
	common = append(common, "--config", config, "--config-sha256", initialized.Pin)
	base := freePorts(t)
	nodes := make([]*process, 4)
	peers := make([]*peer, 4)
	start := func(index int) {
		args := append([]string{"run"}, common...)
		args = append(args, "--node", strconv.Itoa(index), "--base-port", strconv.Itoa(base), "--stop-on-stdin-eof")
		nodes[index] = launch(t, requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR"), args...)
	}
	for i := 0; i < 4; i++ {
		start(i)
		peers[i], err = newPeer(Endpoint(base, i))
		if err != nil {
			t.Fatal(err)
		}
		defer peers[i].close()
	}
	for _, p := range peers {
		awaitHeight(t, p, 3)
	}
	reference := filepath.Join(root, "reference-ledger")
	syncArgs := append([]string{"sync"}, common...)
	syncArgs = append(syncArgs, "--endpoint", Endpoint(base, 0), "--journal", reference)
	doSync := func(create bool) SyncResult {
		args := append([]string(nil), syncArgs...)
		if create {
			args = append(args, "--create")
		}
		var result SyncResult
		if err := json.Unmarshal(operator(t, args, true), &result); err != nil {
			t.Fatal(err)
		}
		if result.Payments || result.Height == 0 || result.Height >= result.ObservedSignedTip {
			t.Fatal("active synchronization overstated the signed tip")
		}
		state = replayActiveScenario(t, peers[0], driver, state, result.Height)
		if HashText(state.AppHash) != result.AppHash {
			t.Fatal("active reference and genuine wallet replay disagree")
		}
		return result
	}
	submit := func(raw []byte, index int, success bool) {
		path := filepath.Join(root, fmt.Sprintf("payment-%x.tx", sha256.Sum256(raw)))
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
		args := append([]string{"submit"}, common...)
		args = append(args, "--endpoint", Endpoint(base, index), "--journal", reference, "--tx", path)
		var receipt Submission
		if err := json.Unmarshal(operator(t, args, success), &receipt); err != nil {
			t.Fatal(err)
		}
		if receipt.Confirmed || (success && receipt.Status != "accepted_to_mempool_not_confirmed") || (!success && receipt.Status != "not_submitted") {
			t.Fatal("active payment receipt claims unsupported confirmation")
		}
	}
	doSync(true)
	first := driver.call(t, 1, nil)
	if len(first) < 40 || string(first[:8]) != "ZVORLAB2" || !bytes.Equal(first[8:40], assetPin[:]) {
		t.Fatal("active payment lost its independently pinned genesis signature domain")
	}
	submit(first, 0, true)
	h := findInclusion(t, peers[0], first, 1)
	awaitHeight(t, peers[0], h+1)
	doSync(false)
	if state.Commitments != 4 || state.Nullifiers != 2 || state.Fees != 1000 {
		t.Fatal("first genuine nonzero active payment accounting")
	}
	for _, node := range nodes {
		node.stop(t)
	}
	highest := uint64(0)
	for i := 0; i < 4; i++ {
		report, err := network.InspectStorage(context.Background(), worker, workerPin, filepath.Join(home, fmt.Sprintf("node%d/pool.journal", i)))
		if err != nil || report.StorageProfile != "active_segments_v1" || report.Segments == 0 || report.JournalBytes < 108+report.Height*150 || report.DiskSpace != nil || report.ConsensusVerified {
			t.Fatal("genuine offline active node capacity failed", err)
		}
		if report.Height > highest {
			highest = report.Height
		}
	}
	for i := 0; i < 4; i++ {
		start(i)
	}
	for _, p := range peers {
		awaitHeight(t, p, int64(highest)+2)
	}
	doSync(false)
	second := driver.call(t, 3, nil)
	submit(second, 1, true)
	h = findInclusion(t, peers[0], second, int64(state.Height)+1)
	for _, p := range peers {
		awaitHeight(t, p, h+1)
	}
	synced := doSync(false)
	if state.Commitments != 6 || state.Nullifiers != 4 || state.Fees != 2000 {
		t.Fatal("onward active payment after full restart accounting")
	}
	driver.call(t, 5, nil) // reopen the genuine wallet and active ledger history
	driver.call(t, 6, nil) // assert actual A/B/C balances and conservation
	for _, p := range peers {
		awaitHeight(t, p, int64(state.Height)+1)
		header, err := network.header(context.Background(), p, int64(state.Height)+1)
		if err != nil || !bytes.Equal(header.Header.AppHash, state.AppHash[:]) {
			t.Fatal("active signed cross-node post-state mismatch", err)
		}
	}
	storageArgs := append([]string{"storage"}, common...)
	storageArgs = append(storageArgs, "--journal", reference, "--expected-height", strconv.FormatUint(synced.Height, 10), "--expected-app-hash", synced.AppHash)
	storageBytes := activeStorageDirectoryBytes(t, reference)
	var report StorageReport
	out := operator(t, storageArgs, true)
	assertDefaultDiskFieldOmitted(t, out)
	if err := json.Unmarshal(out, &report); err != nil || !report.ExpectedCheckpointMatched || report.StorageProfile != "active_segments_v1" || report.JournalBytes == 0 || report.Segments == 0 || report.DiskSpace != nil {
		t.Fatal("active CLI exact-checkpoint capacity failed", err)
	}
	if !reflect.DeepEqual(activeStorageDirectoryBytes(t, reference), storageBytes) {
		t.Fatal("default active CLI inspection modified public ledger bytes")
	}
	for _, reserve := range []uint64{1, ^uint64(0)} {
		diskArgs := append(append([]string(nil), storageArgs...), "--disk-reserve-bytes", strconv.FormatUint(reserve, 10))
		var observed StorageReport
		if err := json.Unmarshal(operator(t, diskArgs, true), &observed); err != nil {
			t.Fatal(err)
		}
		assertRealDiskObservation(t, observed, reserve)
		observed.DiskSpace = nil
		if !reflect.DeepEqual(observed, report) || !reflect.DeepEqual(activeStorageDirectoryBytes(t, reference), storageBytes) {
			t.Fatal("optional OS observation changed active protocol accounting or ledger bytes")
		}
	}
	diskArgs := append(append([]string(nil), storageArgs...), "--disk-reserve-bytes", "1")
	wrongCheckpoint := append([]string(nil), diskArgs...)
	wrongHash, err := ParseHash(synced.AppHash)
	if err != nil {
		t.Fatal(err)
	}
	wrongHash[0] ^= 1
	for i := range wrongCheckpoint {
		if wrongCheckpoint[i] == "--expected-app-hash" {
			wrongCheckpoint[i+1] = HashText(wrongHash)
		}
	}
	if len(operator(t, wrongCheckpoint, false)) != 0 {
		t.Fatal("active disk-space inspection ignored the exact checkpoint")
	}
	lockCtx, cancelLock := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancelLock()
	owner, err := poolbridge.Start(lockCtx, network.workerOptions(worker, workerPin, reference, false))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = owner.Close() })
	if len(operator(t, diskArgs, false)) != 0 {
		t.Fatal("active disk-space inspection bypassed the actual worker owner lock")
	}
	if err := owner.Close(); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(activeStorageDirectoryBytes(t, reference), storageBytes) {
		t.Fatal("rejected active checkpoint or owner-lock inspection modified ledger bytes")
	}
	corrupted := filepath.Join(root, "corrupt-active-ledger")
	if err := os.Mkdir(corrupted, 0700); err != nil {
		t.Fatal(err)
	}
	if len(storageBytes["00000000.journal"]) == 0 {
		t.Fatal("active payment fixture has no first segment to corrupt")
	}
	for name, raw := range storageBytes {
		copyBytes := bytes.Clone(raw)
		if name == "00000000.journal" {
			copyBytes[len(copyBytes)-1] ^= 1
		}
		if err := os.WriteFile(filepath.Join(corrupted, name), copyBytes, 0600); err != nil {
			t.Fatal(err)
		}
	}
	corruptBytes := activeStorageDirectoryBytes(t, corrupted)
	corruptArgs := append([]string(nil), diskArgs...)
	for i := range corruptArgs {
		if corruptArgs[i] == "--journal" {
			corruptArgs[i+1] = corrupted
		}
	}
	if len(operator(t, corruptArgs, false)) != 0 {
		t.Fatal("active disk-space inspection bypassed genuine replay of a corrupt segment")
	}
	if !reflect.DeepEqual(activeStorageDirectoryBytes(t, corrupted), corruptBytes) ||
		!reflect.DeepEqual(activeStorageDirectoryBytes(t, reference), storageBytes) {
		t.Fatal("rejected active disk-space inspection repaired or changed public ledger bytes")
	}
	submit(first, 0, false)
	submit(second, 1, false)
	t.Log("active profile: shipped init/run/sync/submit/storage, InitChain version rejection, genuine nonzero A->B, all-four-node restart, B->C spend, wallet history reopen, signed next-header verification and duplicate rejection passed; low-height NO-FUNDS scenario")
	t.Log("active disk-space inspection: real OS sampling after genuine four-node payment/restart and onward payment, one-byte observation and MaxUint64 warning, unchanged protocol accounting and complete public directory bytes, exact-checkpoint/owner-lock/corrupt-segment rejection passed; no real disk-full or power-loss test")
}
