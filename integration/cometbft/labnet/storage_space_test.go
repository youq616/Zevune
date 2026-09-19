package labnet

import (
	"encoding/json"
	"math"
	"reflect"
	"testing"
)

func TestDiskSpaceThresholdBoundariesAndClaims(t *testing.T) {
	for _, tc := range []struct {
		name      string
		available uint64
		reserve   uint64
		low       bool
	}{
		{"empty", 0, 1, true},
		{"below", 9, 10, true},
		{"equal", 10, 10, true},
		{"above", 11, 10, false},
		{"maximum-threshold", 10, math.MaxUint64, true},
		{"maximum-equal", math.MaxUint64, math.MaxUint64, true},
		{"maximum-above", math.MaxUint64, math.MaxUint64 - 1, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			report, err := diskSpaceReport(tc.available, tc.reserve)
			if err != nil {
				t.Fatal(err)
			}
			if report.Scope != diskSpaceScope || report.AvailableBytes != tc.available ||
				report.ReserveBytes != tc.reserve || report.LowSpace != tc.low || report.SpaceReserved {
				t.Fatalf("incorrect disk observation: %+v", report)
			}
		})
	}
	if report, err := diskSpaceReport(math.MaxUint64, 0); err == nil || report != (DiskSpaceReport{}) {
		t.Fatal("zero implicit reserve produced a report")
	}
	var absent *diskSpaceTarget
	for _, reserve := range []uint64{0, 1, math.MaxUint64} {
		if report, err := absent.sample(reserve); err == nil || report != (DiskSpaceReport{}) {
			t.Fatal("absent target produced a disk observation")
		}
	}
}

func TestDiskSpaceJSONKeepsFullWidthValuesAndExplicitFalse(t *testing.T) {
	report, err := diskSpaceReport(math.MaxUint64, math.MaxUint64-1)
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := json.Marshal(report)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(encoded, &fields); err != nil {
		t.Fatal(err)
	}
	want := map[string]json.RawMessage{
		"scope":           json.RawMessage(`"` + diskSpaceScope + `"`),
		"available_bytes": json.RawMessage("18446744073709551615"),
		"reserve_bytes":   json.RawMessage("18446744073709551614"),
		"low_space":       json.RawMessage("false"),
		"space_reserved":  json.RawMessage("false"),
	}
	if !reflect.DeepEqual(fields, want) {
		t.Fatalf("unexpected disk report fields: %s", encoded)
	}
	var decoded DiskSpaceReport
	if err := json.Unmarshal(encoded, &decoded); err != nil || decoded != report {
		t.Fatal("disk report lost uint64 precision")
	}
}
