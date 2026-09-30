package rpcgate

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

const testHost = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.onion:80"

type testBackend struct {
	calls  atomic.Int64
	action func(context.Context, string, int64, []byte) (json.RawMessage, error)
}

func (b *testBackend) call(ctx context.Context, m string, h int64, tx []byte) (json.RawMessage, error) {
	b.calls.Add(1)
	if b.action != nil {
		return b.action(ctx, m, h, tx)
	}
	return json.RawMessage(`{"height":"7","bytes":"AA=="}`), nil
}
func (b *testBackend) Status(ctx context.Context) (string, int64, error) {
	_, err := b.call(ctx, "status", 0, nil)
	return "test-chain", 7, err
}
func (b *testBackend) Block(ctx context.Context, h int64) (json.RawMessage, error) {
	return b.call(ctx, "block", h, nil)
}
func (b *testBackend) Commit(ctx context.Context, h int64) (json.RawMessage, error) {
	return b.call(ctx, "commit", h, nil)
}
func (b *testBackend) Broadcast(ctx context.Context, tx []byte) (uint32, []byte, error) {
	_, err := b.call(ctx, "broadcast_tx_sync", 0, tx)
	return 0, bytes.Repeat([]byte{0xab}, 32), err
}

func freeAddress(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := l.Addr().String()
	l.Close()
	return address
}
func startTest(t *testing.T, b Backend) (*Service, string) {
	t.Helper()
	c := Config{Listen: freeAddress(t), Host: testHost, MaxHeight: 1000000}
	s, err := Start(context.Background(), c, b)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		s.Stop()
		done := make(chan error, 1)
		go func() { done <- s.Wait() }()
		select {
		case err := <-done:
			if err != nil {
				t.Error(err)
			}
		case <-time.After(3 * time.Second):
			t.Error("service did not stop")
		}
	})
	return s, c.Listen
}
func dial(t *testing.T, address string) net.Conn {
	t.Helper()
	c, err := net.DialTimeout("tcp4", address, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { c.Close() })
	c.SetDeadline(time.Now().Add(3 * time.Second))
	return c
}
func send(t *testing.T, address, request string) (*http.Response, []byte) {
	t.Helper()
	c := dial(t, address)
	if _, err := io.WriteString(c, request); err != nil {
		t.Fatal(err)
	}
	r, err := http.ReadResponse(bufio.NewReader(c), nil)
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(r.Body)
	r.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	c.Close()
	return r, body
}
func httpRequest(body string) string {
	return fmt.Sprintf("POST / HTTP/1.1\r\nHost: %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s", testHost, len(body), body)
}
func eventually(t *testing.T, predicate func() bool) {
	t.Helper()
	until := time.Now().Add(time.Second)
	for !predicate() {
		if time.Now().After(until) {
			t.Fatal("condition not reached")
		}
		time.Sleep(time.Millisecond)
	}
}

func TestFourMethodsAndMinimalWireTypes(t *testing.T) {
	b := &testBackend{}
	_, address := startTest(t, b)
	tests := []struct{ method, params, want string }{
		{"status", `{}`, `{"node_info":{"network":"test-chain"},"sync_info":{"latest_block_height":"7"}}`},
		{"block", `{"height":"1"}`, `{"height":"7","bytes":"AA=="}`},
		{"commit", `{"height":"1"}`, `{"height":"7","bytes":"AA=="}`},
		{"broadcast_tx_sync", `{"tx":"AA=="}`, `{"code":0,"hash":"` + strings.Repeat("AB", 32) + `"}`},
	}
	for _, tt := range tests {
		r, raw := send(t, address, httpRequest(wire(tt.method, tt.params)))
		want := `{"jsonrpc":"2.0","id":0,"result":` + tt.want + `}`
		if r.StatusCode != 200 || string(raw) != want || !r.Close {
			t.Fatalf("%s: %d %s", tt.method, r.StatusCode, raw)
		}
		if r.Header.Get("Date") != "" || r.Header.Get("Set-Cookie") != "" {
			t.Fatal("extra headers")
		}
	}
	if b.calls.Load() != 4 {
		t.Fatal("call count")
	}
}

