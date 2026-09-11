//go:build pool_e2e

package poolapp

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"math/rand/v2"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	cfg "github.com/cometbft/cometbft/config"
	"github.com/cometbft/cometbft/libs/log"
	"github.com/cometbft/cometbft/node"
	"github.com/cometbft/cometbft/p2p"
	"github.com/cometbft/cometbft/privval"
	"github.com/cometbft/cometbft/proxy"
	rpc "github.com/cometbft/cometbft/rpc/client/http"
	"github.com/cometbft/cometbft/types"
	"github.com/youq616/Zevune/internal/poolbridge"
)

func options(path string, create bool) (poolbridge.Options, error) {
	worker := os.Getenv("ZEVUNE_POOL_WORKER")
	b, e := os.ReadFile(worker)
	if e != nil {
		return poolbridge.Options{}, e
	}
	return poolbridge.Options{Executable: worker, ExpectedSHA256: sha256.Sum256(b), Journal: path, Create: create, StartupTimeout: 90 * time.Second}, nil
}
func fixture(t *testing.T) []byte {
	t.Helper()
	b, e := os.ReadFile(os.Getenv("ZEVUNE_POOL_FIXTURE"))
	if e != nil || len(b) == 0 {
		t.Fatal("real zero-value fixture required", e)
	}
	return b
}
func open(t *testing.T, path string, create bool) *Application {
	t.Helper()
	o, e := options(path, create)
	if e != nil {
		t.Fatal(e)
	}
	a, e := Open(context.Background(), o)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { _ = a.Close() })
	return a
}
func info(t *testing.T, a *Application) *abci.ResponseInfo {
	t.Helper()
	r, e := a.Info(context.Background(), &abci.RequestInfo{})
	if e != nil {
		t.Fatal(e)
	}
	return r
}

// All calls below cross a real OS process boundary into the locked Rust store.
func TestRealFinalizationCommitAndRestart(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "pool.journal")
	tx := fixture(t)
	a := open(t, path, true)
	initial := info(t, a)
	bad := bytes.Clone(tx)
	bad[len(bad)-1] ^= 1
	for _, raw := range [][]byte{nil, bad} {
		r, e := a.CheckTx(ctx, &abci.RequestCheckTx{Tx: raw})
		if e != nil || r.Code == 0 {
			t.Fatal("invalid authorization accepted", e)
		}
	}
	r, e := a.CheckTx(ctx, &abci.RequestCheckTx{Tx: tx})
	if e != nil || r.Code != 0 {
		t.Fatal("genuine proof rejected", e)
	}
	if _, e = a.Commit(ctx, &abci.RequestCommit{}); e == nil {
		t.Fatal("commit without finalization")
	}
	hash := sha256.Sum256([]byte("real-pool-finalization-test"))
	request := &abci.RequestFinalizeBlock{Height: 1, Hash: hash[:], Txs: [][]byte{tx}}
	before, e := os.Stat(path)
	if e != nil {
		t.Fatal(e)
	}
	result, e := a.FinalizeBlock(ctx, request)
	if e != nil || len(result.TxResults) != 1 || result.TxResults[0].Code != 0 {
		t.Fatal(e)
	}
	repeated, e := a.FinalizeBlock(ctx, request)
	if e != nil || !bytes.Equal(repeated.AppHash, result.AppHash) {
		t.Fatal("idempotent finalization", e)
	}
	altered := *request
	altered.Txs = [][]byte{bad}
	if _, e = a.FinalizeBlock(ctx, &altered); e == nil {
		t.Fatal("same hash different bytes accepted")
	}
	after, e := os.Stat(path)
	if e != nil || after.Size() != before.Size() {
		t.Fatal("finalize persisted", e)
	}
	if s := info(t, a); s.LastBlockHeight != 0 || !bytes.Equal(s.LastBlockAppHash, initial.LastBlockAppHash) {
		t.Fatal("Info exposed uncommitted state")
	}
	// Kill the real state worker with a prepared block: reopening must show the
	// old state, then an identical finalization can be safely replayed by consensus.
	if e = a.Close(); e != nil {
		t.Fatal(e)
	}
	a = open(t, path, false)
	if info(t, a).LastBlockHeight != 0 {
		t.Fatal("uncommitted state survived")
	}
	final, e := a.FinalizeBlock(ctx, request)
	if e != nil || !bytes.Equal(final.AppHash, result.AppHash) {
		t.Fatal("nondeterministic replay", e)
	}
	if _, e = a.Commit(ctx, &abci.RequestCommit{}); e != nil {
		t.Fatal(e)
	}
	if s := info(t, a); s.LastBlockHeight != 1 || !bytes.Equal(s.LastBlockAppHash, result.AppHash) {
		t.Fatal("commit mismatch")
	}
	if _, e = a.Commit(ctx, &abci.RequestCommit{}); e == nil {
		t.Fatal("duplicate commit accepted")
	}
	if e = a.Close(); e != nil {
		t.Fatal(e)
	}
	a = open(t, path, false)
	if s := info(t, a); s.LastBlockHeight != 1 || !bytes.Equal(s.LastBlockAppHash, result.AppHash) {
		t.Fatal("durable restart mismatch")
	}
	r, e = a.CheckTx(ctx, &abci.RequestCheckTx{Tx: tx})
	if e != nil || r.Code == 0 {
		t.Fatal("replay accepted", e)
	}
	p, e := a.ProcessProposal(ctx, &abci.RequestProcessProposal{Height: 2, Hash: hash[:], Txs: [][]byte{tx}})
	if e != nil || p.Status != abci.ResponseProcessProposal_REJECT {
		t.Fatal("spent transaction proposal accepted", e)
	}
	if e = a.Close(); e != nil {
		t.Fatal(e)
	}
	// Reopening a missing journal must fail; do not silently recreate genesis.
	o, e := options(filepath.Join(t.TempDir(), "missing.journal"), false)
	if e != nil {
		t.Fatal(e)
	}
	if c, e := Open(ctx, o); e == nil {
		_ = c.Close()
		t.Fatal("missing state recreated")
	}
	t.Log("real proof -> Finalize without persistence -> worker restart -> replay -> Commit -> durable restart -> duplicate rejected")
}

