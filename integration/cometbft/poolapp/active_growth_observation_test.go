package poolapp

// Test-only, single-goroutine observation. Nothing here authorizes a payment,
// reads ledger bytes, changes worker policy, retries a request or extends a timer.
import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"
)

type growthPhase uint8

const (
	growthIdle growthPhase = iota
	growthSetup
	growthFundedStart
	growthWorkerCreate
	growthWorkerReplay
	growthFullReplay
	growthChecks
	growthPrepare
	growthOutbox
	growthSelect
	growthFinalizeEmpty
	growthFinalizePaid
	growthPendingChecks
	growthCommitEmpty
	growthCommitPaid
	growthScenarioApply
	growthBalances
	growthWalletRecovery
	growthSpent
	growthClose
	growthDisk
	growthPhaseCount
)

var growthPhaseNames = [...]string{
	"idle", "setup", "funded_start", "worker_create", "boundary_worker_replay",
	"full_worker_replay", "state_checks", "payment_prepare", "outbox_recovery",
	"boundary_select_preview", "finalize_empty", "finalize_paid", "pending_checks",
	"commit_empty", "commit_paid", "scenario_apply", "wallet_balances",
	"wallet_history_recovery", "spent_rejection", "worker_close", "physical_check",
}

const growthReportLimit = 16 * 1024

var growthEvidenceError = errors.New("growth observation evidence unavailable")

type growthTiming struct {
	Completed uint64 `json:"completed"`
	TotalNS   int64  `json:"total_ns"`
	MaxNS     int64  `json:"max_ns"`
}

type growthPhaseReport struct {
	Name string `json:"name"`
	growthTiming
}

type growthPendingReport struct {
	Phase     string `json:"phase"`
	Height    uint64 `json:"height"`
	ElapsedNS *int64 `json:"observed_elapsed_ns"`
}

type growthReport struct {
	Schema                   int                  `json:"schema_version"`
	Scope                    string               `json:"scope"`
	Platform                 string               `json:"platform"`
	Final                    bool                 `json:"final"`
	ChecksCompleted          bool                 `json:"checks_completed"`
	TestFailed               bool                 `json:"test_failed"`
	MeasurementValid         bool                 `json:"measurement_valid"`
	ConfirmedHeight          uint64               `json:"last_confirmed_height"`
	AttemptedHeight          uint64               `json:"attempted_height"`
	CommitOutcomeUnconfirmed bool                 `json:"commit_outcome_unconfirmed"`
	ElapsedNS                *int64               `json:"observed_elapsed_ns"`
	Pending                  *growthPendingReport `json:"pending"`
	Phases                   []growthPhaseReport  `json:"phases"`
}

type growthObservation struct {
	now             func() time.Time
	started, last   time.Time
	phaseStarted    time.Time
	phase           growthPhase
	phaseHeight     uint64
	confirmed       uint64
	attempted       uint64
	finalized       uint64
	valid, coreDone bool
	timings         [growthPhaseCount]growthTiming
	directory       string
	checkpoints     int
	publishedFinal  bool
}

func newGrowthObservation(now func() time.Time) *growthObservation {
	s := now()
	return &growthObservation{now: now, started: s, last: s, valid: true}
}

func (g *growthObservation) clock() time.Time {
	n := g.now()
	// Monotonic time.Now/Sub in the real test; synthetic clocks only in unit tests.
	// Invalid clocks remain unknown, never manufactured zero-duration successes.
	if n.Before(g.last) || n.Sub(g.started) > time.Hour {
		g.valid = false
	}
	g.last = n
	return n
}

func growthPaidHeight(height uint64) bool { return height == 9_999 || height == 10_001 }

func (g *growthObservation) next(height uint64) {
	if g.publishedFinal || g.phase != growthIdle || height != g.confirmed+1 || height > 100_001 {
		g.valid = false
		return
	}
	g.attempted = height
}

func (g *growthObservation) begin(phase growthPhase, height uint64) {
	if !g.valid {
		return
	}
	if g.publishedFinal || g.phase != growthIdle || phase == growthIdle || phase >= growthPhaseCount || height > 100_001 {
		g.valid = false
		return
	}
	if phase == growthFinalizeEmpty || phase == growthFinalizePaid || phase == growthCommitEmpty || phase == growthCommitPaid {
		paid := phase == growthFinalizePaid || phase == growthCommitPaid
		commit := phase == growthCommitEmpty || phase == growthCommitPaid
		if height != g.attempted || height != g.confirmed+1 || paid != growthPaidHeight(height) || (commit && g.finalized != height) || (!commit && g.finalized != 0) {
			g.valid = false
			return
		}
	}
	g.phaseStarted = g.clock()
	g.phase, g.phaseHeight = phase, height
}

// Called ONLY after the original operation and all of its return-value checks
// succeed. FailNow leaves a pending observation and does not increment any count.
func (g *growthObservation) end() {
	if !g.valid {
		return
	}
	if g.phase == growthIdle || g.publishedFinal {
		g.valid = false
		return
	}
	elapsed := g.clock().Sub(g.phaseStarted).Nanoseconds()
	if !g.valid {
		return
	}
	metric := &g.timings[g.phase]
	metric.Completed++
	metric.TotalNS += elapsed
	if elapsed > metric.MaxNS {
		metric.MaxNS = elapsed
	}
	if g.phase == growthFinalizeEmpty || g.phase == growthFinalizePaid {
		g.finalized = g.phaseHeight
	}
	if g.phase == growthCommitEmpty || g.phase == growthCommitPaid {
		g.confirmed, g.finalized = g.phaseHeight, 0
	}
	g.phase = growthIdle
}

