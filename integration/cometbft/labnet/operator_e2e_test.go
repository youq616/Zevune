//go:build operator_e2e

package labnet

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	ctypes "github.com/cometbft/cometbft/rpc/core/types"
	"github.com/cometbft/cometbft/types"
	"github.com/youq616/Zevune/internal/poolbridge"
)

func requiredExecutable(t *testing.T, name string) string {
	t.Helper()
	p := os.Getenv(name)
	f, e := os.Lstat(p)
	if e != nil || !filepath.IsAbs(p) || !f.Mode().IsRegular() {
		t.Fatalf("actual compiled %s is required", name)
	}
	return p
}
func executablePin(t *testing.T, p string) Hash {
	t.Helper()
	b, e := os.ReadFile(p)
	if e != nil {
		t.Fatal(e)
	}
	return sha256.Sum256(b)
}
func operator(t *testing.T, args []string, wantSuccess bool) []byte {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR"), args...)
	cmd.Stderr = io.Discard
	b, e := cmd.Output()
	if (e == nil) != wantSuccess || len(b) > 4096 {
		t.Fatalf("network command result mismatch: success=%v wanted=%v", e == nil, wantSuccess)
	}
	return b
}

type process struct {
	cmd     *exec.Cmd
	in      io.WriteCloser
	out     io.ReadCloser
	done    chan error
	stopped bool
}