type child struct {
	cmd     *exec.Cmd
	in      io.WriteCloser
	done    chan error
	output  bytes.Buffer
	stopped bool
}

func spawn(t *testing.T, home string, i, base int) *child {
	t.Helper()
	c := &child{done: make(chan error, 1)}
	c.cmd = exec.Command(os.Args[0], "-test.run=^TestPoolNodeHelper$")
	c.cmd.Env = append(os.Environ(), "ZEVUNE_POOL_NODE="+home, "ZEVUNE_POOL_INDEX="+strconv.Itoa(i), "ZEVUNE_POOL_PORT="+strconv.Itoa(base))
	c.cmd.Stdout = &c.output
	c.cmd.Stderr = &c.output
	var e error
	c.in, e = c.cmd.StdinPipe()
	if e != nil {
		t.Fatal(e)
	}
	if e = c.cmd.Start(); e != nil {
		t.Fatal(e)
	}
	go func() { c.done <- c.cmd.Wait() }()
	t.Cleanup(func() { stop(t, c) })
	return c
}
func stop(t *testing.T, c *child) {
	t.Helper()
	if c == nil || c.stopped {
		return
	}
	c.stopped = true
	_ = c.in.Close()
	select {
	case e := <-c.done:
		if e != nil {
			t.Errorf("node exit: %v %s", e, c.output.String())
		}
	case <-time.After(30 * time.Second):
		_ = c.cmd.Process.Kill()
		<-c.done
		t.Error("node stop timed out")
	}
}
func freePorts(t *testing.T) int {
	t.Helper()
	for k := 0; k < 50; k++ {
		base := 30000 + 8*rand.IntN(3000)
		ls := []net.Listener{}
		for i := 0; i < 8; i++ {
			l, e := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", base+i))
			if e != nil {
				break
			}
			ls = append(ls, l)
		}
		for _, l := range ls {
			_ = l.Close()
		}
		if len(ls) == 8 {
			return base
		}
	}
	t.Fatal("no free ports")
	return 0
}
func height(c *rpc.HTTP) int64 {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	r, e := c.Status(ctx)
	if e != nil {
		return -1
	}
	return r.SyncInfo.LatestBlockHeight
}
func wait(t *testing.T, c *rpc.HTTP, h int64) {
	t.Helper()
	deadline := time.Now().Add(90 * time.Second)
	for time.Now().Before(deadline) {
		if height(c) >= h {
			return
		}
		time.Sleep(150 * time.Millisecond)
	}
	t.Fatalf("height did not reach %d (got %d)", h, height(c))
}
func setup(t *testing.T, home string) *types.GenesisDoc {
	t.Helper()
	g := &types.GenesisDoc{GenesisTime: time.Now().UTC(), ChainID: ChainID, InitialHeight: 1, ConsensusParams: types.DefaultConsensusParams()}
	g.ConsensusParams.Version.App = AppVersion
	g.ConsensusParams.Block.MaxBytes = 512 * 1024
	g.ConsensusParams.Evidence.MaxBytes = 64 * 1024
	g.ConsensusParams.Validator.PubKeyTypes = []string{"ed25519"}
	for i := 0; i < 4; i++ {
		c := cfg.DefaultConfig().SetRoot(filepath.Join(home, fmt.Sprintf("node%d", i)))
		for _, d := range []string{"config", "data"} {
			if e := os.MkdirAll(filepath.Join(c.RootDir, d), 0700); e != nil {
				t.Fatal(e)
			}
		}
		pv := privval.GenFilePV(c.PrivValidatorKeyFile(), c.PrivValidatorStateFile())
		pv.Save()
		pub, e := pv.GetPubKey()
		if e != nil {
			t.Fatal(e)
		}
		g.Validators = append(g.Validators, types.GenesisValidator{Address: pub.Address(), PubKey: pub, Power: 10, Name: fmt.Sprintf("test-%d", i)})
		if _, e = p2p.LoadOrGenNodeKey(c.NodeKeyFile()); e != nil {
			t.Fatal(e)
		}
		a := open(t, filepath.Join(c.RootDir, "pool.journal"), true)
		if e = a.Close(); e != nil {
			t.Fatal(e)
		}
	}
	if e := g.ValidateAndComplete(); e != nil {
		t.Fatal(e)
	}
	for i := 0; i < 4; i++ {
		c := cfg.DefaultConfig().SetRoot(filepath.Join(home, fmt.Sprintf("node%d", i)))
		if e := g.SaveAs(c.GenesisFile()); e != nil {
			t.Fatal(e)
		}
	}
	return g
}

