package poolapp

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// This fixture exercises only the measurement state machine, NOT a fake worker
// or proof verifier. Actual 100000-block acceptance remains in the tagged test.
func growthObservationFixture() *growthObservation {
	return growthObservationFixtureWithCheckpoints(nil)
}

func growthObservationFixtureWithCheckpoints(emit func(*growthObservation)) *growthObservation {
	now := time.Unix(1, 0)
	g := newGrowthObservation(func() time.Time { now = now.Add(time.Microsecond); return now })
	if emit != nil {
		emit(g)
	}
	step := func(p growthPhase, h uint64) { g.begin(p, h); g.end() }
	for _, p := range []growthPhase{growthSetup, growthFundedStart, growthChecks, growthWorkerCreate, growthChecks} {
		step(p, 0)
	}
	for h := uint64(1); h <= 100_001; h++ {
		g.next(h)
		paid, boundary := growthPaidHeight(h), h >= 9_999 && h <= 10_002 || h == 100_001
		f, c := growthFinalizeEmpty, growthCommitEmpty
		if paid {
			step(growthPrepare, h)
			step(growthOutbox, h)
			f, c = growthFinalizePaid, growthCommitPaid
		}
		if boundary {
			step(growthSelect, h)
		}
		step(f, h)
		if boundary {
			step(growthPendingChecks, h)
		}
		step(c, h)
		if h <= 10_002 {
			step(growthScenarioApply, h)
		}
		if paid {
			for _, p := range []growthPhase{growthBalances, growthClose, growthWorkerReplay, growthChecks, growthWalletRecovery, growthSpent} {
				step(p, h)
			}
		}
		if h == 10_002 {
			step(growthBalances, h)
		}
		if h%25_000 == 0 {
			step(growthChecks, h)
			if emit != nil {
				emit(g)
			}
		}
		if h == 100_000 {
			step(growthChecks, h)
			step(growthClose, h)
			step(growthDisk, h)
			step(growthFullReplay, h)
			step(growthChecks, h)
		}
		if h == 100_001 {
			step(growthChecks, h)
			step(growthClose, h)
			step(growthDisk, h)
		}
	}
	g.coreDone = true
	return g
}

func TestGrowthObservationFullSequenceAndTiming(t *testing.T) {
	g := growthObservationFixture()
	r := g.report(true, false)
	if !r.ChecksCompleted || !r.MeasurementValid || r.Pending != nil || r.CommitOutcomeUnconfirmed || r.ConfirmedHeight != 100_001 {
		t.Fatal("complete measurement contract rejected")
	}
	var total int64
	for _, p := range r.Phases {
		if p.TotalNS != int64(p.Completed)*1_000 || p.MaxNS > p.TotalNS {
			t.Fatal("non-disjoint or inaccurate measured durations")
		}
		total += p.TotalNS
	}
	if r.ElapsedNS == nil || total > *r.ElapsedNS || g.report(false, false).ChecksCompleted || g.report(true, true).ChecksCompleted {
		t.Fatal("partial or failed observation became acceptance")
	}
}

func TestGrowthObservationMissingCoverageCannotClaimCompletion(t *testing.T) {
	g := growthObservationFixture()
	// Regression for the independent C1 review: state_checks (11) and
	// wallet_balances (3) must not escape the exact coverage inventory.
	if g.timings[growthChecks].Completed != 11 || g.timings[growthBalances].Completed != 3 {
		t.Fatal("fixture differs from the actual instrumented call sites")
	}
	for p := growthPhase(1); p < growthPhaseCount; p++ {
		if g.timings[p].Completed == 0 {
			t.Fatalf("phase %s has no fixture coverage", growthPhaseNames[p])
		}
		for _, duplicate := range []bool{false, true} {
			copy := *g
			if duplicate {
				copy.timings[p].Completed++
			} else {
				copy.timings[p].Completed--
			}
			if copy.report(true, false).ChecksCompleted {
				t.Fatalf("phase %s missing/duplicate=%t was accepted", growthPhaseNames[p], duplicate)
			}
		}
	}
	g.coreDone = false
	if g.report(true, false).ChecksCompleted {
		t.Fatal("missing final assertions accepted")
	}
}

func TestGrowthObservationUnconfirmedCommitKeepsLastConfirmed(t *testing.T) {
	now := time.Unix(1, 0)
	g := newGrowthObservation(func() time.Time { return now })
	g.next(1)
	g.begin(growthFinalizeEmpty, 1)
	now = now.Add(2 * time.Millisecond)
	g.end()
	g.begin(growthCommitEmpty, 1)
	now = now.Add(7 * time.Millisecond)
	r := g.report(true, true)
	if r.ChecksCompleted || r.ConfirmedHeight != 0 || r.AttemptedHeight != 1 || !r.CommitOutcomeUnconfirmed || r.Pending == nil || r.Pending.Phase != "commit_empty" || *r.Pending.ElapsedNS != 7_000_000 || g.timings[growthCommitEmpty].Completed != 0 {
		t.Fatal("unfinished commit invented success or completion time")
	}
	if g.timings[growthFinalizeEmpty].TotalNS != 2_000_000 {
		t.Fatal("completed finalization measurement was lost")
	}
}

