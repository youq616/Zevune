//go:build payment_resource_e2e

package poolbridge

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// This test is supervised by scripts/check_payment_resources.py. Neither the
// progress files nor the metrics protocol carry wallet secrets or transaction
// bytes. The actual worker continues to enforce all production state rules.
type paymentResourceProgress struct {
	SchemaVersion   int    `json:"schema_version"`
	Seq             int    `json:"seq"`
	Operation       string `json:"operation"`
	PaymentIndex    uint64 `json:"payment_index"`
	CommittedBlocks uint64 `json:"committed_blocks"`
	Status          string `json:"status"`
	DurationMS      *int64 `json:"duration_ms,omitempty"`
}

type paymentResourceWallet struct {
	Balance   uint64
	Available uint64
	Pending   bool
	Records   uint64
	FileBytes uint64
}

type paymentResourceScenario struct {
	cmd    *exec.Cmd
	in     io.WriteCloser
	out    io.ReadCloser
	done   chan error
	closed bool
}

type paymentResourceRun struct {
	t          *testing.T
	ctx        context.Context
	directory  string
	started    time.Time
	progress   int
	events     int
	committed  uint64
	operations []paymentResourceProgress
	scenario   *paymentResourceScenario
	worker     *Client
	generation int
	walletPath [2]string
	wallets    [2]paymentResourceWallet
	state      Summary
	capacity   ActiveStorage
}

func paymentResourceWriteJSON(t *testing.T, directory, name string, value any) {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil || len(raw) > 65536 {
		t.Fatal("resource evidence encoding or size failed")
	}
	target := filepath.Join(directory, name)
	if _, err = os.Lstat(target); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("resource evidence must be a new file")
	}
	f, err := os.CreateTemp(directory, ".resource-")
	if err != nil {
		t.Fatal("resource evidence temporary file creation failed")
	}
	defer os.Remove(f.Name())
	if err = f.Chmod(0600); err == nil {
		err = writeAll(f, raw)
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil || closeErr != nil || os.Rename(f.Name(), target) != nil {
		t.Fatal("resource evidence publication failed")
	}
}

func (r *paymentResourceRun) measure(operation string, payment uint64, f func()) {
	r.t.Helper()
	if r.progress+2 > 2048 || payment > 33 || r.committed > 33 {
		r.t.Fatal("resource progress bounds exceeded")
	}
	r.progress++
	entry := paymentResourceProgress{
		SchemaVersion: 1, Seq: r.progress, Operation: operation,
		PaymentIndex: payment, CommittedBlocks: r.committed, Status: "started",
	}
	paymentResourceWriteJSON(r.t, r.directory, fmt.Sprintf("progress-%04d.json", r.progress), entry)
	start := time.Now()
	f()
	duration := time.Since(start).Milliseconds()
	r.progress++
	entry.Seq = r.progress
	entry.Status = "completed"
	entry.CommittedBlocks = r.committed
	entry.DurationMS = &duration
	paymentResourceWriteJSON(r.t, r.directory, fmt.Sprintf("progress-%04d.json", r.progress), entry)
	r.operations = append(r.operations, entry)
}

func (r *paymentResourceRun) scenarioExchange(request []byte) []byte {
	r.t.Helper()
	type reply struct {
		body []byte
		err  error
	}
	ch := make(chan reply, 1)
	go func() {
		var err error
		if request != nil {
			err = writeFrame(r.scenario.in, request)
		}
		var body []byte
		if err == nil {
			body, err = readFrame(r.scenario.out, 524288)
		}
		ch <- reply{body, err}
	}()
	timer := time.NewTimer(90 * time.Second)
	defer timer.Stop()
	select {
	case result := <-ch:
		if result.err != nil {
			r.t.Fatal("real resource scenario exchange failed")
		}
		return result.body
	case <-timer.C:
		_ = r.scenario.cmd.Process.Kill()
		r.t.Fatal("real resource scenario response exceeded 90 seconds")
	case <-r.ctx.Done():
		_ = r.scenario.cmd.Process.Kill()
		r.t.Fatal("resource stage exceeded its fixed deadline")
	}
	return nil
}

func (r *paymentResourceRun) call(op byte, data []byte) []byte {
	r.t.Helper()
	request := make([]byte, 1, 1+len(data))
	request[0] = op
	request = append(request, data...)
	reply := r.scenarioExchange(request)
	if len(reply) == 0 || reply[0] != op {
		r.t.Fatal("resource scenario response operation mismatch")
	}
	return reply[1:]
}