// No executable test verifier or issuance shortcut. Each child starts a real
// consensus node and a separate Rust state process against an empty genesis.
func TestPoolNodeHelper(t *testing.T) {
	home := os.Getenv("ZEVUNE_POOL_NODE")
	if home == "" {
		return
	}
	index, e := strconv.Atoi(os.Getenv("ZEVUNE_POOL_INDEX"))
	if e != nil || index < 0 || index >= 4 {
		os.Exit(21)
	}
	base, e := strconv.Atoi(os.Getenv("ZEVUNE_POOL_PORT"))
	if e != nil {
		os.Exit(22)
	}
	c := cfg.DefaultConfig().SetRoot(filepath.Join(home, fmt.Sprintf("node%d", index)))
	c.Moniker = fmt.Sprintf("pool-test-%d", index)
	c.RPC.ListenAddress = fmt.Sprintf("tcp://127.0.0.1:%d", base+index*2)
	c.RPC.GRPCListenAddress = ""
	c.RPC.Unsafe = false
	c.RPC.CORSAllowedOrigins = nil
	c.RPC.MaxBodyBytes = 512 * 1024
	c.RPC.MaxOpenConnections = 32
	c.RPC.PprofListenAddress = ""
	c.P2P.ListenAddress = fmt.Sprintf("tcp://127.0.0.1:%d", base+index*2+1)
	c.P2P.ExternalAddress = ""
	c.P2P.AddrBookStrict = false
	c.P2P.AllowDuplicateIP = true
	c.P2P.PexReactor = false
	c.P2P.Seeds = ""
	c.P2P.PersistentPeersMaxDialPeriod = time.Second
	peers := []string{}
	for i := 0; i < 4; i++ {
		if i == index {
			continue
		}
		other := cfg.DefaultConfig().SetRoot(filepath.Join(home, fmt.Sprintf("node%d", i)))
		key, e := p2p.LoadNodeKey(other.NodeKeyFile())
		if e != nil {
			os.Exit(23)
		}
		peers = append(peers, fmt.Sprintf("%s@127.0.0.1:%d", key.ID(), base+i*2+1))
	}
	c.P2P.PersistentPeers = strings.Join(peers, ",")
	c.Consensus.TimeoutCommit = 400 * time.Millisecond
	c.Consensus.TimeoutPropose = 2 * time.Second
	c.Consensus.CreateEmptyBlocks = true
	c.TxIndex.Indexer = "null"
	c.StateSync.Enable = false
	c.Instrumentation.Prometheus = false
	if c.ValidateBasic() != nil {
		os.Exit(24)
	}
	for _, path := range []string{c.PrivValidatorKeyFile(), c.PrivValidatorStateFile(), c.NodeKeyFile(), filepath.Join(c.RootDir, "pool.journal")} {
		fi, e := os.Lstat(path)
		if e != nil || !fi.Mode().IsRegular() {
			os.Exit(25)
		}
	}
	o, e := options(filepath.Join(c.RootDir, "pool.journal"), false)
	if e != nil {
		os.Exit(26)
	}
	a, e := Open(context.Background(), o)
	if e != nil {
		os.Exit(27)
	}
	pv := privval.LoadFilePV(c.PrivValidatorKeyFile(), c.PrivValidatorStateFile())
	nk, e := p2p.LoadNodeKey(c.NodeKeyFile())
	if e != nil {
		_ = a.Close()
		os.Exit(28)
	}
	n, e := node.NewNode(c, pv, nk, proxy.NewLocalClientCreator(a), node.DefaultGenesisDocProviderFunc(c), cfg.DefaultDBProvider, node.DefaultMetricsProvider(c.Instrumentation), log.NewNopLogger())
	if e != nil {
		_ = a.Close()
		fmt.Fprintln(os.Stderr, e)
		os.Exit(29)
	}
	if e = n.Start(); e != nil {
		_ = a.Close()
		fmt.Fprintln(os.Stderr, e)
		os.Exit(30)
	}
	_, _ = io.Copy(io.Discard, os.Stdin)
	if n.IsRunning() {
		_ = n.Stop()
		n.Wait()
	}
	if a.Close() != nil {
		os.Exit(31)
	}
	os.Exit(0)
}
func TestRealPoolFourProcessConsensus(t *testing.T) {
	tx := fixture(t)
	home := t.TempDir()
	base := freePorts(t)
	gen := setup(t, home)
	nodes := make([]*child, 4)
	clients := make([]*rpc.HTTP, 4)
	for i := range nodes {
		nodes[i] = spawn(t, home, i, base)
		c, e := rpc.New(fmt.Sprintf("http://127.0.0.1:%d", base+2*i), "/websocket")
		if e != nil {
			t.Fatal(e)
		}
		clients[i] = c
	}
	for _, c := range clients {
		wait(t, c, 3)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	bad := bytes.Clone(tx)
	bad[len(bad)-1] ^= 1
	rejected, e := clients[0].BroadcastTxSync(ctx, types.Tx(bad))
	if e != nil || rejected.Code == 0 {
		t.Fatal("invalid proof admitted", e)
	}
	accepted, e := clients[0].BroadcastTxSync(ctx, types.Tx(tx))
	if e != nil || accepted.Code != 0 {
		t.Fatal("valid proof not admitted", e)
	}
	// Locate actual inclusion, rather than treating the mempool receipt as finality.
	included := int64(0)
	for k := 0; k < 50 && included == 0; k++ {
		h := height(clients[0])
		for n := int64(1); n <= h; n++ {
			b, e := clients[0].Block(ctx, &n)
			if e != nil {
				t.Fatal(e)
			}
			for _, raw := range b.Block.Data.Txs {
				if bytes.Equal(raw, tx) {
					included = n
				}
			}
		}
		if included == 0 {
			time.Sleep(200 * time.Millisecond)
		}
	}
	if included == 0 {
		t.Fatal("not included")
	}
	common := included + 2
	for _, c := range clients {
		wait(t, c, common)
	}
	vals := []*types.Validator{}
	for _, v := range gen.Validators {
		vals = append(vals, types.NewValidator(v.PubKey, v.Power))
	}
	set := types.NewValidatorSet(vals)
	// Independently replay each public block through a fresh real state worker.
	reference := open(t, filepath.Join(home, "reference.journal"), true)
	for h := int64(1); h < common; h++ {
		b, e := clients[0].Block(ctx, &h)
		if e != nil {
			t.Fatal(e)
		}
		txs := make([][]byte, len(b.Block.Data.Txs))
		for i, raw := range b.Block.Data.Txs {
			txs[i] = raw
		}
		_, e = reference.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: h, Hash: b.BlockID.Hash, Txs: txs})
		if e != nil {
			t.Fatal(e)
		}
		if _, e = reference.Commit(ctx, &abci.RequestCommit{}); e != nil {
			t.Fatal(e)
		}
	}
	expected := info(t, reference)
	var blockHash []byte
	for i, c := range clients {
		signed, e := c.Commit(ctx, &common)
		if e != nil {
			t.Fatal(e)
		}
		s := signed.SignedHeader
		if e = s.ValidateBasic(ChainID); e != nil {
			t.Fatal(e)
		}
		if e = set.VerifyCommit(ChainID, s.Commit.BlockID, common, s.Commit); e != nil {
			t.Fatal(e)
		}
		if !bytes.Equal(s.Header.Hash(), s.Commit.BlockID.Hash) || !bytes.Equal(s.Header.ValidatorsHash, set.Hash()) || !bytes.Equal(s.Header.AppHash, expected.LastBlockAppHash) {
			t.Fatal("header/state binding mismatch")
		}
		if i == 0 {
			blockHash = bytes.Clone(s.Header.Hash())
		} else if !bytes.Equal(blockHash, s.Header.Hash()) {
			t.Fatal("nodes diverged")
		}
	}
	t.Logf("real zero-value proof included at height %d; 4 node commits/signatures/app hashes matched independent Orchard replay", included)
	// Stop all four, preserving both consensus signer state and Orchard journals.
	for _, n := range nodes {
		stop(t, n)
	}
	highest := int64(0)
	for i := 0; i < 4; i++ {
		a := open(t, filepath.Join(home, fmt.Sprintf("node%d", i), "pool.journal"), false)
		s := info(t, a)
		if s.LastBlockHeight > highest {
			highest = s.LastBlockHeight
		}
		_ = a.Close()
	}
	for i := range nodes {
		nodes[i] = spawn(t, home, i, base)
	}
	for _, c := range clients {
		wait(t, c, highest+3)
	}
	ctx2, cancel2 := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel2()
	repeated, e := clients[0].BroadcastTxSync(ctx2, types.Tx(tx))
	if e != nil || repeated.Code == 0 {
		t.Fatal("spent protocol transaction admitted after full restart", e)
	}
	for _, c := range clients {
		q, e := c.ABCIQuery(ctx2, "/status", nil)
		if e != nil || q.Response.Code != 0 {
			t.Fatal(e)
		}
		var s struct {
			Ledger poolbridge.Summary `json:"ledger"`
		}
		if json.Unmarshal(q.Response.Value, &s) != nil || s.Ledger.Commitments != 2 || s.Ledger.Nullifiers != 2 || s.Ledger.Fees != 0 {
			t.Fatal("restored Orchard state mismatch")
		}
	}
	t.Log("full network restart exceeded every persisted height; spent nullifiers and 2 commitments retained; duplicate rejected")
}
