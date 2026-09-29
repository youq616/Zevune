package labnet

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

const socksTestHost = "pg6mmjiyjmcrsslvykfwnntlaru7p5svn6y2ymmju6nubxndf4pscryd.onion"

// A real local TCP fixture. It never resolves or forwards the example onion
// address, starts Tor, or handles a genuine wallet/validator secret.
func socksFixture(t *testing.T, count int, serve func(net.Conn) error) (string, <-chan error) {
	t.Helper()
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = listener.Close() })
	done := make(chan error, 1)
	go func() {
		defer listener.Close()
		for i := 0; i < count; i++ {
			conn, err := listener.Accept()
			if err != nil {
				done <- err
				return
			}
			_ = conn.SetDeadline(time.Now().Add(12 * time.Second))
			err = serve(conn)
			_ = conn.Close()
			if err != nil {
				done <- err
				return
			}
		}
		done <- nil
	}()
	return listener.Addr().String(), done
}

func socksFixtureDone(t *testing.T, done <-chan error) {
	t.Helper()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(15 * time.Second):
		t.Fatal("SOCKS fixture did not terminate")
	}
}

func socksExpect(conn net.Conn, expected []byte) error {
	got := make([]byte, len(expected))
	if _, err := io.ReadFull(conn, got); err != nil {
		return err
	}
	if !bytes.Equal(got, expected) {
		return errors.New("unexpected SOCKS frame (contents suppressed)")
	}
	return nil
}

func socksExpectClosed(conn net.Conn) error {
	var b [1]byte
	n, err := conn.Read(b[:])
	if n != 0 || err == nil {
		return errors.New("client sent data after rejected handshake")
	}
	if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
		return errors.New("client did not close rejected handshake")
	}
	return nil
}

func socksTestDialer(proxy string) *onionDialer {
	return &onionDialer{proxy: proxy, host: socksTestHost, port: 8080, isolation: strings.Repeat("a", 64)}
}

func socksAuthFrame(d *onionDialer) []byte {
	out := append([]byte{1, 9}, []byte("<torS0X>0")...)
	out = append(out, 64)
	return append(out, []byte(d.isolation)...)
}

func socksConnectFrame(d *onionDialer) []byte {
	out := append([]byte{5, 1, 0, 3, 62}, []byte(d.host)...)
	return binary.BigEndian.AppendUint16(out, d.port)
}

func socksAcceptRequest(conn net.Conn, d *onionDialer) error {
	if err := socksExpect(conn, []byte{5, 1, 2}); err != nil {
		return err
	}
	if err := writeSOCKS(conn, []byte{5, 2}); err != nil {
		return err
	}
	if err := socksExpect(conn, socksAuthFrame(d)); err != nil {
		return err
	}
	if err := writeSOCKS(conn, []byte{1, 0}); err != nil {
		return err
	}
	return socksExpect(conn, socksConnectFrame(d))
}

func TestPrivateSOCKSExactFramesAndAllReplyAddressTypes(t *testing.T) {
	replies := [][]byte{
		{5, 0, 0, 1, 127, 0, 0, 1, 0, 1},
		append([]byte{5, 0, 0, 4}, make([]byte, 18)...),
		{5, 0, 0, 3, 3, 'b', 'n', 'd', 0, 1},
		append(append([]byte{5, 0, 0, 3, 255}, bytes.Repeat([]byte{'x'}, 255)...), 0, 1),
	}
	for i, reply := range replies {
		t.Run(strconv.Itoa(i), func(t *testing.T) {
			d := socksTestDialer("")
			proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
				if err := socksAcceptRequest(conn, d); err != nil {
					return err
				}
				// Fragment the response, including lengths/port. The marker after
				// it must remain available to the caller, not swallowed as SOCKS.
				for _, b := range append(append([]byte{}, reply...), 'R') {
					if err := writeSOCKS(conn, []byte{b}); err != nil {
						return err
					}
				}
				return socksExpect(conn, []byte("application"))
			})
			d.proxy = proxy
			ctx, cancel := context.WithCancel(context.Background())
			conn, err := d.dialContext(ctx, "tcp", net.JoinHostPort(d.host, "8080"))
			cancel() // the finished handshake watcher must no longer own conn.
			if err != nil {
				t.Fatal(err)
			}
			defer conn.Close()
			if err := socksExpect(conn, []byte{'R'}); err != nil {
				t.Fatal(err)
			}
			if err := writeSOCKS(conn, []byte("application")); err != nil {
				t.Fatal(err)
			}
			socksFixtureDone(t, done)
		})
	}
}