func (r *paymentResourceRun) closeScenario() {
	r.t.Helper()
	d := r.scenario
	if d == nil || d.closed {
		return
	}
	d.closed = true
	_ = d.in.Close()
	select {
	case err := <-d.done:
		if err != nil {
			r.t.Error("resource scenario did not exit successfully")
		}
	case <-time.After(10 * time.Second):
		_ = d.cmd.Process.Kill()
		<-d.done
		r.t.Error("resource scenario close exceeded 10 seconds")
	}
	_ = d.out.Close()
}

func (r *paymentResourceRun) startScenario(home string) Hash {
	r.t.Helper()
	executable := os.Getenv("ZEVUNE_FUNDED_SCENARIO")
	info, err := os.Lstat(executable)
	if err != nil || !filepath.IsAbs(executable) || !info.Mode().IsRegular() {
		r.t.Fatal("actual funded scenario executable is required")
	}
	d := &paymentResourceScenario{
		cmd: exec.Command(executable, home, "--active-resource-v1"), done: make(chan error, 1),
	}
	d.cmd.Env = []string{"RAYON_NUM_THREADS=2"}
	for _, entry := range os.Environ() {
		name, _, ok := strings.Cut(entry, "=")
		if ok && (strings.EqualFold(name, "SYSTEMROOT") || strings.EqualFold(name, "WINDIR") || strings.EqualFold(name, "TEMP") || strings.EqualFold(name, "TMP")) {
			d.cmd.Env = append(d.cmd.Env, entry)
		}
	}
	d.cmd.Stderr = io.Discard
	d.in, err = d.cmd.StdinPipe()
	if err != nil {
		r.t.Fatal("resource scenario input pipe failed")
	}
	d.out, err = d.cmd.StdoutPipe()
	if err != nil {
		_ = d.in.Close()
		r.t.Fatal("resource scenario output pipe failed")
	}
	if err = d.cmd.Start(); err != nil {
		_ = d.in.Close()
		_ = d.out.Close()
		r.t.Fatal("resource scenario process start failed")
	}
	r.scenario = d
	go func() { d.done <- d.cmd.Wait() }()
	r.t.Cleanup(r.closeScenario)
	ready := r.scenarioExchange(nil)
	if len(ready) != 128 {
		r.t.Fatal("resource scenario readiness length mismatch")
	}
	var pin Hash
	copy(pin[:], ready[:32])
	r.state = r.summary(ready[32:])
	if pin == (Hash{}) || r.state.Height != 0 || r.state.Commitments != 2 || r.state.Nullifiers != 0 || r.state.Fees != 0 {
		r.t.Fatal("resource scenario did not create the fixed funded genesis")
	}
	return pin
}

func (r *paymentResourceRun) summary(raw []byte) Summary {
	r.t.Helper()
	state, err := ActiveSegmentsV1.decodeSummary(raw)
	if err != nil {
		r.t.Fatal("resource scenario Summary encoding mismatch")
	}
	return state
}

func (r *paymentResourceRun) walletStatus(op byte, pending bool) [2]paymentResourceWallet {
	r.t.Helper()
	raw := r.call(op, nil)
	if len(raw) != 162 || r.summary(raw[:96]) != r.state {
		r.t.Fatal("independent scenario Summary differs from committed worker state")
	}
	var wallets [2]paymentResourceWallet
	for index := range wallets {
		part := raw[96+33*index : 96+33*(index+1)]
		if part[16] > 1 {
			r.t.Fatal("wallet pending marker is not canonical")
		}
		wallets[index] = paymentResourceWallet{
			Balance: binary.BigEndian.Uint64(part[:8]), Available: binary.BigEndian.Uint64(part[8:16]),
			Pending: part[16] == 1, Records: binary.BigEndian.Uint64(part[17:25]), FileBytes: binary.BigEndian.Uint64(part[25:33]),
		}
	}
	height := r.state.Height
	odd, even := (height+1)/2, height/2
	balances := [2]uint64{50000 - 2000*odd + 1000*even, 50000 + 1000*odd - 2000*even}
	records := [2]uint64{2 + height + odd, 2 + height + even}
	for index, wallet := range wallets {
		wantPending := pending && uint64(index) == height%2
		if wantPending {
			records[index]++
		}
		info, err := os.Lstat(r.walletPath[index])
		if err != nil || !info.Mode().IsRegular() || info.Size() <= 0 || uint64(info.Size()) != wallet.FileBytes {
			r.t.Fatal("actual encrypted wallet file size differs from storage_status")
		}
		if wallet.Balance != balances[index] || wallet.Records != records[index] || wallet.Pending != wantPending || wallet.Available > wallet.Balance {
			r.t.Fatal("fixed payment wallet balance, records or reservation mismatch")
		}
		if (!wantPending && wallet.Available != wallet.Balance) || (wantPending && wallet.Available == wallet.Balance) {
			r.t.Fatal("wallet available balance did not reflect the actual pending reservation")
		}
	}
	return wallets
}

