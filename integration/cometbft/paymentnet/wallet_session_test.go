package paymentnet

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// The persistent session holds the wallet only on the client side. It is not
// the public-only worker launched by validators. The password is synthetic.
func TestWarmWalletSessionAndActualSubmission(t *testing.T) {
	cryptoExe := os.Getenv("ZEVUNE_CRYPTO_BIN")
	if cryptoExe == "" {
		if os.Getenv("ZEVUNE_M5_REQUIRE") == "1" {
			t.Fatal("missing real crypto")
		}
		t.Skip("requires dedicated payment integration job")
	}
	sessionExe := filepath.Join(filepath.Dir(cryptoExe), "zevune-wallet-session"+filepath.Ext(cryptoExe))
	if _, err := os.Stat(sessionExe); err != nil {
		t.Fatal("missing built wallet session executable:", err)
	}
	dir := t.TempDir()
	home := filepath.Join(dir, "network")
	a := filepath.Join(dir, "a.wallet")
	b := filepath.Join(dir, "b.wallet")
	addrA := crypto(t, true, "wallet-new", a)
	addrB := crypto(t, true, "wallet-new", b)
	genesis := filepath.Join(dir, "genesis.bin")
	crypto(t, false, "genesis", addrA, genesis)
	if _, err := Init(home, availablePort(t), cryptoExe, genesis); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 4; i++ {
		spawn(t, home, i)
	}
	for i := 0; i < 4; i++ {
		waitState(t, home, i, 3)
	}
	history := filepath.Join(dir, "initial.json")
	export(t, home, history)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, sessionExe, a, genesis, "--password-stdin")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	in, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	startup := time.Now()
	if err = cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = in.Close(); _ = cmd.Process.Kill(); _ = cmd.Wait() }()
	reader := bufio.NewReaderSize(out, 4096)
	read := func() map[string]any {
		t.Helper()
		line, e := reader.ReadString('\n')
		if e != nil {
			t.Fatalf("wallet session response: %v", e)
		}
		var value map[string]any
		if json.Unmarshal([]byte(line), &value) != nil {
			t.Fatal("invalid session response")
		}
		return value
	}
	if _, err = io.WriteString(in, testPassword+"\n"); err != nil {
		t.Fatal(err)
	}
	if read()["ready"] != true {
		t.Fatal("wallet did not initialize")
	}
	ready := time.Now()
	target := filepath.Join(dir, "warm.tx")
	request, _ := json.Marshal(map[string]any{"op": "prepare", "id": 1, "history": history, "recipient": addrB, "units": 200000, "destination": target})
	begin := time.Now()
	if _, err = in.Write(append(request, '\n')); err != nil {
		t.Fatal(err)
	}
	response := read()
	if response["ok"] != true || response["id"] != float64(1) {
		t.Fatal("warm prepare failed")
	}
	prepared := time.Now()
	receipt := submit(t, home, target)
	confirmed := time.Now()
	final := filepath.Join(dir, "after.json")
	export(t, home, final)
	if crypto(t, true, "balance", b, final, genesis) != "200000" {
		t.Fatal("warm payment was not received")
	}
	scanned := time.Now()
	// The same unlocked session rescans without rebuilding proof parameters.
	request, _ = json.Marshal(map[string]any{"op": "balance", "id": 2, "history": final})
	if _, err = in.Write(append(request, '\n')); err != nil {
		t.Fatal(err)
	}
	response = read()
	data, ok := response["data"].(map[string]any)
	if !ok || response["ok"] != true || data["balance"] != float64(799000) {
		t.Fatal("resident wallet rescan mismatch")
	}
	_, _ = io.WriteString(in, "{\"op\":\"exit\",\"id\":3}\n")
	if read()["closed"] != true {
		t.Fatal("wallet did not close")
	}
	_ = in.Close()
	if err = cmd.Wait(); err != nil {
		t.Fatal("wallet session did not exit cleanly")
	}
	t.Logf("M5_WARM_TIMING initialization_ms=%.3f warm_prepare_ms=%.3f submit_checkpoint_ms=%.3f export_and_recipient_cold_scan_ms=%.3f height=%d; one sample, not p95 or TPS", float64(ready.Sub(startup).Microseconds())/1000, float64(prepared.Sub(begin).Microseconds())/1000, float64(confirmed.Sub(prepared).Microseconds())/1000, float64(scanned.Sub(confirmed).Microseconds())/1000, receipt.Height)
	if strings.Contains(stderr.String(), testPassword) {
		t.Fatal("password leaked into diagnostics")
	}
}