func TestPrivateSOCKSRejectsDowngradeAndAuthenticationFailure(t *testing.T) {
	for _, reply := range [][]byte{{5, 0}, {5, 255}, {4, 2}, {5, 1}, {5, 128}} {
		t.Run(fmt.Sprintf("method_%x", reply), func(t *testing.T) {
			proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
				if err := socksExpect(conn, []byte{5, 1, 2}); err != nil {
					return err
				}
				if err := writeSOCKS(conn, reply); err != nil {
					return err
				}
				return socksExpectClosed(conn)
			})
			d := socksTestDialer(proxy)
			conn, err := d.dialContext(context.Background(), "tcp", net.JoinHostPort(d.host, "8080"))
			if conn != nil || err != errPrivateSOCKS {
				t.Fatalf("unexpected rejection result: %v", err)
			}
			socksFixtureDone(t, done)
		})
	}
	for _, reply := range [][]byte{{1, 1}, {1, 255}, {5, 0}, {0, 0}} {
		t.Run(fmt.Sprintf("auth_%x", reply), func(t *testing.T) {
			d := socksTestDialer("")
			proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
				if err := socksExpect(conn, []byte{5, 1, 2}); err != nil {
					return err
				}
				if err := writeSOCKS(conn, []byte{5, 2}); err != nil {
					return err
				}
				if err := socksExpect(conn, socksAuthFrame(d)); err != nil {
					return err
				}
				if err := writeSOCKS(conn, reply); err != nil {
					return err
				}
				return socksExpectClosed(conn)
			})
			d.proxy = proxy
			conn, err := d.dialContext(context.Background(), "tcp", net.JoinHostPort(d.host, "8080"))
			if conn != nil || err != errPrivateSOCKS {
				t.Fatal("authentication failure accepted")
			}
			socksFixtureDone(t, done)
		})
	}
}

func TestPrivateSOCKSRejectsEveryTruncatedReplyAndBadConnect(t *testing.T) {
	full := []byte{5, 0, 0, 1, 127, 0, 0, 1, 0, 1}
	for stage := 0; stage < 3; stage++ {
		response := [][]byte{{5, 2}, {1, 0}, full}[stage]
		for cut := 0; cut < len(response); cut++ {
			t.Run(fmt.Sprintf("stage_%d_cut_%d", stage, cut), func(t *testing.T) {
				d := socksTestDialer("")
				proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
					requests := [][]byte{{5, 1, 2}, socksAuthFrame(d), socksConnectFrame(d)}
					replies := [][]byte{{5, 2}, {1, 0}, full}
					for s := 0; s <= stage; s++ {
						if err := socksExpect(conn, requests[s]); err != nil {
							return err
						}
						if s == stage {
							return writeSOCKS(conn, replies[s][:cut])
						}
						if err := writeSOCKS(conn, replies[s]); err != nil {
							return err
						}
					}
					return nil
				})
				d.proxy = proxy
				conn, err := d.dialContext(context.Background(), "tcp", net.JoinHostPort(d.host, "8080"))
				if conn != nil || err != errPrivateSOCKS {
					t.Fatal("truncated response accepted")
				}
				socksFixtureDone(t, done)
			})
		}
	}
	for i, reply := range [][]byte{{4, 0, 0, 1}, {5, 1, 0, 1}, {5, 0xf0, 0, 1}, {5, 0, 1, 1}, {5, 0, 0, 0}, {5, 0, 0, 3, 0}, {5, 0, 0, 3, 2, 'x'}, {5, 0, 0, 4, 0}} {
		t.Run(fmt.Sprintf("bad_connect_%d", i), func(t *testing.T) {
			d := socksTestDialer("")
			proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
				if err := socksAcceptRequest(conn, d); err != nil {
					return err
				}
				return writeSOCKS(conn, reply)
			})
			d.proxy = proxy
			conn, err := d.dialContext(context.Background(), "tcp", net.JoinHostPort(d.host, "8080"))
			if conn != nil || err != errPrivateSOCKS {
				t.Fatal("malformed CONNECT accepted")
			}
			socksFixtureDone(t, done)
		})
	}
}

func TestPrivateSOCKSCancellationClosesRealSocketAtEachStage(t *testing.T) {
	for stage := 0; stage < 3; stage++ {
		t.Run(strconv.Itoa(stage), func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			d := socksTestDialer("")
			proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
				requests := [][]byte{{5, 1, 2}, socksAuthFrame(d), socksConnectFrame(d)}
				replies := [][]byte{{5, 2}, {1, 0}}
				for s := 0; s <= stage; s++ {
					if err := socksExpect(conn, requests[s]); err != nil {
						return err
					}
					if s == stage {
						cancel() // after the real read, not a synthetic elapsed clock.
						return socksExpectClosed(conn)
					}
					if err := writeSOCKS(conn, replies[s]); err != nil {
						return err
					}
				}
				return nil
			})
			d.proxy = proxy
			conn, err := d.dialContext(ctx, "tcp", net.JoinHostPort(d.host, "8080"))
			if conn != nil || err != errPrivateSOCKS {
				t.Fatal("cancelled handshake accepted")
			}
			socksFixtureDone(t, done)
		})
	}
}