func (r *paymentResourceRun) workerSnapshot() (Summary, ActiveStorage) {
	r.t.Helper()
	state, err := r.worker.Status(r.ctx)
	if err != nil {
		r.t.Fatal("resource worker Status failed")
	}
	capacity, err := r.worker.ActiveCapacity(r.ctx)
	if err != nil || capacity.Summary != state {
		r.t.Fatal("resource worker ActiveCapacity failed or describes a different Summary")
	}
	return state, capacity
}

// Windows prevents another process from reading the locked genesis header.
// While the worker is alive, compare its metadata and all segment bytes. Full
// header bytes and complete physical records are checked after each Close.
func paymentResourceDiskDigest(t *testing.T, path string) Hash {
	t.Helper()
	entries, err := os.ReadDir(path)
	if err != nil {
		t.Fatal("resource ledger directory inspection failed")
	}
	hash := sha256.New()
	for _, entry := range entries {
		name := filepath.Join(path, entry.Name())
		info, err := os.Lstat(name)
		if err != nil || !info.Mode().IsRegular() {
			t.Fatal("resource ledger has a non-regular entry")
		}
		_, _ = hash.Write([]byte(entry.Name()))
		var raw [8]byte
		binary.BigEndian.PutUint64(raw[:], uint64(info.Size()))
		_, _ = hash.Write(raw[:])
		if entry.Name() == "genesis" {
			binary.BigEndian.PutUint64(raw[:], uint64(info.ModTime().UnixNano()))
			_, _ = hash.Write(raw[:])
			continue
		}
		body, err := os.ReadFile(name)
		if err != nil || int64(len(body)) != info.Size() {
			t.Fatal("resource ledger segment byte inspection failed")
		}
		_, _ = hash.Write(body)
	}
	var result Hash
	copy(result[:], hash.Sum(nil))
	return result
}

func paymentResourceHash(height uint64) Hash {
	var raw [8]byte
	binary.BigEndian.PutUint64(raw[:], height)
	return sha256.Sum256(append([]byte("ZEVUNE-PAYMENT-RESOURCE-NO-FUNDS\x00"), raw[:]...))
}

func (r *paymentResourceRun) unchanged(path string, disk Hash) {
	r.t.Helper()
	state, capacity := r.workerSnapshot()
	if state != r.state || capacity != r.capacity || paymentResourceDiskDigest(r.t, path) != disk {
		r.t.Fatal("rejected or uncommitted candidate changed committed state or ledger bytes")
	}
}

func (r *paymentResourceRun) rejectSpent(path string, transactions [][]byte, pending bool) {
	r.t.Helper()
	disk := paymentResourceDiskDigest(r.t, path)
	for _, tx := range transactions {
		if len(tx) < 48 || binary.BigEndian.Uint64(tx[40:48]) < r.state.Height+1 {
			r.t.Fatal("duplicate test payment expired before its rejection check")
		}
		if err := r.worker.Check(r.ctx, tx); !errors.Is(err, ErrRejected) {
			r.t.Fatal("spent payment Check did not reject")
		}
		if _, err := r.worker.Preview(r.ctx, r.state.Height+1, paymentResourceHash(r.state.Height+1), [][]byte{tx}); !errors.Is(err, ErrRejected) {
			r.t.Fatal("spent payment Preview did not reject")
		}
		if _, _, err := r.worker.Finalize(r.ctx, r.state.Height+1, paymentResourceHash(r.state.Height+1), [][]byte{tx}); !errors.Is(err, ErrRejected) {
			r.t.Fatal("spent payment Finalize did not reject")
		}
	}
	selected, err := r.worker.SelectProposal(r.ctx, r.state.Height+1, MaxProposalBytes, transactions)
	if err != nil || len(selected) != 0 {
		r.t.Fatal("spent payments were selected")
	}
	r.unchanged(path, disk)
	if r.walletStatus(0, pending) != r.wallets {
		r.t.Fatal("duplicate rejection changed wallet state or reservations")
	}
}