func launch(t *testing.T, exe string, args ...string) *process {
	t.Helper()
	p := &process{cmd: exec.Command(exe, args...), done: make(chan error, 1)}
	p.cmd.Stderr = io.Discard
	var e error
	p.in, e = p.cmd.StdinPipe()
	if e != nil {
		t.Fatal(e)
	}
	p.out, e = p.cmd.StdoutPipe()
	if e != nil {
		t.Fatal(e)
	}
	if e = p.cmd.Start(); e != nil {
		t.Fatal(e)
	}
	go func() { p.done <- p.cmd.Wait() }()
	t.Cleanup(func() { p.stop(t) })
	return p
}
func (p *process) stop(t *testing.T) {
	t.Helper()
	if p.stopped {
		return
	}
	p.stopped = true
	_ = p.in.Close()
	select {
	case e := <-p.done:
		if e != nil {
			t.Error("child exited unsuccessfully")
		}
	case <-time.After(45 * time.Second):
		_ = p.cmd.Process.Kill()
		<-p.done
		t.Error("child did not stop")
	}
	_ = p.out.Close()
}
func (p *process) frame(t *testing.T) []byte {
	t.Helper()
	type readResult struct {
		b []byte
		e error
	}
	done := make(chan readResult, 1)
	go func() {
		var head [4]byte
		_, e := io.ReadFull(p.out, head[:])
		if e != nil {
			done <- readResult{nil, e}
			return
		}
		n := binary.BigEndian.Uint32(head[:])
		if n < 1 || n > 524288 {
			done <- readResult{nil, ErrBounds}
			return
		}
		b := make([]byte, n)
		_, e = io.ReadFull(p.out, b)
		done <- readResult{b, e}
	}()
	select {
	case r := <-done:
		if r.e != nil {
			t.Fatal("scenario read failed", r.e)
		}
		return r.b
	case <-time.After(90 * time.Second):
		_ = p.cmd.Process.Kill()
		t.Fatal("scenario timed out")
	}
	return nil
}
func (p *process) call(t *testing.T, op byte, data []byte) []byte {
	t.Helper()
	var header [4]byte
	binary.BigEndian.PutUint32(header[:], uint32(len(data)+1))
	request := append(header[:], op)
	request = append(request, data...)
	if _, e := io.Copy(p.in, bytes.NewReader(request)); e != nil {
		t.Fatal(e)
	}
	b := p.frame(t)
	if len(b) < 1 || b[0] != op {
		t.Fatal("scenario response mismatch")
	}
	return b[1:]
}
func parseSummary(t *testing.T, b []byte) poolbridge.Summary {
	t.Helper()
	if len(b) != 96 {
		t.Fatal("summary length")
	}
	var s poolbridge.Summary
	s.Height = binary.BigEndian.Uint64(b[:8])
	copy(s.AppHash[:], b[8:40])
	copy(s.Root[:], b[40:72])
	s.Commitments = binary.BigEndian.Uint64(b[72:80])
	s.Nullifiers = binary.BigEndian.Uint64(b[80:88])
	s.Fees = binary.BigEndian.Uint64(b[88:96])
	return s
}
func freePorts(t *testing.T) int {
	t.Helper()
	for base := 35000; base < 65000; base += 8 {
		listeners := []net.Listener{}
		for i := 0; i < 8; i++ {
			l, e := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", base+i))
			if e != nil {
				break
			}
			listeners = append(listeners, l)
		}
		for _, l := range listeners {
			l.Close()
		}
		if len(listeners) == 8 {
			return base
		}
	}
	t.Fatal("no local ports")
	return 0
}
func awaitHeight(t *testing.T, p *peer, want int64) {
	t.Helper()
	until := time.Now().Add(90 * time.Second)
	for time.Now().Before(until) {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		s, e := p.Status(ctx)
		cancel()
		if e == nil && s != nil && s.SyncInfo.LatestBlockHeight >= want {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("node did not reach height %d", want)
}
func findInclusion(t *testing.T, p *peer, raw []byte, start int64) int64 {
	t.Helper()
	until := time.Now().Add(60 * time.Second)
	ctx, cancel := context.WithDeadline(context.Background(), until)
	defer cancel()
	for time.Now().Before(until) {
		s, e := p.Status(ctx)
		if e != nil {
			t.Fatal(e)
		}
		for ; start <= s.SyncInfo.LatestBlockHeight; start++ {
			b, e := p.Block(ctx, &start)
			if e != nil {
				t.Fatal(e)
			}
			for _, tx := range b.Block.Data.Txs {
				if bytes.Equal(tx, raw) {
					return start
				}
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("signed payment not included")
	return 0
}
func replayScenario(t *testing.T, p *peer, driver *process, state poolbridge.Summary, target uint64) poolbridge.Summary {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	for h := state.Height + 1; h <= target; h++ {
		height := int64(h)
		b, e := p.Block(ctx, &height)
		if e != nil {
			t.Fatal(e)
		}
		txs := make([][]byte, len(b.Block.Data.Txs))
		for i, tx := range b.Block.Data.Txs {
			txs[i] = tx
		}
		var hash Hash
		copy(hash[:], b.BlockID.Hash)
		encoded, e := poolbridge.BlockBytes(h, hash, txs)
		if e != nil {
			t.Fatal(e)
		}
		state = parseSummary(t, driver.call(t, 2, encoded))
	}
	return state
}
func TestRealOperatorNonzeroPaymentsAndRestart(t *testing.T) {
	root := t.TempDir()
	walletHome := filepath.Join(root, "private-wallets")
	if e := os.Mkdir(walletHome, 0700); e != nil {
		t.Fatal(e)
	}
	driver := launch(t, requiredExecutable(t, "ZEVUNE_FUNDED_SCENARIO"), walletHome)
	ready := driver.frame(t)
	if len(ready) != 128 {
		t.Fatal("initial frame")
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
	if e := json.Unmarshal(operator(t, initArgs, true), &initialized); e != nil {
		t.Fatal(e)
	}
	config := filepath.Join(home, configName)
	pin, e := ParseHash(initialized.Pin)
	if e != nil {
		t.Fatal(e)
	}
	network, e := Load(config, pin)
	if e != nil {
		t.Fatal(e)
	}
	operator(t, initArgs, false) // never replace an existing network or signer state
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
		peers[i], e = newPeer(Endpoint(base, i))
		if e != nil {
			t.Fatal(e)
		}
		defer peers[i].close()
	}
	for _, p := range peers {
		awaitHeight(t, p, 3)
	}
	ref := filepath.Join(root, "reference.journal")
	syncArgs := append([]string{"sync"}, common...)
	syncArgs = append(syncArgs, "--endpoint", Endpoint(base, 0), "--journal", ref)
	doSync := func(create bool) SyncResult {
		a := append([]string(nil), syncArgs...)
		if create {
			a = append(a, "--create")
		}
		var result SyncResult
		if e := json.Unmarshal(operator(t, a, true), &result); e != nil {
			t.Fatal(e)
		}
		if result.Payments || result.Height == 0 {
			t.Fatal("invalid sync report")
		}
		return result
	}
	synced := doSync(true)
	state = replayScenario(t, peers[0], driver, state, synced.Height)
	if HashText(state.AppHash) != synced.AppHash {
		t.Fatal("independent replay mismatch")
	}
	submit := func(raw []byte, index int, success bool) {
		path := filepath.Join(root, fmt.Sprintf("payment-%x.tx", sha256.Sum256(raw)))
		if e := os.WriteFile(path, raw, 0600); e != nil {
			t.Fatal(e)
		}
		args := append([]string{"submit"}, common...)
		args = append(args, "--endpoint", Endpoint(base, index), "--journal", ref, "--tx", path)
		var out Submission
		if e := json.Unmarshal(operator(t, args, success), &out); e != nil {
			t.Fatal(e)
		}
		if out.Confirmed || (success && out.Status != "accepted_to_mempool_not_confirmed") {
			t.Fatal("incorrect finality status")
		}
	}
	first := driver.call(t, 1, nil)
	if restored := driver.call(t, 4, []byte{0}); !bytes.Equal(first, restored) {
		t.Fatal("outbox backup changed payment")
	}
	bad := bytes.Clone(first)
	bad[len(bad)-1] ^= 1
	submit(bad, 0, false)
	submit(first, 0, true)
	h := findInclusion(t, peers[0], first, 1)
	awaitHeight(t, peers[0], h+1)
	synced = doSync(false)
	state = replayScenario(t, peers[0], driver, state, synced.Height)
	if HashText(state.AppHash) != synced.AppHash {
		t.Fatal("first payment state mismatch")
	}
	nodes[3].stop(t)
	second := driver.call(t, 3, nil)
	if restored := driver.call(t, 4, []byte{1}); !bytes.Equal(second, restored) {
		t.Fatal("onward outbox changed")
	}
	submit(second, 1, true)
	h = findInclusion(t, peers[0], second, int64(state.Height)+1)
	awaitHeight(t, peers[0], h+1)
	start(3)
	for _, p := range peers {
		awaitHeight(t, p, h+1)
	}
	synced = doSync(false)
	state = replayScenario(t, peers[0], driver, state, synced.Height)
	if HashText(state.AppHash) != synced.AppHash {
		t.Fatal("second payment state mismatch")
	}
	driver.call(t, 6, nil)
	for _, p := range peers {
		s, e := network.header(context.Background(), p, int64(state.Height)+1)
		if e != nil || !bytes.Equal(s.Header.AppHash, state.AppHash[:]) {
			t.Fatal("signed cross-node state mismatch", e)
		}
	}
	for _, p := range nodes {
		p.stop(t)
	}
	highest := uint64(0)
	for i := 0; i < 4; i++ {
		store, e := poolbridge.Start(context.Background(), network.workerOptions(worker, workerPin, filepath.Join(home, fmt.Sprintf("node%d/pool.journal", i)), false))
		if e != nil {
			t.Fatal(e)
		}
		s, e := store.Status(context.Background())
		store.Close()
		if e != nil {
			t.Fatal(e)
		}
		if s.Height > highest {
			highest = s.Height
		}
	}
	for i := 0; i < 4; i++ {
		start(i)
	}
	for _, p := range peers {
		awaitHeight(t, p, int64(highest)+2)
	}
	synced = doSync(false)
	state = replayScenario(t, peers[0], driver, state, synced.Height)
	if HashText(state.AppHash) != synced.AppHash {
		t.Fatal("restored state mismatch")
	}
	driver.call(t, 5, nil)
	driver.call(t, 6, nil)
	submit(first, 0, false)
	submit(second, 1, false)
	t.Log("shipped init/run/sync/submit commands: real nonzero A->B->C, encrypted outbox backup, one-node outage, signed reference-state checks, full restart and duplicate rejection passed; local NO-FUNDS only")
}

// An adversarial test-only RPC source returns genuine quorum signatures over an
// incorrect post-state. Signature checks alone must not contaminate local disk.
type falseStatePeer struct {
	first *types.SignedHeader
	next  *types.SignedHeader
	block *types.Block
}

func (p *falseStatePeer) Status(context.Context) (*ctypes.ResultStatus, error) {
	s := &ctypes.ResultStatus{}
	s.NodeInfo.Network = p.first.ChainID
	s.SyncInfo.LatestBlockHeight = 2
	return s, nil
}
func (p *falseStatePeer) Block(context.Context, *int64) (*ctypes.ResultBlock, error) {
	return &ctypes.ResultBlock{Block: p.block, BlockID: p.first.Commit.BlockID}, nil
}
func (p *falseStatePeer) Commit(_ context.Context, h *int64) (*ctypes.ResultCommit, error) {
	s := p.first
	if *h == 2 {
		s = p.next
	}
	return &ctypes.ResultCommit{SignedHeader: *s, CanonicalCommit: true}, nil
}
func (p *falseStatePeer) BroadcastTxSync(context.Context, types.Tx) (*ctypes.ResultBroadcastTx, error) {
	return nil, errors.New("not used")
}
func TestQuorumSignedWrongPostStateNeverPersists(t *testing.T) {
	worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
	path := filepath.Join(t.TempDir(), "reference.journal")
	store, e := poolbridge.Start(context.Background(), poolbridge.Options{Executable: worker, ExpectedSHA256: executablePin(t, worker), Journal: path, Create: true})
	if e != nil {
		t.Fatal(e)
	}
	defer store.Close()
	initial, e := store.Status(context.Background())
	if e != nil {
		t.Fatal(e)
	}
	n, keys := signingNetwork(t)
	n.genesis.AppHash = bytes.Clone(initial.AppHash[:])
	b := types.MakeBlock(1, nil, &types.Commit{}, nil)
	header := headerTemplate(n, 1)
	b.Header.Version = header.Version
	b.Header.ChainID = header.ChainID
	b.Header.Time = header.Time
	b.Header.ValidatorsHash = header.ValidatorsHash
	b.Header.NextValidatorsHash = header.NextValidatorsHash
	b.Header.ConsensusHash = header.ConsensusHash
	b.Header.AppHash = header.AppHash
	b.Header.ProposerAddress = header.ProposerAddress
	parts, e := b.MakePartSet(types.BlockPartSizeBytes)
	if e != nil {
		t.Fatal(e)
	}
	first := signHeader(t, n, keys, &b.Header, parts.Header(), 4)
	nextHeader := headerTemplate(n, 2)
	nextHeader.LastBlockID = first.Commit.BlockID
	nextHeader.AppHash = bytes.Repeat([]byte{99}, 32)
	nextHeader.Time = b.Time.Add(time.Millisecond)
	next := signHeader(t, n, keys, nextHeader, parts.Header(), 4)
	remote := &falseStatePeer{first: first, next: next, block: b}
	before, e := os.ReadFile(path)
	if e != nil {
		t.Fatal(e)
	}
	_, e = n.synchronize(context.Background(), remote, store, 128)
	if !errors.Is(e, ErrCertificate) {
		t.Fatal("wrong post-state was not rejected", e)
	}
	after, e := os.ReadFile(path)
	if e != nil || !bytes.Equal(before, after) {
		t.Fatal("untrusted state contaminated journal")
	}
	status, e := store.Status(context.Background())
	if e != nil || status != initial {
		t.Fatal("untrusted state changed memory")
	}
}