func TestGrowthObservationRejectsInvalidTransitions(t *testing.T) {
	cases := []func(*growthObservation){
		func(g *growthObservation) { g.begin(growthPhaseCount, 0) },
		func(g *growthObservation) { g.begin(growthIdle, 0) },
		func(g *growthObservation) { g.end() },
		func(g *growthObservation) { g.next(2) },
		func(g *growthObservation) { g.begin(growthChecks, 100_002) },
		func(g *growthObservation) { g.begin(growthSetup, 0); g.begin(growthChecks, 0) },
		func(g *growthObservation) { g.next(1); g.begin(growthCommitEmpty, 1) },
		func(g *growthObservation) { g.next(1); g.begin(growthFinalizePaid, 1) },
		func(g *growthObservation) {
			g.next(1)
			g.begin(growthFinalizeEmpty, 1)
			g.end()
			g.begin(growthFinalizeEmpty, 1)
		},
		func(g *growthObservation) { g.publishedFinal = true; g.next(1) },
	}
	for i, apply := range cases {
		g := newGrowthObservation(time.Now)
		apply(g)
		r := g.report(true, false)
		if r.MeasurementValid || r.ChecksCompleted || r.ConfirmedHeight != 0 {
			t.Fatalf("invalid transition %d accepted", i)
		}
	}
}

func TestGrowthObservationClockFailureRetainsUnknownDuration(t *testing.T) {
	for _, shift := range []time.Duration{-time.Second, 2 * time.Hour} {
		now := time.Unix(100, 0)
		g := newGrowthObservation(func() time.Time { return now })
		g.next(1)
		g.begin(growthFinalizeEmpty, 1)
		now = now.Add(shift)
		g.end()
		r := g.report(true, true)
		if r.MeasurementValid || r.ElapsedNS != nil || r.Pending == nil || r.Pending.ElapsedNS != nil || g.timings[growthFinalizeEmpty].Completed != 0 {
			t.Fatal("bad clock became a zero-duration success")
		}
	}
}

func TestGrowthObservationPublicSchemaAndBound(t *testing.T) {
	g := growthObservationFixture()
	g.directory = "PRIVATE-PATH-SENTINEL"
	data, err := json.Marshal(g.report(true, false))
	if err != nil || len(data) > growthReportLimit || bytes.Contains(data, []byte(g.directory)) {
		t.Fatal("private context or unbounded observation")
	}
	var decoded map[string]json.RawMessage
	if json.Unmarshal(data, &decoded) != nil || len(decoded) != 13 {
		t.Fatal("unexpected public report schema")
	}
	if len(growthPhaseNames) != int(growthPhaseCount) {
		t.Fatal("phase names and bounded inventory differ")
	}
}