func (r *paymentResourceRun) candidate(path string, tx []byte) Summary {
	r.t.Helper()
	height, hash := r.state.Height+1, paymentResourceHash(r.state.Height+1)
	disk := paymentResourceDiskDigest(r.t, path)
	broken := bytes.Clone(tx)
	broken[len(broken)-1] ^= 1
	if err := r.worker.Check(r.ctx, broken); !errors.Is(err, ErrRejected) {
		r.t.Fatal("bad binding signature Check did not reject")
	}
	if _, err := r.worker.Preview(r.ctx, height, hash, [][]byte{broken}); !errors.Is(err, ErrRejected) {
		r.t.Fatal("bad binding signature Preview did not reject")
	}
	if _, _, err := r.worker.Finalize(r.ctx, height, hash, [][]byte{broken}); !errors.Is(err, ErrRejected) {
		r.t.Fatal("bad binding signature Finalize did not reject")
	}
	if err := r.worker.Check(r.ctx, tx); err != nil {
		r.t.Fatal("genuine resource payment Check failed")
	}
	selected, err := r.worker.SelectProposal(r.ctx, height, MaxProposalBytes, [][]byte{broken, tx, tx})
	if err != nil || len(selected) != 1 || !bytes.Equal(selected[0], tx) {
		r.t.Fatal("candidate selection did not preserve the real payment exactly once")
	}
	preview, err := r.worker.Preview(r.ctx, height, hash, selected)
	if err != nil || preview.Height != height || preview.Commitments != 2+2*height || preview.Nullifiers != 2*height || preview.Fees != 1000*height {
		r.t.Fatal("genuine payment Preview failed or had incorrect public state")
	}
	r.unchanged(path, disk)
	if r.walletStatus(0, true) != r.wallets {
		r.t.Fatal("candidate rejection or selection changed wallet reservations")
	}
	return preview
}

func (r *paymentResourceRun) commit(path string, tx []byte, preview Summary, previousPayments [][]byte) {
	r.t.Helper()
	height := r.state.Height + 1
	disk := paymentResourceDiskDigest(r.t, path)
	finalized, tag, err := r.worker.Finalize(r.ctx, height, paymentResourceHash(height), [][]byte{tx})
	if err != nil || finalized != preview {
		r.t.Fatal("genuine payment Finalize differs from Preview")
	}
	r.unchanged(path, disk)
	if height == 33 {
		wrong := tag
		wrong[0] ^= 1
		if _, err = r.worker.Commit(r.ctx, wrong); !errors.Is(err, ErrRejected) {
			r.t.Fatal("wrong Commit tag accepted while a genuine finalization was pending")
		}
		r.rejectSpent(path, previousPayments, true)
		selected, err := r.worker.SelectProposal(r.ctx, height, MaxProposalBytes, [][]byte{tx, tx})
		if err != nil || len(selected) != 1 || !bytes.Equal(selected[0], tx) {
			r.t.Fatal("selection with a nonempty pending commit slot changed the valid candidate")
		}
		r.unchanged(path, disk)
	}
	committed, err := r.worker.Commit(r.ctx, tag)
	if err != nil || committed != finalized {
		r.t.Fatal("real payment Commit failed or lost the valid pending commit slot")
	}
	r.state = committed
	r.committed = committed.Height
	frameBytes := uint64(EmptyRecordBytes + 4 + len(tx))
	r.capacity.Summary = committed
	r.capacity.LogicalBytes += frameBytes
	if uint64(r.capacity.TailBytes)+frameBytes > ActiveSegmentBytes || r.capacity.Segments == 0 {
		r.capacity.Segments++
		r.capacity.TailBytes = uint32(frameBytes)
	} else {
		r.capacity.TailBytes += uint32(frameBytes)
	}
	state, capacity := r.workerSnapshot()
	if state != r.state || capacity != r.capacity {
		r.t.Fatal("committed capacity does not include the exact complete payment frame")
	}
}

type paymentResourceEvent struct {
	SchemaVersion int    `json:"schema_version"`
	Seq           int    `json:"seq"`
	Phase         string `json:"phase"`
	Height        uint64 `json:"height"`
	PaidBlocks    uint64 `json:"paid_blocks"`
	Processes     []struct {
		Role       string `json:"role"`
		Generation int    `json:"generation"`
		PID        int    `json:"pid"`
	} `json:"processes"`
	State struct {
		Commitments  uint64 `json:"commitments"`
		Nullifiers   uint64 `json:"nullifiers"`
		Fees         uint64 `json:"fees"`
		LogicalBytes uint64 `json:"logical_bytes"`
		Segments     uint32 `json:"segments"`
		TailBytes    uint32 `json:"tail_bytes"`
	} `json:"state"`
	Wallets []struct {
		RecordsUsed uint64 `json:"records_used"`
		FileBytes   uint64 `json:"file_bytes"`
	} `json:"wallets"`
	ElapsedMS int64 `json:"elapsed_ms"`
}