func (g *growthObservation) complete() bool {
	if !g.valid || !g.coreDone || g.phase != growthIdle || g.confirmed != 100_001 || g.finalized != 0 {
		return false
	}
	// Cross-check observation coverage; not a substitute for the original real
	// proof, Summary, capacity, physical-history and wallet assertions.
	want := map[growthPhase]uint64{
		growthSetup: 1, growthFundedStart: 1, growthWorkerCreate: 1,
		growthWorkerReplay: 2, growthFullReplay: 1, growthPrepare: 2,
		growthOutbox: 2, growthSelect: 5, growthPendingChecks: 5,
		growthFinalizeEmpty: 99_999, growthFinalizePaid: 2,
		growthCommitEmpty: 99_999, growthCommitPaid: 2,
		growthScenarioApply: 10_002, growthWalletRecovery: 2,
		growthSpent: 2, growthClose: 4, growthDisk: 2,
	}
	for phase, count := range want {
		if g.timings[phase].Completed != count {
			return false
		}
	}
	return true
}

func (g *growthObservation) report(final, failed bool) growthReport {
	n := g.clock()
	r := growthReport{
		Schema: 1, Scope: "local_growth_call_boundaries_not_fsync_or_tps", Platform: runtime.GOOS,
		Final: final, ChecksCompleted: final && !failed && g.complete(), TestFailed: failed,
		MeasurementValid: g.valid, ConfirmedHeight: g.confirmed, AttemptedHeight: g.attempted,
		CommitOutcomeUnconfirmed: g.phase == growthCommitEmpty || g.phase == growthCommitPaid,
	}
	if g.valid {
		d := n.Sub(g.started).Nanoseconds()
		r.ElapsedNS = &d
	}
	if g.phase != growthIdle {
		r.Pending = &growthPendingReport{Phase: growthPhaseNames[g.phase], Height: g.phaseHeight}
		if g.valid {
			d := n.Sub(g.phaseStarted).Nanoseconds()
			r.Pending.ElapsedNS = &d
		}
	}
	for phase := growthPhase(1); phase < growthPhaseCount; phase++ {
		r.Phases = append(r.Phases, growthPhaseReport{growthPhaseNames[phase], g.timings[phase]})
	}
	return r
}

// Create-only fixed filenames, six files at most, 16 KiB each. A failed partial
// write is retained and fails the test; it is never overwritten or called valid.
func writeGrowthReport(directory, name string, data []byte) error {
	if len(data) > growthReportLimit || (name != "final.json" && name != "checkpoint-0.json" && name != "checkpoint-1.json" && name != "checkpoint-2.json" && name != "checkpoint-3.json" && name != "checkpoint-4.json") {
		return growthEvidenceError
	}
	if !filepath.IsAbs(directory) {
		return growthEvidenceError
	}
	fi, err := os.Lstat(directory)
	if err != nil || !fi.IsDir() || fi.Mode()&os.ModeSymlink != 0 {
		return growthEvidenceError
	}
	f, err := os.OpenFile(filepath.Join(directory, name), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return growthEvidenceError
	}
	n, writeErr := f.Write(data)
	syncErr := f.Sync()
	closeErr := f.Close()
	if writeErr != nil || n != len(data) || syncErr != nil || closeErr != nil {
		return growthEvidenceError
	}
	return nil
}

func (g *growthObservation) publish(t *testing.T, final bool) {
	t.Helper()
	if g.publishedFinal || (!final && (g.checkpoints >= 5 || g.confirmed != uint64(g.checkpoints)*25_000 || g.phase != growthIdle || g.finalized != 0)) {
		g.valid = false
		t.Error("invalid growth observation checkpoint sequence")
		return
	}
	name := "final.json"
	if !final {
		name = fmt.Sprintf("checkpoint-%d.json", g.checkpoints)
		g.checkpoints++
	}
	if final && !t.Failed() && g.checkpoints != 5 {
		g.valid = false
	}
	r := g.report(final, t.Failed())
	if !r.MeasurementValid || (final && !r.ChecksCompleted && !t.Failed()) {
		t.Error("growth observation is incomplete or invalid")
		r.TestFailed, r.ChecksCompleted = true, false
	}
	g.publishedFinal = final
	data, err := json.Marshal(r)
	if err != nil || len(data)+1 > growthReportLimit {
		g.valid = false
		t.Error("growth observation encoding failed")
		return
	}
	data = append(data, '\n')
	if g.directory != "" && writeGrowthReport(g.directory, name, data) != nil {
		g.valid = false
		t.Error("growth observation persistence failed")
		return
	}
	t.Logf("ACTIVE_GROWTH_OBSERVATION %s", data)
}

func installGrowthObservation(t *testing.T) *growthObservation {
	t.Helper()
	g := newGrowthObservation(time.Now)
	g.directory = os.Getenv("ZEVUNE_GROWTH_EVIDENCE_DIR")
	// Register BEFORE TempDir and child cleanups: final evidence must include
	// teardown failures. Hard Go timeout / SIGKILL may leave only checkpoints.
	t.Cleanup(func() { g.publish(t, true) })
	g.publish(t, false)
	if t.Failed() {
		t.FailNow()
	}
	return g
}