func TestGrowthObservationFilesAreCreateOnlyAndBounded(t *testing.T) {
	root := t.TempDir()
	original := []byte("original\n")
	if writeGrowthReport(root, "checkpoint-0.json", original) != nil {
		t.Fatal("could not write control")
	}
	for _, tc := range []struct {
		directory, name string
		data            []byte
	}{
		{root, "checkpoint-0.json", []byte("replacement")},
		{root, "checkpoint-5.json", original},
		{root, "../outside.json", original},
		{root, "final.json", make([]byte, growthReportLimit+1)},
		{"relative", "final.json", original},
		{filepath.Join(root, "missing"), "final.json", original},
	} {
		if err := writeGrowthReport(tc.directory, tc.name, tc.data); err != growthEvidenceError || err.Error() != "growth observation evidence unavailable" {
			t.Fatal("unsafe write or unredacted error")
		}
	}
	b, err := os.ReadFile(filepath.Join(root, "checkpoint-0.json"))
	if err != nil || !bytes.Equal(b, original) {
		t.Fatal("existing evidence was changed")
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 1 {
		t.Fatal("rejected writes created files")
	}
}

func TestGrowthObservationDirectoryLinkIsRefused(t *testing.T) {
	root := t.TempDir()
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(root, link); err != nil {
		t.Skip("OS does not permit a directory symlink for this account")
	}
	if writeGrowthReport(link, "final.json", []byte("{}")) != growthEvidenceError {
		t.Fatal("directory symlink accepted")
	}
}

func TestGrowthObservationChild(t *testing.T) {
	mode := os.Getenv("ZEVUNE_GROWTH_OBSERVATION_CHILD")
	if mode == "" {
		t.Skip("parent-only measurement failure helper")
	}
	g := installGrowthObservation(t)
	switch mode {
	case "fatal":
		g.next(1)
		g.begin(growthFinalizeEmpty, 1)
		g.end()
		g.begin(growthCommitEmpty, 1)
		t.Fatal("intentional measurement-test failure")
	case "cleanup", "missing-checkpoint":
		fixture := growthObservationFixture()
		// Preserve the reporter closure's pointer and output directory.
		fixture.directory, fixture.checkpoints = g.directory, g.checkpoints
		*g = *fixture
		if mode == "cleanup" {
			t.Cleanup(func() { t.Error("intentional cleanup failure") })
		}
	case "duplicate-checkpoint":
		g.publish(t, false)
	case "timeout":
		g.begin(growthFundedStart, 0)
		time.Sleep(time.Minute)
	default:
		t.Fatal("unknown measurement-test mode")
	}
}

func TestGrowthObservationRealFailNowCleanupAndTimeout(t *testing.T) {
	for _, mode := range []string{"fatal", "cleanup", "timeout", "missing-checkpoint", "duplicate-checkpoint"} {
		t.Run(mode, func(t *testing.T) {
			root := t.TempDir()
			ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			defer cancel()
			exe, err := os.Executable()
			if err != nil {
				t.Fatal("test executable unavailable")
			}
			budget := "5s"
			if mode == "timeout" {
				budget = "1s"
			}
			cmd := exec.CommandContext(ctx, exe, "-test.run=^TestGrowthObservationChild$", "-test.timeout="+budget)
			cmd.Env = append(os.Environ(), "ZEVUNE_GROWTH_OBSERVATION_CHILD="+mode, "ZEVUNE_GROWTH_EVIDENCE_DIR="+root)
			if err = cmd.Run(); err == nil || ctx.Err() != nil || cmd.ProcessState == nil || cmd.ProcessState.Success() {
				t.Fatal("deliberately failing child did not exit under its own test runner")
			}
			read := func(name string) growthReport {
				b, err := os.ReadFile(filepath.Join(root, name))
				var r growthReport
				if err != nil || len(b) > growthReportLimit || json.Unmarshal(b, &r) != nil {
					t.Fatal("missing bounded child evidence")
				}
				return r
			}
			if read("checkpoint-0.json").ChecksCompleted {
				t.Fatal("initial checkpoint claimed completion")
			}
			if mode == "timeout" {
				if _, err = os.Lstat(filepath.Join(root, "final.json")); !os.IsNotExist(err) {
					t.Fatal("hard timeout invented final evidence")
				}
				return
			}
			r := read("final.json")
			if !r.Final || !r.TestFailed || r.ChecksCompleted {
				t.Fatal("failure hidden by final observation")
			}
			if mode == "fatal" && (!r.CommitOutcomeUnconfirmed || r.ConfirmedHeight != 0 || r.AttemptedHeight != 1 || r.Pending == nil) {
				t.Fatal("FailNow lost unconfirmed commit")
			}
			if (mode == "missing-checkpoint" || mode == "duplicate-checkpoint") && r.MeasurementValid {
				t.Fatal("invalid checkpoint inventory accepted")
			}
			if mode == "cleanup" && (!r.MeasurementValid || r.ConfirmedHeight != 100_001) {
				t.Fatal("cleanup failure lost otherwise complete measurement")
			}
		})
	}
}

func TestGrowthObservationCompletePublicationAndImmutableSnapshots(t *testing.T) {
	root := t.TempDir()
	g := growthObservationFixtureWithCheckpoints(func(g *growthObservation) {
		g.directory = root
		g.publish(t, false)
	})
	before, err := os.ReadFile(filepath.Join(root, "checkpoint-0.json"))
	if err != nil {
		t.Fatal("initial snapshot missing")
	}
	g.publish(t, true)
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 6 {
		t.Fatal("wrong bounded file inventory")
	}
	for _, entry := range entries {
		b, err := os.ReadFile(filepath.Join(root, entry.Name()))
		var r growthReport
		if err != nil || len(b) > growthReportLimit || json.Unmarshal(b, &r) != nil {
			t.Fatal("invalid snapshot")
		}
		if entry.Name() == "final.json" {
			if !r.Final || !r.ChecksCompleted || r.TestFailed {
				t.Fatal("complete publication rejected")
			}
		} else if r.Final || r.ChecksCompleted {
			t.Fatal("checkpoint claimed completion")
		}
	}
	after, err := os.ReadFile(filepath.Join(root, "checkpoint-0.json"))
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("earlier evidence was overwritten")
	}
}