func (r *paymentResourceRun) checkpoint(phase string) {
	r.t.Helper()
	r.events++
	if r.events > 9 || r.worker.cmd.Process == nil || r.scenario.cmd.Process == nil {
		r.t.Fatal("resource checkpoint process identity is absent")
	}
	event := paymentResourceEvent{
		SchemaVersion: 1, Seq: r.events, Phase: phase,
		Height: r.state.Height, PaidBlocks: r.committed, ElapsedMS: time.Since(r.started).Milliseconds(),
	}
	for _, process := range []struct {
		role       string
		generation int
		pid        int
	}{{"worker", r.generation, r.worker.cmd.Process.Pid}, {"scenario", 1, r.scenario.cmd.Process.Pid}} {
		event.Processes = append(event.Processes, struct {
			Role       string `json:"role"`
			Generation int    `json:"generation"`
			PID        int    `json:"pid"`
		}{process.role, process.generation, process.pid})
	}
	event.State.Commitments = r.state.Commitments
	event.State.Nullifiers = r.state.Nullifiers
	event.State.Fees = r.state.Fees
	event.State.LogicalBytes = r.capacity.LogicalBytes
	event.State.Segments = r.capacity.Segments
	event.State.TailBytes = r.capacity.TailBytes
	for _, wallet := range r.wallets {
		event.Wallets = append(event.Wallets, struct {
			RecordsUsed uint64 `json:"records_used"`
			FileBytes   uint64 `json:"file_bytes"`
		}{wallet.Records, wallet.FileBytes})
	}
	paymentResourceWriteJSON(r.t, r.directory, fmt.Sprintf("event-%02d.json", r.events), event)
	deadline := time.NewTimer(15 * time.Second)
	defer deadline.Stop()
	poll := time.NewTicker(20 * time.Millisecond)
	defer poll.Stop()
	for {
		ackPath := filepath.Join(r.directory, fmt.Sprintf("ack-%02d.json", r.events))
		info, err := os.Lstat(ackPath)
		if err == nil {
			if !info.Mode().IsRegular() || info.Size() <= 0 || info.Size() > 65536 {
				r.t.Fatal("resource acknowledgment file is invalid")
			}
			file, err := os.Open(ackPath)
			if err != nil {
				r.t.Fatal("resource acknowledgment could not be opened")
			}
			opened, statErr := file.Stat()
			if statErr != nil || !os.SameFile(info, opened) {
				_ = file.Close()
				r.t.Fatal("resource acknowledgment file identity changed")
			}
			valid := paymentResourceAckValid(io.LimitReader(file, 65537), r.events)
			closeErr := file.Close()
			if !valid || closeErr != nil {
				r.t.Fatal("resource acknowledgment rejected or failed strict validation")
			}
			return
		}
		if !errors.Is(err, os.ErrNotExist) {
			r.t.Fatal("resource acknowledgment inspection failed")
		}
		select {
		case <-deadline.C:
			r.t.Fatal("resource checkpoint exceeded its 15 second acknowledgment budget")
		case <-r.ctx.Done():
			r.t.Fatal("resource stage deadline during checkpoint")
		case <-poll.C:
		}
	}
}

// JSON structs alone allow duplicate and case-insensitive keys. A successful
// acknowledgment must have exactly these three canonical keys once each;
// failed acknowledgments (with error_code) deliberately stop the Go test.
func paymentResourceAckValid(reader io.Reader, seq int) bool {
	decoder := json.NewDecoder(reader)
	start, err := decoder.Token()
	if err != nil || start != json.Delim('{') {
		return false
	}
	seen := map[string]bool{}
	var version, received int
	var ok bool
	for decoder.More() {
		key, err := decoder.Token()
		name, valid := key.(string)
		if err != nil || !valid || seen[name] {
			return false
		}
		seen[name] = true
		switch name {
		case "schema_version":
			err = decoder.Decode(&version)
		case "seq":
			err = decoder.Decode(&received)
		case "ok":
			err = decoder.Decode(&ok)
		default:
			return false
		}
		if err != nil {
			return false
		}
	}
	end, err := decoder.Token()
	if err != nil || end != json.Delim('}') {
		return false
	}
	var extra any
	return decoder.Decode(&extra) == io.EOF && len(seen) == 3 && version == 1 && received == seq && ok
}