func TestPrivateSOCKSHandshakeUsesRealBoundedDeadline(t *testing.T) {
	d := socksTestDialer("")
	proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
		if err := socksExpect(conn, []byte{5, 1, 2}); err != nil {
			return err
		}
		return socksExpectClosed(conn) // stall until the production deadline.
	})
	d.proxy = proxy
	start := time.Now()
	conn, err := d.dialContext(context.Background(), "tcp", net.JoinHostPort(d.host, "8080"))
	elapsed := time.Since(start)
	if conn != nil || err != errPrivateSOCKS || elapsed < 4*time.Second || elapsed > 10*time.Second {
		t.Fatalf("deadline result %v after %s", err, elapsed)
	}
	socksFixtureDone(t, done)
}

func TestPrivateSOCKSRejectsWrongDialTargetBeforeConnecting(t *testing.T) {
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	d := socksTestDialer(listener.Addr().String())
	for _, input := range [][2]string{{"tcp4", net.JoinHostPort(d.host, "8080")}, {"udp", net.JoinHostPort(d.host, "8080")}, {"tcp", "127.0.0.1:8080"}, {"tcp", d.host + ":80"}, {"tcp", "example.org:8080"}} {
		conn, err := d.dialContext(context.Background(), input[0], input[1])
		if conn != nil || err != errPrivateSOCKS {
			t.Fatal("incorrect dial target accepted")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	for _, ctx := range []context.Context{ctx, nil} {
		if c, e := d.dialContext(ctx, "tcp", net.JoinHostPort(d.host, "8080")); c != nil || e != errPrivateSOCKS {
			t.Fatal("invalid context accepted")
		}
	}
	_ = listener.(*net.TCPListener).SetDeadline(time.Now().Add(30 * time.Millisecond))
	if c, err := listener.Accept(); err == nil {
		c.Close()
		t.Fatal("invalid input caused a connection")
	} else if ne, ok := err.(net.Error); !ok || !ne.Timeout() {
		t.Fatal(err)
	}
}

func TestPrivateSOCKSReconnectAndConcurrentDial(t *testing.T) {
	d := socksTestDialer("")
	proxy, done := socksFixture(t, 8, func(conn net.Conn) error {
		if err := socksAcceptRequest(conn, d); err != nil {
			return err
		}
		return writeSOCKS(conn, []byte{5, 0, 0, 1, 0, 0, 0, 0, 0, 0})
	})
	d.proxy = proxy
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			conn, err := d.dialContext(context.Background(), "tcp", net.JoinHostPort(d.host, "8080"))
			if err != nil {
				t.Error(err)
				return
			}
			conn.Close()
		}()
	}
	wg.Wait()
	socksFixtureDone(t, done)
}

type socksShortWriter struct{ bytes.Buffer }

func (w *socksShortWriter) Write(b []byte) (int, error) { return w.Buffer.Write(b[:1]) }

type socksZeroWriter struct{}

func (socksZeroWriter) Write([]byte) (int, error) { return 0, nil }

func TestPrivateSOCKSWriteHandlesShortWrites(t *testing.T) {
	w := &socksShortWriter{}
	if err := writeSOCKS(w, []byte("abc")); err != nil || w.String() != "abc" {
		t.Fatal("short writes lost data")
	}
	if err := writeSOCKS(socksZeroWriter{}, []byte("a")); err != errPrivateSOCKS {
		t.Fatal("zero progress write accepted")
	}
}

func TestPrivateSOCKSRestoresDetachedRequestCancellation(t *testing.T) {
	for _, timeout := range []bool{false, true} {
		t.Run(strconv.FormatBool(timeout), func(t *testing.T) {
			original, cancel := context.WithCancel(context.Background())
			if timeout {
				cancel()
				original, cancel = context.WithTimeout(context.Background(), 300*time.Millisecond)
			}
			defer cancel()
			// Match net/http's real getConn context operation: cancellation and
			// deadline are detached, only the request-context VALUE survives.
			detached := context.WithoutCancel(context.WithValue(original, privateRPCRequestContextKey{}, original))
			proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
				if err := socksExpect(conn, []byte{5, 1, 2}); err != nil {
					return err
				}
				if !timeout {
					cancel()
				}
				return socksExpectClosed(conn)
			})
			d := socksTestDialer(proxy)
			start := time.Now()
			conn, err := d.dialContext(detached, "tcp", net.JoinHostPort(d.host, "8080"))
			if conn != nil || err != errPrivateSOCKS || time.Since(start) > 2*time.Second {
				t.Fatal("original lifecycle was lost during detached dialing")
			}
			socksFixtureDone(t, done)
		})
	}
}
