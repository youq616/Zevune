//go:build pool_e2e && funded_e2e

package poolapp

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	rpc "github.com/cometbft/cometbft/rpc/client/http"
	"github.com/cometbft/cometbft/types"
	"github.com/youq616/Zevune/internal/poolbridge"
)

type fundedDriver struct {
	in    io.WriteCloser
	out   io.ReadCloser
	cmd   *exec.Cmd
	done  chan error
	state poolbridge.Summary
}

func fundedRead(r io.Reader) ([]byte, error) {
	var size [4]byte
	if _, e := io.ReadFull(r, size[:]); e != nil {
		return nil, e
	}
	n := binary.BigEndian.Uint32(size[:])
	if n == 0 || n > 524288 {
		return nil, fmt.Errorf("invalid funded frame length")
	}
	b := make([]byte, n)
	_, e := io.ReadFull(r, b)
	return b, e
}
func fundedSummary(t *testing.T, b []byte) poolbridge.Summary {
	t.Helper()
	if len(b) != 96 {
		t.Fatal("invalid summary length")
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
func (d *fundedDriver) read(t *testing.T) []byte {
	t.Helper()
	type result struct {
		b []byte
		e error
	}
	ch := make(chan result, 1)
	go func() { b, e := fundedRead(d.out); ch <- result{b, e} }()
	select {
	case r := <-ch:
		if r.e != nil {
			t.Fatal("real funded scenario response", r.e)
		}
		return r.b
	case <-time.After(90 * time.Second):
		_ = d.cmd.Process.Kill()
		t.Fatal("real funded scenario timeout")
	}
	return nil
}
func startFunded(t *testing.T, home string) (*fundedDriver, poolbridge.Hash) {
	t.Helper()
	exe := os.Getenv("ZEVUNE_FUNDED_SCENARIO")
	fi, e := os.Lstat(exe)
	if e != nil || !fi.Mode().IsRegular() || !filepath.IsAbs(exe) {
		t.Fatal("actual funded scenario executable required", e)
	}
	d := &fundedDriver{cmd: exec.Command(exe, home), done: make(chan error, 1)}
	d.cmd.Env = []string{"RAYON_NUM_THREADS=2"}
	for _, env := range os.Environ() {
		k, _, ok := strings.Cut(env, "=")
		if ok && (strings.EqualFold(k, "SYSTEMROOT") || strings.EqualFold(k, "WINDIR") || strings.EqualFold(k, "TMP") || strings.EqualFold(k, "TEMP")) {
			d.cmd.Env = append(d.cmd.Env, env)
		}
	}
	d.cmd.Stderr = io.Discard
	d.in, e = d.cmd.StdinPipe()
	if e != nil {
		t.Fatal(e)
	}
	d.out, e = d.cmd.StdoutPipe()
	if e != nil {
		t.Fatal(e)
	}
	if e = d.cmd.Start(); e != nil {
		t.Fatal(e)
	}
	go func() { d.done <- d.cmd.Wait() }()
	t.Cleanup(func() {
		_ = d.in.Close()
		select {
		case e := <-d.done:
			if e != nil {
				t.Errorf("funded scenario exit: %v", e)
			}
		case <-time.After(10 * time.Second):
			_ = d.cmd.Process.Kill()
			<-d.done
			t.Error("funded scenario stop timeout")
		}
		_ = d.out.Close()
	})
	ready := d.read(t)
	if len(ready) != 128 {
		t.Fatal("invalid readiness")
	}
	var digest poolbridge.Hash
	copy(digest[:], ready[:32])
	d.state = fundedSummary(t, ready[32:])
	if d.state.Height != 0 || d.state.Commitments != 2 || d.state.Fees != 0 || d.state.Nullifiers != 0 {
		t.Fatal("unexpected genesis state")
	}
	return d, digest
}
func (d *fundedDriver) call(t *testing.T, op byte, data []byte) []byte {
	t.Helper()
	b := make([]byte, 5, 5+len(data))
	binary.BigEndian.PutUint32(b[:4], uint32(1+len(data)))
	b[4] = op
	b = append(b, data...)
	if _, e := io.Copy(d.in, bytes.NewReader(b)); e != nil {
		t.Fatal(e)
	}
	reply := d.read(t)
	if len(reply) == 0 || reply[0] != op {
		t.Fatal("mismatched driver response")
	}
	return reply[1:]
}
func verifyFundedHeader(t *testing.T, ctx context.Context, c *rpc.HTTP, vals *types.ValidatorSet, h int64) *types.SignedHeader {
	t.Helper()
	commit, e := c.Commit(ctx, &h)
	if e != nil {
		t.Fatal(e)
	}
	s := &commit.SignedHeader
	if e = s.ValidateBasic(ChainID); e != nil {
		t.Fatal(e)
	}
	if e = vals.VerifyCommit(ChainID, s.Commit.BlockID, h, s.Commit); e != nil {
		t.Fatal(e)
	}
	if !bytes.Equal(s.Header.Hash(), s.Commit.BlockID.Hash) || !bytes.Equal(s.Header.ValidatorsHash, vals.Hash()) || !bytes.Equal(s.Header.NextValidatorsHash, vals.Hash()) {
		t.Fatal("signed header identity mismatch")
	}
	return s
}
func (d *fundedDriver) replay(t *testing.T, ctx context.Context, c *rpc.HTTP, vals *types.ValidatorSet, target int64) {
	t.Helper()
	wait(t, c, target+1)
	for h := int64(d.state.Height) + 1; h <= target; h++ {
		b, e := c.Block(ctx, &h)
		if e != nil {
			t.Fatal(e)
		}
		signed := verifyFundedHeader(t, ctx, c, vals, h)
		if !bytes.Equal(b.Block.Hash(), signed.Header.Hash()) || !bytes.Equal(b.Block.Data.Hash(), signed.Header.DataHash) || !bytes.Equal(signed.Header.AppHash, d.state.AppHash[:]) {
			t.Fatal("public replay not bound to signed predecessor")
		}
		txs := make([][]byte, len(b.Block.Data.Txs))
		for i, tx := range b.Block.Data.Txs {
			txs[i] = tx
		}
		var hash poolbridge.Hash
		copy(hash[:], b.BlockID.Hash)
		encoded, e := poolbridge.BlockBytes(uint64(h), hash, txs)
		if e != nil {
			t.Fatal(e)
		}
		d.state = fundedSummary(t, d.call(t, 2, encoded))
		if d.state.Height != uint64(h) {
			t.Fatal("replay height mismatch")
		}
	}
	next := verifyFundedHeader(t, ctx, c, vals, target+1)
	if !bytes.Equal(next.Header.AppHash, d.state.AppHash[:]) {
		t.Fatal("replayed result differs from signed app hash")
	}
}
func assertFundedAgreement(t *testing.T, ctx context.Context, clients []*rpc.HTTP, vals *types.ValidatorSet, s poolbridge.Summary) {
	t.Helper()
	h := int64(s.Height) + 1
	var first []byte
	for i, c := range clients {
		wait(t, c, h)
		signed := verifyFundedHeader(t, ctx, c, vals, h)
		if !bytes.Equal(signed.Header.AppHash, s.AppHash[:]) {
			t.Fatal("validator state differs from independently replayed Orchard state")
		}
		if i == 0 {
			first = bytes.Clone(signed.Header.Hash())
		} else if !bytes.Equal(first, signed.Header.Hash()) {
			t.Fatal("validators disagree")
		}
	}
}
func inclusionFunded(t *testing.T, ctx context.Context, c *rpc.HTTP, tx []byte, start int64) int64 {
	t.Helper()
	deadline := time.Now().Add(60 * time.Second)
	cursor := start
	for time.Now().Before(deadline) {
		last := height(c)
		for ; cursor <= last; cursor++ {
			b, e := c.Block(ctx, &cursor)
			if e != nil {
				t.Fatal(e)
			}
			for _, raw := range b.Block.Data.Txs {
				if bytes.Equal(raw, tx) {
					return cursor
				}
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("signed transaction not included")
	return 0
}
func balancesFunded(t *testing.T, b []byte, balances [3]uint64, fee uint64) {
	t.Helper()
	if len(b) != 147 {
		t.Fatal("invalid scenario status")
	}
	s := fundedSummary(t, b[:96])
	if s.Fees != fee {
		t.Fatal("fees differ")
	}
	for i, expected := range balances {
		part := b[96+i*17 : 96+(i+1)*17]
		if binary.BigEndian.Uint64(part[:8]) != expected || binary.BigEndian.Uint64(part[8:16]) != expected || part[16] != 0 {
			t.Fatal("wallet balance, reservation or pending state mismatch")
		}
	}
}

func TestFundedWalletFourNodesAndRecovery(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Minute)
	defer cancel()
	root := t.TempDir()
	walletHome := filepath.Join(root, "local-wallets")
	if e := os.Mkdir(walletHome, 0700); e != nil {
		t.Fatal(e)
	}
	driver, pin := startFunded(t, walletHome)
	t.Setenv("ZEVUNE_TEST_GENESIS", filepath.Join(walletHome, "test-genesis.bin"))
	t.Setenv("ZEVUNE_TEST_GENESIS_SHA256", hex.EncodeToString(pin[:]))
	home := filepath.Join(root, "network")
	gen := setup(t, home)
	if !validGenesisState(gen.AppState, pin) || !bytes.Equal(gen.AppHash, driver.state.AppHash[:]) {
		t.Fatal("network not bound to checked public genesis")
	}
	vals := []*types.Validator{}
	for _, v := range gen.Validators {
		vals = append(vals, types.NewValidator(v.PubKey, v.Power))
	}
	set := types.NewValidatorSet(vals)
	base := freePorts(t)
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
	driver.replay(t, ctx, clients[0], set, 3)
	firstStart := time.Now()
	first := driver.call(t, 1, nil)
	if restored := driver.call(t, 4, []byte{0}); !bytes.Equal(first, restored) {
		t.Fatal("sender backup did not preserve exact signed payment")
	}
	bad := bytes.Clone(first)
	bad[len(bad)-1] ^= 1
	rejected, e := clients[0].BroadcastTxSync(ctx, types.Tx(bad))
	if e != nil || rejected.Code == 0 {
		t.Fatal("tampered paid transaction admitted", e)
	}
	accepted, e := clients[0].BroadcastTxSync(ctx, types.Tx(first))
	if e != nil || accepted.Code != 0 {
		t.Fatal("genuine nonzero payment rejected", e)
	}
	included := inclusionFunded(t, ctx, clients[0], first, 4)
	driver.replay(t, ctx, clients[0], set, included)
	assertFundedAgreement(t, ctx, clients, set, driver.state)
	balancesFunded(t, driver.call(t, 0, nil), [3]uint64{39_000, 60_000, 0}, 1_000)
	firstMS := time.Since(firstStart).Milliseconds()
	stop(t, nodes[3])
	secondStart := time.Now()
	driver.replay(t, ctx, clients[0], set, height(clients[0]))
	second := driver.call(t, 3, nil)
	if restored := driver.call(t, 4, []byte{1}); !bytes.Equal(second, restored) {
		t.Fatal("recipient backup lost onward payment")
	}
	accepted, e = clients[1].BroadcastTxSync(ctx, types.Tx(second))
	if e != nil || accepted.Code != 0 {
		t.Fatal("onward payment rejected with one node down", e)
	}
	onward := inclusionFunded(t, ctx, clients[0], second, included+1)
	driver.replay(t, ctx, clients[0], set, onward)
	assertFundedAgreement(t, ctx, clients[:3], set, driver.state)
	balancesFunded(t, driver.call(t, 0, nil), [3]uint64{39_000, 19_000, 40_000}, 2_000)
	secondMS := time.Since(secondStart).Milliseconds()
	nodes[3] = spawn(t, home, 3, base)
	wait(t, clients[3], onward+2)
	assertFundedAgreement(t, ctx, clients, set, driver.state)
	for _, n := range nodes {
		stop(t, n)
	}
	highest := int64(0)
	for i := range nodes {
		a := open(t, filepath.Join(home, fmt.Sprintf("node%d", i), "pool.journal"), false)
		s := info(t, a)
		if s.LastBlockHeight > highest {
			highest = s.LastBlockHeight
		}
		_ = a.Close()
	}
	balancesFunded(t, driver.call(t, 5, nil), [3]uint64{39_000, 19_000, 40_000}, 2_000)
	for i := range nodes {
		nodes[i] = spawn(t, home, i, base)
	}
	for _, c := range clients {
		wait(t, c, highest+3)
	}
	driver.replay(t, ctx, clients[0], set, highest+2)
	assertFundedAgreement(t, ctx, clients, set, driver.state)
	for _, tx := range [][]byte{first, second} {
		repeat, e := clients[0].BroadcastTxSync(ctx, types.Tx(tx))
		if e != nil || repeat.Code == 0 {
			t.Fatal("spent paid transaction accepted after restart", e)
		}
	}
	balancesFunded(t, driver.call(t, 6, nil), [3]uint64{39_000, 19_000, 40_000}, 2_000)
	for _, c := range clients {
		q, e := c.ABCIQuery(ctx, "/status", nil)
		if e != nil || q.Response.Code != 0 {
			t.Fatal(e)
		}
		var result struct {
			Mode   string             `json:"mode"`
			Ledger poolbridge.Summary `json:"ledger"`
		}
		if json.Unmarshal(q.Response.Value, &result) != nil || result.Mode != "local_fixed_supply_funded_orchard_lab" || result.Ledger.Commitments != 6 || result.Ledger.Nullifiers != 4 || result.Ledger.Fees != 2_000 {
			t.Fatal("restored funded state mismatch")
		}
	}
	t.Logf("FUNDED_LOCAL samples_ms=[%d,%d]; includes backup/rescan, signed-header checks and independent replay; only two samples, NOT p95/TPS/WAN or production payment speed", firstMS, secondMS)
	t.Log("actual nonzero A->B->C, multi-input change, exact encrypted outbox recovery, one-validator outage, full network restart, signed state agreement and duplicate rejection passed")
}