// This independently counts physical frames; genuine Orchard authorization is
// still established by the worker and the separately reopened scenario store.
func paymentResourceCheckDisk(t *testing.T, path string, pin Hash, initial Summary, capacity ActiveStorage, transactions [][]byte, states []Summary) Hash {
	t.Helper()
	if len(states) != len(transactions) || uint64(len(transactions)) != capacity.Summary.Height {
		t.Fatal("physical resource inspection requires every submitted payment and Summary")
	}
	header, err := os.ReadFile(filepath.Join(path, "genesis"))
	network := sha256.Sum256([]byte(Network))
	if err != nil || len(header) != 140 || string(header[:8]) != "ZVOPOL03" || !bytes.Equal(header[8:40], network[:]) || !bytes.Equal(header[40:72], pin[:]) || binary.BigEndian.Uint32(header[72:76]) != 2 {
		t.Fatal("physical resource genesis header is not the pinned two-allocation active header")
	}
	entries, err := os.ReadDir(path)
	if err != nil || len(entries) != int(capacity.Segments)+1 {
		t.Fatal("physical resource segment count differs from capacity")
	}
	logical := uint64(len(header))
	previous := initial.AppHash
	var records, lastSize uint64
	for index := uint32(0); index < capacity.Segments; index++ {
		path := filepath.Join(path, fmt.Sprintf("%08d.journal", index))
		info, err := os.Lstat(path)
		if err != nil || !info.Mode().IsRegular() || info.Size() < EmptyRecordBytes || info.Size() > ActiveSegmentBytes {
			t.Fatal("physical resource segment size or kind is invalid")
		}
		raw, err := os.ReadFile(path)
		if err != nil || int64(len(raw)) != info.Size() {
			t.Fatal("physical resource segment read failed")
		}
		logical += uint64(len(raw))
		for offset := 0; offset < len(raw); {
			if len(raw)-offset < 4 {
				t.Fatal("physical resource frame prefix was split")
			}
			n := int(binary.BigEndian.Uint32(raw[offset : offset+4]))
			if n < 118 || n > len(raw)-offset-36 || records >= uint64(len(transactions)) {
				t.Fatal("physical resource frame is incomplete or outside the submitted history")
			}
			if offset == 0 && index != 0 && lastSize+uint64(n+36) <= ActiveSegmentBytes {
				t.Fatal("resource segment rotated before a full frame required it")
			}
			body := raw[offset+4 : offset+4+n]
			checksum := sha256.Sum256(body)
			height := records + 1
			hash := paymentResourceHash(height)
			tx := transactions[records]
			if string(body[:8]) != "ZVOBLK01" || binary.BigEndian.Uint64(body[8:16]) != height || !bytes.Equal(body[16:48], hash[:]) || !bytes.Equal(body[48:80], previous[:]) || !bytes.Equal(body[80:112], states[records].AppHash[:]) || !bytes.Equal(raw[offset+4+n:offset+36+n], checksum[:]) {
				t.Fatal("physical resource history hash, predecessor or checksum differs")
			}
			if binary.BigEndian.Uint16(body[112:114]) != 1 || n != 118+len(tx) || binary.BigEndian.Uint32(body[114:118]) != uint32(len(tx)) || !bytes.Equal(body[118:], tx) {
				t.Fatal("physical resource frame is not the exact single genuine payment")
			}
			copy(previous[:], body[80:112])
			records++
			offset += n + 36
		}
		lastSize = uint64(len(raw))
	}
	if records != uint64(len(transactions)) || records != capacity.Summary.Height || len(states) != len(transactions) || previous != capacity.Summary.AppHash || logical != capacity.LogicalBytes || lastSize != uint64(capacity.TailBytes) {
		t.Fatal("physical resource totals differ from the complete committed history")
	}
	return sha256.Sum256(header)
}