func TestInvalidHTTPAndJSONNeverCallsUpstream(t *testing.T) {
	b := &testBackend{}
	_, addr := startTest(t, b)
	valid := httpRequest(wire("status", `{}`))
	tests := []string{
		strings.Replace(valid, "POST / ", "GET / ", 1), strings.Replace(valid, "POST / ", "POST /? ", 1),
		strings.Replace(valid, "POST / ", "POST /websocket ", 1), strings.Replace(valid, "POST / ", "POST http://"+testHost+"/ ", 1),
		strings.Replace(valid, "POST / ", "POST /%2f ", 1), strings.Replace(valid, testHost, "localhost:80", 1),
		strings.Replace(valid, "Content-Type: application/json", "Content-Type: application/json; charset=utf-8", 1),
		strings.Replace(valid, "Content-Type: application/json", "Content-Type: application/json\r\nContent-Type: application/json", 1),
		strings.Replace(valid, "Content-Type: application/json\r\n", "", 1),
		httpRequest(wire("status", `{"a":1}`)), httpRequest(wire("abci_query", `{}`)), httpRequest("[" + wire("status", `{}`) + "]"),
		httpRequest(wire("status", `{}`) + wire("status", `{}`)),
	}
	for _, h := range []string{"Origin:", "Cookie:", "Authorization:", "Proxy-Authorization:", "Content-Encoding:", "Upgrade:", "Trailer: X-Foo", "Expect: test", "Connection: upgrade"} {
		tests = append(tests, strings.Replace(valid, "\r\nContent-Type:", "\r\n"+h+"\r\nContent-Type:", 1))
	}
	for i, raw := range tests {
		r, _ := send(t, addr, raw)
		if r.StatusCode == 200 {
			t.Fatalf("accepted case %d", i)
		}
	}
	if b.calls.Load() != 0 {
		t.Fatal("invalid request reached upstream")
	}
}

func TestBusyRejectDoesNotReadUnsentBody(t *testing.T) {
	entered := make(chan struct{}, 2)
	b := &testBackend{action: func(ctx context.Context, _ string, _ int64, _ []byte) (json.RawMessage, error) {
		entered <- struct{}{}
		<-ctx.Done()
		return nil, ctx.Err()
	}}
	s, addr := startTest(t, b)
	for i := 0; i < 2; i++ {
		c := dial(t, addr)
		io.WriteString(c, httpRequest(wire("status", `{}`)))
		select {
		case <-entered:
		case <-time.After(time.Second):
			t.Fatal("not entered")
		}
	}
	for _, headers := range []string{"Content-Length: 100", "Transfer-Encoding: chunked"} {
		start := time.Now()
		r, raw := send(t, addr, fmt.Sprintf("POST / HTTP/1.1\r\nHost: %s\r\nContent-Type: application/json\r\n%s\r\n\r\n", testHost, headers))
		if r.StatusCode != 503 || !r.Close || !bytes.Contains(raw, []byte(`"busy"`)) || time.Since(start) > time.Second {
			t.Fatal("busy body drain", r.StatusCode, string(raw))
		}
	}
	if b.calls.Load() != 2 {
		t.Fatal("busy called backend")
	}
	s.Stop()
	if err := s.Wait(); err != nil {
		t.Fatal(err)
	}
}

func TestReadingBodyCountsAsActiveAndEarlyErrorsDoNotDrain(t *testing.T) {
	b := &testBackend{}
	s, addr := startTest(t, b)
	for i := 0; i < 2; i++ {
		c := dial(t, addr)
		io.WriteString(c, fmt.Sprintf("POST / HTTP/1.1\r\nHost: %s\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n", testHost))
	}
	eventually(t, func() bool { s.mu.Lock(); defer s.mu.Unlock(); return s.active == 2 })
	r, _ := send(t, addr, httpRequest(wire("status", `{}`)))
	if r.StatusCode != 503 {
		t.Fatal("reads bypass admission")
	}
	if b.calls.Load() != 0 {
		t.Fatal("incomplete request upstream")
	}
	s.Stop()
	s.Wait()
	b2 := &testBackend{}
	_, addr2 := startTest(t, b2)
	for _, headers := range []string{"Content-Length: 65537", "Content-Length: 20\r\nOrigin:"} {
		r, _ := send(t, addr2, fmt.Sprintf("POST / HTTP/1.1\r\nHost: %s\r\nContent-Type: application/json\r\n%s\r\n\r\n", testHost, headers))
		if r.StatusCode == 200 {
			t.Fatal("early error accepted")
		}
	}
}

func TestChunkedSizeAndUndeclaredTrailer(t *testing.T) {
	b := &testBackend{}
	_, addr := startTest(t, b)
	for _, tt := range []struct {
		body, trailer string
		good          bool
	}{
		{wire("status", `{}`), "", true},
		{strings.Repeat(" ", MaxRequestBytes+1), "", false},
		{wire("status", `{}`), "Authorization: unwanted\r\n", false},
	} {
		raw := fmt.Sprintf("POST / HTTP/1.1\r\nHost: %s\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n%x\r\n%s\r\n0\r\n%s\r\n", testHost, len(tt.body), tt.body, tt.trailer)
		r, _ := send(t, addr, raw)
		if (r.StatusCode == 200) != tt.good {
			t.Fatal("chunk/trailer policy", r.StatusCode)
		}
	}
	if b.calls.Load() != 1 {
		t.Fatal("invalid chunk/trailer upstream")
	}
}

func TestUpstreamErrorAndResponseOverflowAreSanitized(t *testing.T) {
	for _, tt := range []struct {
		result json.RawMessage
		err    error
	}{
		{nil, errors.New("secret-upstream-message")}, {nil, nil}, {json.RawMessage(`{"x":"` + strings.Repeat("x", MaxResponseBytes-8) + `"}`), nil},
	} {
		b := &testBackend{action: func(context.Context, string, int64, []byte) (json.RawMessage, error) { return tt.result, tt.err }}
		_, addr := startTest(t, b)
		r, raw := send(t, addr, httpRequest(wire("block", `{"height":"1"}`)))
		if r.StatusCode != 502 || bytes.Contains(raw, []byte(`"result"`)) || bytes.Contains(raw, []byte("secret")) {
			t.Fatal("bad error", r.StatusCode, string(raw))
		}
		if b.calls.Load() != 1 {
			t.Fatal("retried error")
		}
	}
}

