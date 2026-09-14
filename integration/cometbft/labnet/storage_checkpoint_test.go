package labnet

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/youq616/Zevune/internal/poolbridge"
)

func TestStorageCheckpointCanonicalInputs(t *testing.T) {
	hash := HashText(Hash{0xab})
	for _, height := range []string{"0", "1", strconv.FormatUint(recordLimit, 10)} {
		c, err := ParseStorageCheckpoint(height, hash)
		if err != nil || strconv.FormatUint(c.Height, 10) != height || HashText(c.AppHash) != hash {
			t.Fatalf("valid exact checkpoint rejected: %v", err)
		}
	}
	for _, height := range []string{"", "00", "01", "+1", "-1", " 1", "1\n", "0x01", "1.0", "10001", "18446744073709551616", strings.Repeat("0", 4096)} {
		if c, err := ParseStorageCheckpoint(height, hash); err == nil || c != (StorageCheckpoint{}) {
			t.Fatal("non-canonical or out-of-range height accepted")
		}
	}
	for _, value := range []string{"", hash[:63], hash + "0", strings.ToUpper(hash), strings.Repeat("0", 64), hash + "\n"} {
		if c, err := ParseStorageCheckpoint("0", value); err == nil || c != (StorageCheckpoint{}) {
			t.Fatal("invalid checkpoint hash accepted")
		}
	}
}

func TestStorageCheckpointExactTipNotMinimumHeightOrFinality(t *testing.T) {
	s := poolbridge.Summary{Height: 3, AppHash: Hash{1}, Commitments: 2}
	c := StorageCheckpoint{Height: 3, AppHash: Hash{1}}
	r, err := storageReportAtCheckpoint(s, 44+3*150, &c)
	if err != nil || !r.ExpectedCheckpointMatched || r.ConsensusVerified || r.NetworkAccessed || r.RealFundsAllowed {
		t.Fatal("matching checkpoint rejected or overstated")
	}
	// A successful unpinned capacity check must explicitly say it did not check
	// a checkpoint, including on JSON output (no omitempty on the bool).
	unpinned, err := storageReportAtCheckpoint(s, 494, nil)
	if err != nil || unpinned.ExpectedCheckpointMatched {
		t.Fatal("unpinned check invented a trusted checkpoint")
	}
	raw, err := json.Marshal(unpinned)
	if err != nil || !strings.Contains(string(raw), `"expected_checkpoint_matched":false`) {
		t.Fatal("missing explicit unpinned result")
	}
	for _, other := range []poolbridge.Summary{
		{Height: 2, AppHash: Hash{1}}, // complete valid prefix is still the wrong tip
		{Height: 4, AppHash: Hash{1}}, // exact means not a minimum-height constraint
		{Height: 3, AppHash: Hash{2}}, // same-height alternate state
	} {
		out, err := storageReportAtCheckpoint(other, 1000, &c)
		if !errors.Is(err, ErrStorageCheckpoint) || out.Scope != "" || out.ExpectedCheckpointMatched {
			t.Fatal("wrong checkpoint emitted a success/partial report")
		}
	}
	// A matching pin never skips consistency and capacity validation.
	if out, err := storageReportAtCheckpoint(s, 1, &c); err == nil || out.ExpectedCheckpointMatched {
		t.Fatal("matching pin bypassed bounds")
	}
	genesis := StorageCheckpoint{Height: 0, AppHash: Hash{8}}
	if r, err := storageReportAtCheckpoint(poolbridge.Summary{AppHash: genesis.AppHash}, 44, &genesis); err != nil || !r.ExpectedCheckpointMatched {
		t.Fatal("height-zero checkpoint disabled")
	}
}

func TestInvalidStorageCheckpointFailsBeforeFileAccess(t *testing.T) {
	path := filepath.Join(t.TempDir(), "must-not-exist")
	n := &Network{}
	for _, c := range []StorageCheckpoint{{}, {Height: recordLimit + 1, AppHash: Hash{1}}, {Height: math.MaxUint64, AppHash: Hash{1}}} {
		if r, err := n.InspectStorageAtCheckpoint(context.Background(), "", Hash{}, path, c); !errors.Is(err, ErrBounds) || r.Scope != "" {
			t.Fatal("invalid checkpoint passed request preflight")
		}
	}
	var absent *Network
	if _, err := absent.InspectStorageAtCheckpoint(context.Background(), "", Hash{}, path, StorageCheckpoint{AppHash: Hash{1}}); !errors.Is(err, ErrBounds) {
		t.Fatal("nil network accepted")
	}
	if _, err := n.InspectStorageAtCheckpoint(nil, "", Hash{}, path, StorageCheckpoint{AppHash: Hash{1}}); !errors.Is(err, ErrBounds) {
		t.Fatal("nil context accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := n.InspectStorageAtCheckpoint(ctx, "", Hash{}, path, StorageCheckpoint{AppHash: Hash{1}}); err == nil {
		t.Fatal("cancelled context accepted")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("invalid checkpoint created data")
	}
}

func FuzzStorageCheckpointInputs(f *testing.F) {
	f.Add("0", HashText(Hash{1}))
	f.Add("10000", HashText(Hash{2}))
	f.Add("01", strings.Repeat("0", 64))
	f.Fuzz(func(t *testing.T, height, hash string) {
		c, err := ParseStorageCheckpoint(height, hash)
		if err != nil {
			return
		}
		if c.Validate() != nil || strconv.FormatUint(c.Height, 10) != height || HashText(c.AppHash) != hash {
			t.Fatal("non-canonical checkpoint accepted")
		}
		r, err := storageReportAtCheckpoint(poolbridge.Summary{Height: c.Height, AppHash: c.AppHash}, int64(44+c.Height*150), &c)
		if err != nil || !r.ExpectedCheckpointMatched || r.ConsensusVerified || r.NetworkAccessed || r.RealFundsAllowed {
			t.Fatal("checkpoint result overstated")
		}
	})
}
