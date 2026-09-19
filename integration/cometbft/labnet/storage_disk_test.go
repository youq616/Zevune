package labnet

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/youq616/Zevune/internal/poolbridge"
)

func TestDiskInspectionRejectsInvalidRequestsBeforeOpeningStorage(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "must-not-exist")
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	legacy := &Network{profile: poolbridge.LegacyJournal}
	active := &Network{profile: poolbridge.ActiveSegmentsV1}
	for _, tc := range []struct {
		name     string
		network  *Network
		ctx      context.Context
		reserve  uint64
		expected *StorageCheckpoint
		wantErr  error
	}{
		{"nil-network", nil, context.Background(), 1, nil, ErrBounds},
		{"nil-context", legacy, nil, 1, nil, ErrBounds},
		{"cancelled-context", legacy, ctx, 1, nil, ErrBounds},
		{"zero-reserve", legacy, context.Background(), 0, nil, ErrBounds},
		{"unknown-profile", &Network{profile: poolbridge.StorageProfile(255)}, context.Background(), 1, nil, ErrStorageProfile},
		{"empty-checkpoint", legacy, context.Background(), 1, &StorageCheckpoint{}, ErrBounds},
		{"legacy-height", legacy, context.Background(), 1, &StorageCheckpoint{Height: poolbridge.LegacyJournal.MaxHeight() + 1, AppHash: Hash{1}}, ErrBounds},
		{"active-height", active, context.Background(), 1, &StorageCheckpoint{Height: poolbridge.ActiveSegmentsV1.MaxHeight() + 1, AppHash: Hash{1}}, ErrBounds},
		{"overflow-height", active, context.Background(), math.MaxUint64, &StorageCheckpoint{Height: math.MaxUint64, AppHash: Hash{1}}, ErrBounds},
	} {
		t.Run(tc.name, func(t *testing.T) {
			report, err := tc.network.InspectStorageWithDiskSpace(tc.ctx, "", Hash{}, missing, tc.reserve, tc.expected)
			if !errors.Is(err, tc.wantErr) || !reflect.DeepEqual(report, StorageReport{}) {
				t.Fatalf("invalid request produced a report or reached storage: %v", err)
			}
		})
	}
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Fatal("invalid disk inspection request created storage")
	}
}

func TestDiskInspectionNeverCreatesMissingStorage(t *testing.T) {
	for _, profile := range []poolbridge.StorageProfile{poolbridge.LegacyJournal, poolbridge.ActiveSegmentsV1} {
		missing := filepath.Join(t.TempDir(), "must-not-exist")
		n := &Network{profile: profile}
		for _, expected := range []*StorageCheckpoint{nil, {Height: profile.MaxHeight(), AppHash: Hash{1}}} {
			report, err := n.InspectStorageWithDiskSpace(context.Background(), "", Hash{}, missing, math.MaxUint64, expected)
			if err == nil || !reflect.DeepEqual(report, StorageReport{}) {
				t.Fatal("missing storage produced a disk inspection report")
			}
		}
		if _, err := os.Stat(missing); !os.IsNotExist(err) {
			t.Fatal("disk inspection created missing storage")
		}
	}
}

func TestDefaultStorageReportsKeepDiskSpaceAbsent(t *testing.T) {
	summary := poolbridge.Summary{Height: 1, AppHash: Hash{1}, Commitments: 2}
	checkpoint := StorageCheckpoint{Height: summary.Height, AppHash: summary.AppHash}
	for _, expected := range []*StorageCheckpoint{nil, &checkpoint} {
		legacy, err := storageReportAtCheckpoint(summary, 194, expected)
		if err != nil {
			t.Fatal(err)
		}
		active, err := activeStorageReport(poolbridge.ActiveStorage{
			Summary: summary, LogicalBytes: 194, Segments: 1, TailBytes: 150,
		}, expected)
		if err != nil {
			t.Fatal(err)
		}
		for _, report := range []StorageReport{legacy, active} {
			raw, err := json.Marshal(report)
			if err != nil || report.DiskSpace != nil || strings.Contains(string(raw), `"disk_space"`) {
				t.Fatal("default capacity report introduced a disk observation")
			}
			if report.ExpectedCheckpointMatched != (expected != nil) || !report.EmptyBlockFitsLimits || len(report.Warnings) != 0 {
				t.Fatal("default capacity or checkpoint semantics changed")
			}
		}
	}
}
