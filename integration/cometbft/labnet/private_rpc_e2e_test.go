//go:build operator_e2e

package labnet

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// Protocol-only SOCKS fixture forwarding to ONE independently fixed numeric
// local RPC endpoint. Never resolve/forward an onion name or claim Tor evidence.
// All four validators, proofs, signatures, worker and operator are real builds;
// only this transport hop is a fixture. This is not four-machine acceptance.
func privateOperatorProxy(t *testing.T, endpoint string) (string, *atomic.Int64) {
	t.Helper()
	if ValidateEndpoint(endpoint) != nil {
		t.Fatal("nonlocal test proxy target")
	}
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	var workers sync.WaitGroup
	var connections atomic.Int64
	workers.Add(1)
	go func() {
		defer workers.Done()
		for {
			client, err := listener.Accept()
			if err != nil {
				return
			}
			workers.Add(1)
			go func() {
				defer workers.Done()
				defer client.Close()
				stopClient := context.AfterFunc(ctx, func() { _ = client.Close() })
				defer stopClient()
				_ = client.SetDeadline(time.Now().Add(10 * time.Second))
				if _, err := acceptPrivateSOCKS(client); err != nil {
					return
				}
				upstream, err := (&net.Dialer{Timeout: 2 * time.Second}).DialContext(ctx, "tcp4", strings.TrimPrefix(endpoint, "http://"))
				if err != nil {
					return
				}
				defer upstream.Close()
				stopUpstream := context.AfterFunc(ctx, func() { _ = upstream.Close() })
				defer stopUpstream()
				_ = client.SetDeadline(time.Time{})
				connections.Add(1)
				copied := make(chan struct{})
				go func() { _, _ = io.Copy(upstream, client); _ = upstream.Close(); close(copied) }()
				_, _ = io.Copy(client, upstream)
				_ = client.Close()
				_ = upstream.Close()
				<-copied
			}()
		}
	}()
	t.Cleanup(func() { cancel(); _ = listener.Close(); workers.Wait() })
	return listener.Addr().String(), &connections
}

func TestRealOperatorPrivateRPCPaymentAndAuthenticatedReplay(t *testing.T) {
	root := t.TempDir()
	walletHome := filepath.Join(root, "private-wallets")
	if err := os.Mkdir(walletHome, 0700); err != nil {
		t.Fatal(err)
	}
	driver := launch(t, requiredExecutable(t, "ZEVUNE_FUNDED_SCENARIO"), walletHome)
	ready := driver.frame(t)
	if len(ready) != 128 {
		t.Fatal("real scenario initial frame")
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
	config := filepath.Join(home, configName)
	configPin, err := ParseHash(initialized.Pin)
	if err != nil {
		t.Fatal(err)
	}
	network, err := Load(config, configPin)
	if err != nil {
		t.Fatal(err)
	}
	common = append(common, "--config", config, "--config-sha256", initialized.Pin)
	base := freePorts(t)
	nodes := make([]*process, 4)
	peers := make([]*peer, 4)
	for i := 0; i < 4; i++ {
		args := append([]string{"run"}, common...)
		args = append(args, "--node", strconv.Itoa(i), "--base-port", strconv.Itoa(base), "--stop-on-stdin-eof")
		nodes[i] = launchNode(t, requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR"), i, network.config.NodeIDs[i], args...)
		peers[i], err = newPeer(Endpoint(base, i))
		if err != nil {
			t.Fatal(err)
		}
		defer peers[i].close()
	}
	awaitNetworkHeight(t, nodes, peers, 3)
	proxy, connections := privateOperatorProxy(t, Endpoint(base, 0))
	ref := filepath.Join(root, "private-reference.journal")
	route := []string{"--endpoint", privateTestEndpoint, "--socks-proxy", proxy, "--journal", ref}
	synchronize := func(create bool) SyncResult {
		args := append([]string{"sync"}, common...)
		args = append(args, route...)
		if create {
			args = append(args, "--create")
		}
		var result SyncResult
		if err := json.Unmarshal(operator(t, args, true), &result); err != nil {
			t.Fatal(err)
		}
		if result.Payments || result.Height == 0 {
			t.Fatal("invalid private sync result")
		}
		return result
	}
	initial := synchronize(true)
	state = replayScenario(t, peers[0], driver, state, initial.Height)
	if HashText(state.AppHash) != initial.AppHash {
		t.Fatal("initial private path replay mismatch")
	}
	raw := driver.call(t, 1, nil)
	if len(raw) < 40 || string(raw[:8]) != "ZVORLAB2" || !bytes.Equal(raw[8:40], assetPin[:]) {
		t.Fatal("real genesis-bound transaction required")
	}
	submit := func(raw []byte, expected bool) Submission {
		path := filepath.Join(root, "signed-test-payment.tx")
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
		args := append([]string{"submit"}, common...)
		args = append(args, route...)
		args = append(args, "--tx", path)
		var receipt Submission
		if err := json.Unmarshal(operator(t, args, expected), &receipt); err != nil {
			t.Fatal(err)
		}
		if receipt.Confirmed {
			t.Fatal("mempool receipt marked confirmed")
		}
		return receipt
	}
	corrupted := bytes.Clone(raw)
	corrupted[len(corrupted)-1] ^= 1
	if receipt := submit(corrupted, false); receipt.Status != "not_submitted" {
		t.Fatal("bad signature escaped private submit preflight")
	}
	if receipt := submit(raw, true); receipt.Status != "accepted_to_mempool_not_confirmed" {
		t.Fatal("private payment not submitted")
	}
	height := findInclusion(t, peers[0], raw, 1)
	// Preserve the original post-inclusion 90-second budget, shared by both
	// height waits and the final signed-header reads. Final sync may advance
	// beyond the payment's inclusion height; it does not synchronize all peers.
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	sources := make([]rpcSource, len(peers))
	statuses := make([]nodeStatusSource, len(peers))
	for i, p := range peers {
		sources[i], statuses[i] = p, p
	}
	if observed, err := waitNodeHeights(ctx, nodes, statuses, height+1); err != nil {
		t.Fatalf("private inclusion height wait: target=%d class=%s nodes=%+v", height+1, privateRPCCheckClass(err), observed)
	}
	final := synchronize(false)
	state = replayScenario(t, peers[0], driver, state, final.Height)
	if HashText(state.AppHash) != final.AppHash || state.Nullifiers == 0 {
		t.Fatal("private path did not retain genuine payment reexecution")
	}
	needed := int64(state.Height) + 1
	if observed, failure := checkPrivateRPCHeaders(ctx, network, nodes, sources, needed, state.AppHash); failure.Class != "ok" {
		t.Fatalf("private reference differs from signed validator state: %+v nodes=%+v", failure, observed)
	}
	if connections.Load() < 4 {
		t.Fatal("CLI operations bypassed the explicit SOCKS route")
	}
	for _, p := range nodes {
		p.stop(t)
	}
}
