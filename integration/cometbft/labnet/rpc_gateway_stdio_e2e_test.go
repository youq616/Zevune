//go:build operator_e2e

package labnet

import (
	"bufio"
	"encoding/json"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"github.com/youq616/Zevune/internal/rpcgate"
	"github.com/youq616/Zevune/internal/rpcgate/gatetest"
)

// Actual command with inherited *os.File handles, not os/exec copying writers
// or a test-program replacement. Wait finishes before peer endpoints are closed
// or drained in failure assertions. The sole Wait goroutine is always joined.
type gatewayCommand struct {
	cmd                   *exec.Cmd
	input, output, errors *os.File
	child                 []*os.File
	all                   []*os.File
	done                  chan error
	started, waited       bool
	startedAt             time.Time
}

func newGatewayCommand(t *testing.T, args []string) *gatewayCommand {
	t.Helper()
	p := &gatewayCommand{cmd: exec.Command(requiredExecutable(t, "ZEVUNE_RPC_GATEWAY"), args...), done: make(chan error, 1)}
	t.Cleanup(func() {
		if p.started && !p.waited {
			p.cmd.Process.Kill()
			<-p.done
			p.waited = true
		}
		for _, f := range p.all {
			f.Close()
		}
	})
	pipe := func() (*os.File, *os.File) {
		r, w, err := gatetest.Pipe()
		if err != nil {
			t.Fatal(err)
		}
		p.all = append(p.all, r, w)
		return r, w
	}
	in, input := pipe()
	output, out := pipe()
	stderr, errOut := pipe()
	p.input, p.output, p.errors = input, output, stderr
	p.cmd.Stdin, p.cmd.Stdout, p.cmd.Stderr = in, out, errOut
	p.child = []*os.File{in, out, errOut}
	return p
}

func (p *gatewayCommand) start(t *testing.T) {
	t.Helper()
	p.startedAt = time.Now()
	if err := p.cmd.Start(); err != nil {
		t.Fatal(err)
	}
	p.started = true
	for _, f := range p.child {
		f.Close() // release only the parent's copies of the CHILD endpoints
	}
	go func() { p.done <- p.cmd.Wait() }()
}

func (p *gatewayCommand) wait(t *testing.T, budget time.Duration, success bool) {
	t.Helper()
	select {
	case err := <-p.done:
		p.waited = true
		if (err == nil) != success {
			t.Fatal("gateway exit status", err)
		}
	case <-time.After(budget):
		p.cmd.Process.Kill()
		<-p.done
		p.waited = true
		t.Fatal("gateway did not exit before parent pipe intervention")
	}
}

func (p *gatewayCommand) ready(t *testing.T) {
	t.Helper()
	if err := p.output.SetReadDeadline(time.Now().Add(4 * time.Second)); err != nil {
		t.Fatal(err)
	}
	line, err := bufio.NewReader(io.LimitReader(p.output, 512)).ReadString('\n')
	if err != nil || line != rpcgate.ReadyRecord {
		t.Fatal("actual gateway readiness failed", err)
	}
	p.output.SetReadDeadline(time.Time{})
}

func gatewayListenerClosed(t *testing.T, address string) {
	t.Helper()
	c, err := net.DialTimeout("tcp4", address, 200*time.Millisecond)
	if err == nil {
		c.Close()
		t.Fatal("gateway retained listening socket after exit")
	}
}

