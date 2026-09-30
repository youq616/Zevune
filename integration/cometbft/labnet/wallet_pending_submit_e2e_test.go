//go:build operator_e2e && wallet_network_e2e

package labnet

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

// This fixture forwards actual CometBFT responses; it never fabricates an
// accepting proof or mempool result. Only the second ACTUAL accepted response
// is discarded, AFTER the upstream has received the entire signed transaction.
func TestRealWalletPendingSubmission(t *testing.T) {
	for _, profile := range []string{"02", "03"} {
		t.Run(profile, func(t *testing.T) {
			root := t.TempDir()
			walletRoot := filepath.Join(root, "valueless-submit")
			if err := os.Mkdir(walletRoot, 0700); err != nil {
				t.Fatal(err)
			}
			networkExe := requiredExecutable(t, "ZEVUNE_NETWORK_OPERATOR")
			worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
			driver := launch(t, requiredExecutable(t, "ZEVUNE_PYTHON"), "-I",
				requiredExecutable(t, "ZEVUNE_WALLET_NETWORK_SUBMIT_SCENARIO"), walletRoot, networkExe, worker,
				requiredExecutable(t, "ZEVUNE_WALLET_LOCAL"), profile)
			initial := walletNetworkFrame(t, driver)
			asset, ok := initial["genesis_sha256"].(string)
			if initial["stage"] != "genesis" || !ok {
				t.Fatal("genesis frame")
			}
			if _, err := ParseHash(asset); err != nil {
				t.Fatal(err)
			}
			home := filepath.Join(root, "network")
			common := []string{"--no-real-funds", "--worker", worker, "--worker-sha256", HashText(executablePin(t, worker))}
			initArgs := append([]string{"init"}, common...)
			initArgs = append(initArgs, "--home", home, "--genesis", filepath.Join(walletRoot, "genesis.bin"), "--genesis-sha256", asset)
			var initialized struct {
				Pin string `json:"config_sha256"`
			}
			if json.Unmarshal(operator(t, initArgs, true), &initialized) != nil {
				t.Fatal("initialize")
			}
			pin, err := ParseHash(initialized.Pin)
			if err != nil {
				t.Fatal(err)
			}
			config := filepath.Join(home, configName)
			network, err := Load(config, pin)
			if err != nil {
				t.Fatal(err)
			}
			common = append(common, "--config", config, "--config-sha256", initialized.Pin)
			base := freePorts(t)
			nodes := make([]*process, 4)
			peers := make([]*peer, 4)
			running := make([]bool, 4)
			startStopped := func() {
				for i := range nodes {
					if running[i] {
						continue
					}
					if peers[i] != nil {
						peers[i].close()
					}
					args := append([]string{"run"}, common...)
					args = append(args, "--node", strconv.Itoa(i), "--base-port", strconv.Itoa(base), "--stop-on-stdin-eof")
					nodes[i] = launchNode(t, networkExe, i, network.config.NodeIDs[i], args...)
					running[i] = true
					peers[i], err = newPeer(Endpoint(base, i))
					if err != nil {
						t.Fatal(err)
					}
					t.Cleanup(peers[i].close)
				}
			}
			stop := func(from int) {
				for i := from; i < len(nodes); i++ {
					if running[i] {
						nodes[i].stop(t)
						running[i] = false
					}
				}
			}
			startStopped()
			awaitNetworkHeight(t, nodes, peers, 3)
			stop(1) // genuine RPC0/signed tip remains; no simulated height or clock
			upstream, err := url.Parse(Endpoint(base, 0))
			if err != nil {
				t.Fatal(err)
			}
			forwarding := httputil.NewSingleHostReverseProxy(upstream)
			transport := &http.Transport{Proxy: nil}
			forwarding.Transport = transport
			defer transport.CloseIdleConnections()
			var requests, broadcasts atomic.Int64
			var lostAccepted atomic.Bool
			var mu sync.Mutex
			var expected []byte
			round := -1
			relay := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				raw, readErr := io.ReadAll(io.LimitReader(r.Body, 65537))
				r.Body.Close()
				var q struct {
					Method string                     `json:"method"`
					Params map[string]json.RawMessage `json:"params"`
				}
				if readErr != nil || len(raw) > 65536 || json.Unmarshal(raw, &q) != nil {
					w.WriteHeader(400)
					return
				}
				r.Body = io.NopCloser(bytes.NewReader(raw))
				if q.Method != "broadcast_tx_sync" {
					forwarding.ServeHTTP(w, r)
					return
				}
				count := broadcasts.Add(1)
				var encoded string
				if json.Unmarshal(q.Params["tx"], &encoded) != nil {
					t.Error("missing broadcast bytes")
					w.WriteHeader(400)
					return
				}
				tx, decodeErr := base64.StdEncoding.DecodeString(encoded)
				mu.Lock()
				same := bytes.Equal(tx, expected)
				current := round
				mu.Unlock()
				if decodeErr != nil || !same || current < 0 || count != int64(current+1) {
					t.Error("unexpected or duplicate broadcast")
					w.WriteHeader(400)
					return
				}
				if current == 0 {
					forwarding.ServeHTTP(w, r)
					return
				}
				// Capture the REAL upstream result, then close the downstream before
				// sending any response. A failure here must not fake acceptance.
				recorded := httptest.NewRecorder()
				forwarding.ServeHTTP(recorded, r)
				var reply struct {
					Result struct {
						Code uint32 `json:"code"`
						Hash string `json:"hash"`
					} `json:"result"`
				}
				id := sha256.Sum256(tx)
				if recorded.Code != 200 || json.Unmarshal(recorded.Body.Bytes(), &reply) != nil || reply.Result.Code != 0 || !strings.EqualFold(reply.Result.Hash, HashText(id)) {
					t.Error("second actual mempool acceptance missing")
					w.WriteHeader(502)
					return
				}
				conn, _, hijackErr := w.(http.Hijacker).Hijack()
				if hijackErr != nil {
					t.Error(hijackErr)
					return
				}
				lostAccepted.Store(true)
				conn.Close()
			}))
			defer relay.Close()
			proxy, connections := privateOperatorProxy(t, relay.URL)
			// The ACTUAL command rejects a file/hash mismatch before any RPC.
			bad := filepath.Join(root, "mismatched.tx")
			if err := os.WriteFile(bad, []byte{1, 2, 3}, 0600); err != nil {
				t.Fatal(err)
			}
			badArgs := append([]string{"submit"}, common...)
			badArgs = append(badArgs, "--journal", filepath.Join(root, "not-opened-reference"), "--endpoint", privateTestEndpoint, "--socks-proxy", proxy, "--tx", bad, "--tx-sha256", strings.Repeat("11", 32))
			operator(t, badArgs, false)
			if requests.Load() != 0 || broadcasts.Load() != 0 {
				t.Fatal("hash mismatch reached RPC")
			}
			walletNetworkSend(t, driver, map[string]string{"config": config, "config_sha256": initialized.Pin, "endpoint": privateTestEndpoint, "socks_proxy": proxy})
			for index := 0; index < 2; index++ {
				ready := walletNetworkFrame(t, driver)
				if ready["stage"] != "ready-to-submit" || ready["round"] != float64(index) {
					t.Fatal("pending not ready")
				}
				tx, err := os.ReadFile(filepath.Join(walletRoot, "payment-"+strconv.Itoa(index)+".tx"))
				id := sha256.Sum256(tx)
				if err != nil || len(tx) < 98 || ready["txid"] != HashText(id) {
					t.Fatal("actual pending bytes missing")
				}
				if broadcasts.Load() != int64(index) {
					t.Fatal("prepare/recovery broadcast")
				}
				mu.Lock()
				expected = bytes.Clone(tx)
				round = index
				mu.Unlock()
				walletNetworkSend(t, driver, map[string]string{"stage": "submit-now"})
				submitted := walletNetworkFrame(t, driver)
				if submitted["stage"] != "submitted" || submitted["round"] != float64(index) || broadcasts.Load() != int64(index+1) {
					t.Fatal("one explicit submit required")
				}
				if index == 1 && !lostAccepted.Load() {
					t.Fatal("lost-response path not exercised")
				}
				// Restore quorum BEFORE shutting node0 down: mempool persistence is
				// not promised. Require actual inclusion and signed post-state first.
				startStopped()
				height := findInclusion(t, peers[0], tx, 1)
				awaitNetworkHeight(t, nodes, peers, height+1)
				stop(0)
				startStopped()
				awaitNetworkHeight(t, nodes, peers, height+3)
				stop(1)
				walletNetworkSend(t, driver, map[string]string{"stage": "included-and-restarted"})
			}
			last := walletNetworkFrame(t, driver)
			if last["stage"] != "done" || last["real_funds_allowed"] != false || last["accepted_not_confirmed"] != true || last["lost_response_unknown"] != true || last["pending_preserved"] != true || last["restarted"] != true || broadcasts.Load() != 2 || connections.Load() < 4 {
				t.Fatal("native submission incomplete")
			}
			driver.stop(t)
			stop(0)
			t.Log("two distinct valueless pending payments; each submitted once; real accepted then lost-response unknown; exact bytes, unchanged wallet and authenticated reconciliation after full restart")
		})
	}
}
