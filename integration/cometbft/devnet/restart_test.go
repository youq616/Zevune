package devnet

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/cometbft/cometbft/libs/log"
	"github.com/youq616/Zevune/internal/ledger"
)

// Require NEW commits above the highest durable height, not merely a stale
// target that nodes may already have reached before the full shutdown.
func TestFullRestartAdvancesBeyondDurableHeight(t *testing.T) {
	if testing.Short() {
		t.Skip("four-process restart test")
	}
	home := filepath.Join(t.TempDir(), "restart-cluster")
	m, err := Init(home, freeBase(t))
	if err != nil {
		t.Fatal(err)
	}
	nodes := make([]*child, NodeCount)
	for i := range nodes {
		nodes[i] = spawn(t, home, i)
	}
	for i := range nodes {
		waitHeight(t, client(t, m, i), 3)
	}
	for _, n := range nodes {
		stop(t, n, false)
	}
	var maximum uint64
	for i := 0; i < NodeCount; i++ {
		e, err := ledger.OpenPersistent(ChainID, filepath.Join(nodeHome(home, i), "application"), nil, ledger.UnavailableVerifier{})
		if err != nil {
			t.Fatal(err)
		}
		h := e.Summary().Height
		if h > maximum {
			maximum = h
		}
		if err = e.Close(); err != nil {
			t.Fatal(err)
		}
	}
	for i := range nodes {
		nodes[i] = spawn(t, home, i)
	}
	for i := range nodes {
		waitHeight(t, client(t, m, i), int64(maximum)+3)
	}
	t.Logf("restart advanced every node beyond highest recovered height %d to at least %d", maximum, maximum+3)
}

func TestMissingSigningStateIsNotRecreated(t *testing.T) {
	home := filepath.Join(t.TempDir(), "missing-state")
	if _, err := Init(home, freeBase(t)); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(nodeHome(home, 0), "data", "priv_validator_state.json")
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if n, err := Start(home, 0, log.NewNopLogger()); err == nil {
		_ = n.Stop()
		t.Fatal("node started with missing anti-double-sign state")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("signing state was silently recreated")
	}
}