func gatewayListenerOpened(t *testing.T, address string) {
	t.Helper()
	end := time.Now().Add(1500 * time.Millisecond)
	for {
		c, err := net.DialTimeout("tcp4", address, 100*time.Millisecond)
		if err == nil {
			c.Close()
			return
		}
		if time.Now().After(end) {
			t.Fatal("gateway never opened listener before ready write timeout")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func fillGatewayPipe(t *testing.T, w *os.File) {
	t.Helper()
	written, err := gatetest.Saturate(w)
	if err != nil || written <= 0 {
		t.Fatal("full-pipe precondition not established", written, err)
	}
	t.Logf("completed_fill_bytes=%d; parent will not drain before child exits", written)
}

func gatewayFixedFailure(t *testing.T, p *gatewayCommand) {
	t.Helper()
	if !p.waited {
		t.Fatal("must check exit before draining stderr")
	}
	raw, err := io.ReadAll(io.LimitReader(p.errors, 512))
	if err != nil || string(raw) != rpcgate.FailureRecord {
		t.Fatal("noncanonical failure output", err)
	}
}

func gatewayLifecycleConfig(t *testing.T) (string, string) {
	t.Helper()
	root := t.TempDir()
	walletHome := filepath.Join(root, "wallets")
	if err := os.Mkdir(walletHome, 0700); err != nil {
		t.Fatal(err)
	}
	driver := launch(t, requiredExecutable(t, "ZEVUNE_FUNDED_SCENARIO"), walletHome)
	ready := driver.frame(t)
	if len(ready) != 128 {
		t.Fatal("real funded scenario frame")
	}
	var assetPin Hash
	copy(assetPin[:], ready[:32])
	worker := requiredExecutable(t, "ZEVUNE_POOL_WORKER")
	home := filepath.Join(root, "network")
	args := []string{"init", "--no-real-funds", "--worker", worker, "--worker-sha256", HashText(executablePin(t, worker)), "--home", home, "--genesis", filepath.Join(walletHome, "test-genesis.bin"), "--genesis-sha256", HashText(assetPin)}
	var initialized struct {
		Pin string `json:"config_sha256"`
	}
	if err := json.Unmarshal(operator(t, args, true), &initialized); err != nil {
		t.Fatal(err)
	}
	return filepath.Join(home, configName), initialized.Pin
}

func TestRealGatewayInheritedStandardStreamLifecycle(t *testing.T) {
	config, pin := gatewayLifecycleConfig(t)
	argsFor := func(address string) []string {
		return []string{"--no-real-funds", "--config", config, "--config-sha256", pin, "--listen", address, "--upstream", "http://" + gatewayTestAddress(t), "--onion-endpoint", privateTestEndpoint, "--stop-on-stdin-eof"}
	}
	t.Run("stdin_open_cancel_signal", func(t *testing.T) {
		address := gatewayTestAddress(t)
		p := newGatewayCommand(t, argsFor(address))
		prepareGatewaySignal(t, p.cmd)
		p.start(t)
		p.ready(t)
		signalGateway(t, p.cmd)
		p.wait(t, 2*time.Second, true)
		gatewayListenerClosed(t, address)
		// p.input has never been closed or written. No EOF helped this exit.
	})
	t.Run("stdout_full_ready_timeout", func(t *testing.T) {
		address := gatewayTestAddress(t)
		p := newGatewayCommand(t, argsFor(address))
		fillGatewayPipe(t, p.cmd.Stdout.(*os.File))
		p.start(t)
		gatewayListenerOpened(t, address)
		p.wait(t, 5*time.Second, false)
		if time.Since(p.startedAt) < 1800*time.Millisecond {
			t.Fatal("did not exercise the ready write budget")
		}
		gatewayListenerClosed(t, address)
		gatewayFixedFailure(t, p)
		// stdout has not been read; stdin's writer and stdout's reader remain open.
	})
	t.Run("stderr_full_failure_timeout", func(t *testing.T) {
		address := gatewayTestAddress(t)
		args := append(argsFor(address), "--unknown-flag")
		p := newGatewayCommand(t, args)
		fillGatewayPipe(t, p.cmd.Stderr.(*os.File))
		p.start(t)
		p.wait(t, 4*time.Second, false)
		if time.Since(p.startedAt) < 800*time.Millisecond {
			t.Fatal("did not exercise failure output budget")
		}
		gatewayListenerClosed(t, address)
		// No draining of stderr and no EOF on stdin took place before Wait.
	})
	t.Run("stdin_open_listen_failure", func(t *testing.T) {
		address := gatewayTestAddress(t)
		occupied, err := net.Listen("tcp4", address)
		if err != nil {
			t.Fatal(err)
		}
		defer occupied.Close()
		p := newGatewayCommand(t, argsFor(address))
		p.start(t)
		p.wait(t, 2*time.Second, false)
		gatewayFixedFailure(t, p)
		// The PARENT listener was never acquired/closed by the failed command.
		c, err := net.DialTimeout("tcp4", address, time.Second)
		if err != nil {
			t.Fatal("failed startup changed unrelated listener", err)
		}
		c.Close()
		occupied.Close()
		gatewayListenerClosed(t, address)
	})
	for _, stream := range []string{"stdin", "stdout", "stderr"} {
		t.Run("unsupported_file_"+stream, func(t *testing.T) {
			address := gatewayTestAddress(t)
			p := newGatewayCommand(t, argsFor(address))
			path := filepath.Join(t.TempDir(), "unsupported")
			f, err := os.Create(path)
			if err != nil {
				t.Fatal(err)
			}
			p.child, p.all = append(p.child, f), append(p.all, f)
			switch stream {
			case "stdin":
				p.cmd.Stdin = f
			case "stdout":
				p.cmd.Stdout = f
			case "stderr":
				p.cmd.Stderr = f
			}
			p.start(t)
			p.wait(t, 2*time.Second, false)
			gatewayListenerClosed(t, address)
			if raw, err := os.ReadFile(path); err != nil || len(raw) != 0 {
				t.Fatal("unsupported stream was written")
			}
			if stream != "stderr" {
				gatewayFixedFailure(t, p)
			}
		})
	}
	for _, stream := range []string{"stdin", "stdout", "stderr"} {
		t.Run("wrong_direction_pipe_"+stream, func(t *testing.T) {
			address := gatewayTestAddress(t)
			p := newGatewayCommand(t, argsFor(address))
			r, w, err := gatetest.Pipe() // Windows: genuine overlapped handles
			if err != nil {
				t.Fatal(err)
			}
			p.all = append(p.all, r, w)
			if stream == "stdin" {
				p.cmd.Stdin = w // only FILE_WRITE_DATA, no FILE_READ_DATA
				p.child = append(p.child, w)
			} else if stream == "stdout" {
				p.cmd.Stdout = r // only FILE_READ_DATA, no FILE_WRITE_DATA
				p.child = append(p.child, r)
			} else {
				p.cmd.Stderr = r
				p.child = append(p.child, r)
			}
			p.start(t)
			p.wait(t, 2*time.Second, false)
			gatewayListenerClosed(t, address)
			// Read output only AFTER the nonzero exit. All peer endpoints have
			// remained open; no EOF, drain or successful signal helped the exit.
			if err := p.output.SetReadDeadline(time.Now().Add(time.Second)); err != nil {
				t.Fatal(err)
			}
			raw, err := io.ReadAll(io.LimitReader(p.output, 512))
			if err != nil || len(raw) != 0 {
				t.Fatal("wrong-direction command emitted readiness", err)
			}
			if stream != "stderr" {
				gatewayFixedFailure(t, p)
			}
			// Absence of a transient bind cannot be proved by a post-exit dial:
			// the additional owner tests assert ErrConfiguration, and execute's
			// checked OpenInput/OpenOutput calls precede RunGateway/Start.
		})
	}

	if runtime.GOOS == "windows" {
		for _, stream := range []string{"stdin", "stdout", "stderr"} {
			t.Run("unsupported_synchronous_pipe_"+stream, func(t *testing.T) {
				address := gatewayTestAddress(t)
				p := newGatewayCommand(t, argsFor(address))
				r, w, err := os.Pipe() // synchronous CreatePipe, deliberately unsupported
				if err != nil {
					t.Fatal(err)
				}
				p.all = append(p.all, r, w)
				if stream == "stdin" {
					p.cmd.Stdin = r
					p.child = append(p.child, r)
				} else if stream == "stdout" {
					p.cmd.Stdout = w
					p.child = append(p.child, w)
				} else {
					p.cmd.Stderr = w
					p.child = append(p.child, w)
				}
				p.start(t)
				p.wait(t, 2*time.Second, false)
				gatewayListenerClosed(t, address)
				if stream != "stderr" {
					gatewayFixedFailure(t, p)
				}
			})
		}
	}
}