func TestActivePaymentResources32AndRecovery(t *testing.T) {
	// Fixed 32+1 real payments: no count/amount/budget overrides or synthetic
	// ledger state. OS resident/peak readings come from the Python supervisor.
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Minute)
	defer cancel()
	r := &paymentResourceRun{t: t, ctx: ctx, started: time.Now(), directory: os.Getenv("ZEVUNE_RESOURCE_HANDSHAKE_DIR")}
	info, err := os.Lstat(r.directory)
	if err != nil || !filepath.IsAbs(r.directory) || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		t.Fatal("new private resource handshake directory is required")
	}
	entries, err := os.ReadDir(r.directory)
	if err != nil || len(entries) != 0 {
		t.Fatal("resource handshake directory must start empty")
	}
	root := t.TempDir()
	walletHome := filepath.Join(root, "wallets")
	if err = os.Mkdir(walletHome, 0700); err != nil {
		t.Fatal("private resource wallet directory creation failed")
	}
	r.walletPath = [2]string{filepath.Join(walletHome, "actor-0.zwallet"), filepath.Join(walletHome, "actor-1.zwallet")}
	var pin Hash
	r.measure("scenario_start", 0, func() { pin = r.startScenario(walletHome) })
	initial := r.state
	manifest := filepath.Join(walletHome, "test-genesis.bin")
	rawGenesis, err := os.ReadFile(manifest)
	if err != nil || len(rawGenesis) != 312 || string(rawGenesis[:8]) != "ZVTGEN03" || sha256.Sum256(rawGenesis) != pin || ValidateTestGenesisFrame(rawGenesis) != nil {
		t.Fatal("resource scenario did not create the exact pinned active genesis")
	}
	workerExecutable := os.Getenv("ZEVUNE_POOL_WORKER")
	workerFile, err := os.Open(workerExecutable)
	if err != nil {
		t.Fatal("actual resource worker executable is required")
	}
	workerHash := sha256.New()
	n, hashErr := io.Copy(workerHash, io.LimitReader(workerFile, 512<<20+1))
	closeErr := workerFile.Close()
	if hashErr != nil || closeErr != nil || n < 1 || n > 512<<20 {
		t.Fatal("actual resource worker digest could not be computed")
	}
	var executablePin Hash
	copy(executablePin[:], workerHash.Sum(nil))
	path := filepath.Join(root, "active-ledger")
	options := Options{
		Executable: workerExecutable, ExpectedSHA256: executablePin, Journal: path,
		TestGenesis: manifest, TestGenesisSHA256: pin,
		StartupTimeout: time.Minute, RequestTimeout: time.Minute,
	}
	startWorker := func(create bool) {
		t.Helper()
		options.Create = create
		client, err := Start(ctx, options)
		if err != nil {
			t.Fatal("real resource worker startup or full replay failed its 60 second budget")
		}
		r.worker = client
		r.generation++
		t.Cleanup(func() { _ = client.Close() })
		if client.Profile() != ActiveSegmentsV1 || client.Profile().MaxHeight() != 1000000 || client.Profile().MaxJournalBytes() != 1073741824 || ActiveSegmentBytes != 1048576 || ActiveMaxSegments != 2048 {
			t.Fatal("resource test changed the fixed active storage profile")
		}
		state, capacity := r.workerSnapshot()
		if state != r.state {
			t.Fatal("new worker full replay differs from the independent scenario Summary")
		}
		if create {
			if capacity.LogicalBytes != 140 || capacity.Segments != 0 || capacity.TailBytes != 0 {
				t.Fatal("resource genesis capacity is not exact")
			}
			r.capacity = capacity
		} else if capacity != r.capacity {
			t.Fatal("reopened worker full replay changed exact capacity")
		}
	}
	r.measure("worker_create", 0, func() { startWorker(true) })
	r.measure("wallet_sync", 0, func() { r.wallets = r.walletStatus(0, false) })
	r.checkpoint("genesis")
	var transactions [][]byte
	var states []Summary
	var headerDigest Hash
	for payment := uint64(1); payment <= 33; payment++ {
		if err = ctx.Err(); err != nil {
			t.Fatal("resource payment sequence exceeded its fixed 20 minute budget")
		}
		if payment == 33 {
			r.measure("worker_close", 0, func() {
				if err = r.worker.Close(); err != nil {
					t.Fatal("first generation resource worker close failed")
				}
			})
			r.measure("disk_check", 0, func() {
				headerDigest = paymentResourceCheckDisk(t, path, pin, initial, r.capacity, transactions, states)
			})
			r.measure("worker_reopen", 0, func() { startWorker(false) })
			r.checkpoint("worker_reopened_32")
			r.measure("wallet_recover", 0, func() {
				r.walletPath = [2]string{filepath.Join(walletHome, "backup-1-0.zwallet"), filepath.Join(walletHome, "backup-2-1.zwallet")}
				if r.walletStatus(5, false) != r.wallets {
					t.Fatal("independent ledger and receipt-bound wallet recovery changed complete state")
				}
			})
			r.checkpoint("wallet_recovered_32")
		}
		var tx []byte
		r.measure("prepare", payment, func() {
			tx = r.call(1, nil)
			if len(tx) < 98 || len(tx) > MaxTransactionBytes || string(tx[:8]) != "ZVORLAB2" || !bytes.Equal(tx[8:40], pin[:]) || binary.BigEndian.Uint64(tx[40:48]) != r.state.Height+100 || binary.BigEndian.Uint64(tx[48:56]) != 1000 || binary.BigEndian.Uint64(tx[56:64]) != 1000 || tx[96] != 2 {
				t.Fatal("real resource payment lost its exact domain, expiry, fee or two-action policy")
			}
			r.wallets = r.walletStatus(0, true)
		})
		if payment == 33 {
			r.measure("outbox_restore", 33, func() {
				if restored := r.call(4, []byte{0}); !bytes.Equal(restored, tx) {
					t.Fatal("restored encrypted outbox did not preserve the newly prepared 33rd payment bytes")
				}
				r.walletPath[0] = filepath.Join(walletHome, "backup-3-0.zwallet")
				if r.walletStatus(0, true) != r.wallets || r.wallets[0].Records != 51 || r.wallets[1].Records != 50 {
					t.Fatal("exact outbox recovery changed wallet records, bytes or reservation")
				}
			})
			r.checkpoint("pending_restored_33")
		}
		var preview Summary
		r.measure("candidate", payment, func() { preview = r.candidate(path, tx) })
		r.measure("worker_commit", payment, func() { r.commit(path, tx, preview, transactions) })
		transactions = append(transactions, bytes.Clone(tx))
		states = append(states, r.state)
		r.measure("scenario_apply", payment, func() {
			raw, err := r.worker.BlockBytes(payment, paymentResourceHash(payment), [][]byte{tx})
			if err != nil || r.summary(r.call(2, raw)) != r.state {
				t.Fatal("independent genuine scenario prepare/commit differs from the worker Summary")
			}
		})
		r.measure("wallet_sync", payment, func() {
			op := byte(0)
			if payment == 33 {
				op = 6 // The fixed finish assertions include the same full history sync.
			}
			r.wallets = r.walletStatus(op, false)
		})
		if payment%8 == 0 || payment == 33 {
			r.measure("duplicate_rejection", 0, func() { r.rejectSpent(path, transactions, false) })
			phase := fmt.Sprintf("payment_%d", payment)
			if payment == 33 {
				phase = "complete_33"
			}
			r.checkpoint(phase)
		}
	}
	r.measure("worker_close", 0, func() {
		if err = r.worker.Close(); err != nil {
			t.Fatal("second generation resource worker close failed")
		}
	})
	r.measure("disk_check", 0, func() {
		if paymentResourceCheckDisk(t, path, pin, initial, r.capacity, transactions, states) != headerDigest {
			t.Fatal("resource immutable genesis header changed across recovery and the 33rd payment")
		}
	})
	r.measure("finish", 0, r.closeScenario)
	if t.Failed() || r.events != 9 || r.state.Height != 33 || r.state.Commitments != 68 || r.state.Nullifiers != 66 || r.state.Fees != 33000 || r.wallets[0].Records != 52 || r.wallets[1].Records != 51 || r.wallets[0].Pending || r.wallets[1].Pending {
		t.Fatal("resource baseline did not complete the fixed 32+1 payment acceptance")
	}
	checks := map[string]bool{}
	for _, name := range []string{
		"genuine_payments", "summary_agreement", "capacity_accounting", "wallet_records", "wallet_file_bytes", "physical_frames",
		"worker_full_replay", "scenario_full_replay", "wallet_backup_recovery", "post_recovery_payment", "exact_outbox_recovery",
		"rejection_nonmutation", "pending_commit_preserved", "pending_cleared",
	} {
		checks[name] = true
	}
	paymentResourceWriteJSON(t, r.directory, "result.json", map[string]any{
		"schema_version": 1, "complete": true, "paid_blocks": 33, "height": 33, "actions_per_payment": 2,
		"commitments": r.state.Commitments, "nullifiers": r.state.Nullifiers, "fees": r.state.Fees,
		"logical_bytes": r.capacity.LogicalBytes, "segments": r.capacity.Segments, "tail_bytes": r.capacity.TailBytes,
		"wallet_records": [2]uint64{r.wallets[0].Records, r.wallets[1].Records}, "wallet_bytes": [2]uint64{r.wallets[0].FileBytes, r.wallets[1].FileBytes},
		"checks": checks, "timings": map[string]any{"total_ms": time.Since(r.started).Milliseconds(), "operations": r.operations},
	})
	t.Log("PAYMENT_RESOURCE_RESULT paid_blocks=33 actions_per_payment=2 commitments=68 nullifiers=66 fees=33000; complete Summary/capacity, full replay, receipt-bound wallets, exact outbox, physical frames and rejection non-mutation passed")
}