func TestSingleRequestCancelDoesNotStopServiceAndRootWaits(t *testing.T) {
	entered := make(chan struct{}, 2)
	exited := make(chan struct{}, 2)
	b := &testBackend{action: func(ctx context.Context, m string, _ int64, _ []byte) (json.RawMessage, error) {
		if m == "status" {
			return nil, nil
		}
		entered <- struct{}{}
		<-ctx.Done()
		exited <- struct{}{}
		return nil, ctx.Err()
	}}
	s, addr := startTest(t, b)
	c := dial(t, addr)
	io.WriteString(c, httpRequest(wire("block", `{"height":"1"}`)))
	<-entered
	c.Close()
	select {
	case <-exited:
	case <-time.After(time.Second):
		t.Fatal("request did not cancel upstream")
	}
	r, _ := send(t, addr, httpRequest(wire("status", `{}`)))
	if r.StatusCode != 200 {
		t.Fatal("single cancel stopped root")
	}
	c2 := dial(t, addr)
	io.WriteString(c2, httpRequest(wire("commit", `{"height":"1"}`)))
	<-entered
	slow := dial(t, addr)
	io.WriteString(slow, "POST / HTTP/1.1\r\n")
	s.Stop()
	if err := s.Wait(); err != nil {
		t.Fatal(err)
	}
	select {
	case <-exited:
	default:
		t.Fatal("root returned before upstream exit")
	}
	for _, conn := range []net.Conn{c2, slow} {
		conn.SetReadDeadline(time.Now().Add(time.Second))
		_, err := io.Copy(io.Discard, conn)
		if e, ok := err.(net.Error); ok && e.Timeout() {
			t.Fatal("socket retained")
		}
	}
	s.listener.mu.Lock()
	count := len(s.listener.conns)
	s.listener.mu.Unlock()
	if count != 0 {
		t.Fatal("tracked sockets retained")
	}
}

func TestSocketLimitIncludesSlowHeaders(t *testing.T) {
	s, addr := startTest(t, &testBackend{})
	for i := 0; i < maxConnections; i++ {
		c := dial(t, addr)
		io.WriteString(c, "POST / HTTP/1.1\r\n")
		expected := i + 1
		eventually(t, func() bool {
			s.listener.mu.Lock()
			defer s.listener.mu.Unlock()
			return len(s.listener.conns) == expected
		})
	}
	extra := dial(t, addr)
	extra.SetReadDeadline(time.Now().Add(time.Second))
	var one [1]byte
	if _, err := extra.Read(one[:]); err == nil {
		t.Fatal("excess open")
	} else if e, ok := err.(net.Error); ok && e.Timeout() {
		t.Fatal("excess queued")
	}
}

func TestConfigurationAndStoppedAdmission(t *testing.T) {
	for _, a := range []string{"127.0.0.1:0", "127.0.0.1:80", "127.0.0.1:08080", "localhost:8080", "0.0.0.0:8080", "[::1]:8080", "127.0.0.1:65536", "127.0.0.1:8080/"} {
		if ValidateListen(a) == nil {
			t.Fatal("address accepted", a)
		}
	}
	for _, a := range []string{"127.0.0.1:1024", "127.0.0.1:65535"} {
		if ValidateListen(a) != nil {
			t.Fatal("address rejected", a)
		}
	}
	c := Config{Listen: freeAddress(t), Host: testHost, MaxHeight: 10}
	if _, err := Start(nil, c, &testBackend{}); err == nil {
		t.Fatal("nil context")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := Start(ctx, c, &testBackend{}); err == nil {
		t.Fatal("canceled start")
	}
	if _, err := Start(context.Background(), c, nil); err == nil {
		t.Fatal("nil backend")
	}
	for _, h := range []string{"localhost:80", testHost + "/", strings.ToUpper(testHost), strings.Replace(testHost, ":80", ":0", 1)} {
		bad := c
		bad.Host = h
		if _, err := Start(context.Background(), bad, &testBackend{}); err == nil {
			t.Fatal("bad host")
		}
	}
	// Repeated racing requests and root cancellation exercise admission/Wait.
	for i := 0; i < 5; i++ {
		s, addr := startTest(t, &testBackend{})
		var wg sync.WaitGroup
		for j := 0; j < 8; j++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				c, err := net.DialTimeout("tcp4", addr, time.Second)
				if err == nil {
					defer c.Close()
					c.SetDeadline(time.Now().Add(time.Second))
					io.WriteString(c, httpRequest(wire("status", `{}`)))
					io.Copy(io.Discard, c)
				}
			}()
		}
		s.Stop()
		s.Wait()
		wg.Wait()
	}
}
