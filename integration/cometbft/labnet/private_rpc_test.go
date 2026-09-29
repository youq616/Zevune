package labnet

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base32"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/cometbft/cometbft/types"
)

const privateTestEndpoint = "http://" + socksTestHost + ":8080"

func TestPrivateRPCCanonicalOnionAndProxy(t *testing.T) {
	for _, host := range []string{socksTestHost,
		"sp3k262uwy4r2k3ycr5awluarykdpag6a7y33jxop4cs2lu5uz5sseqd.onion",
		"xa4r2iadxm55fbnqgwwi5mymqdcofiu3w6rpbtqn7b2dyn7mgwj64jyd.onion"} {
		for _, port := range []string{"1", "80", "8080", "65535"} {
			endpoint := "http://" + host + ":" + port
			if err := ValidatePrivateRPC(endpoint, "127.0.0.1:9050"); err != nil {
				t.Fatal("official canonical onion vector rejected", err)
			}
			if err := ValidateEndpoint(endpoint); err == nil {
				t.Fatal("legacy endpoint validator accepts onion")
			}
		}
	}
	for _, proxy := range []string{"", "localhost:9050", "127.0.0.2:9050", "[::1]:9050", "127.0.0.1:09050", "127.0.0.1:80", "127.0.0.1:65536", "127.0.0.1:9050/", "http://127.0.0.1:9050", "127.0.0.1:9050?", "127.0.0.1:9050#", "127.0.0.1:9050\x00", "192.0.2.1:9050"} {
		if ValidatePrivateRPC(privateTestEndpoint, proxy) != ErrEndpoint {
			t.Fatal("noncanonical proxy accepted")
		}
	}
	bad := []string{"", "http://127.0.0.1:8080", "http://example.org:8080", "https://" + socksTestHost + ":8080",
		"http://" + socksTestHost, "http://" + socksTestHost + ":0", "http://" + socksTestHost + ":08080", "http://" + socksTestHost + ":65536",
		"http://" + strings.ToUpper(socksTestHost) + ":8080", "HTTP://" + socksTestHost + ":8080", "http://x." + socksTestHost + ":8080",
		"http://" + socksTestHost + ".:8080", "http://user@" + socksTestHost + ":8080", "http://" + strings.Repeat("a", 16) + ".onion:8080",
		"http://%70" + socksTestHost[1:] + ":8080", strings.Repeat("x", 4096)}
	for _, suffix := range []string{"/", "/x", "?", "?q=x", "#", "#x", "/%2e", "\n", "\x00"} {
		bad = append(bad, privateTestEndpoint+suffix)
	}
	decoded, err := base32.StdEncoding.DecodeString(strings.ToUpper(socksTestHost[:56]))
	if err != nil {
		t.Fatal(err)
	}
	for _, index := range []int{0, 32, 33, 34} {
		changed := bytes.Clone(decoded)
		changed[index] ^= 1
		bad = append(bad, "http://"+strings.ToLower(base32.StdEncoding.EncodeToString(changed))+".onion:8080")
	}
	for _, endpoint := range bad {
		if ValidatePrivateRPC(endpoint, "127.0.0.1:9050") != ErrEndpoint {
			t.Fatal("invalid onion endpoint accepted")
		}
	}
}

// Parse the exact client auth and domain CONNECT on a real test socket. The
// returned parameter is test-observed random isolation, not a wallet secret.
func acceptPrivateSOCKS(conn net.Conn) (string, error) {
	if err := socksExpect(conn, []byte{5, 1, 2}); err != nil {
		return "", err
	}
	if err := writeSOCKS(conn, []byte{5, 2}); err != nil {
		return "", err
	}
	if err := socksExpect(conn, append([]byte{1, 9}, []byte("<torS0X>0")...)); err != nil {
		return "", err
	}
	if err := socksExpect(conn, []byte{64}); err != nil {
		return "", err
	}
	var isolation [64]byte
	if _, err := io.ReadFull(conn, isolation[:]); err != nil {
		return "", err
	}
	if _, err := hex.DecodeString(string(isolation[:])); err != nil || string(isolation[:]) != strings.ToLower(string(isolation[:])) {
		return "", errors.New("invalid isolation encoding")
	}
	if err := writeSOCKS(conn, []byte{1, 0}); err != nil {
		return "", err
	}
	if err := socksExpect(conn, socksConnectFrame(socksTestDialer(""))); err != nil {
		return "", err
	}
	if err := writeSOCKS(conn, []byte{5, 0, 0, 1, 0, 0, 0, 0, 0, 0}); err != nil {
		return "", err
	}
	return string(isolation[:]), nil
}

func privateRPCRequest(reader *bufio.Reader) (json.RawMessage, string, error) {
	r, err := http.ReadRequest(reader)
	if err != nil {
		return nil, "", err
	}
	defer r.Body.Close()
	if r.Method != http.MethodPost || r.Host != socksTestHost+":8080" || r.URL.RequestURI() != "/" || r.Header.Get("Accept-Encoding") != "" {
		return nil, "", errors.New("RPC escaped fixed uncompressed root POST")
	}
	var envelope struct {
		ID     json.RawMessage `json:"id"`
		Method string          `json:"method"`
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, maxResponseBytes+1))
	if err != nil || len(raw) > int(maxResponseBytes) {
		return nil, "", errors.New("RPC request bound")
	}
	if err := json.Unmarshal(raw, &envelope); err != nil || len(envelope.ID) == 0 {
		return nil, "", errors.New("invalid RPC request")
	}
	return envelope.ID, envelope.Method, nil
}

func privateRPCReply(conn net.Conn, id json.RawMessage, keep bool) error {
	body := append(append([]byte(`{"jsonrpc":"2.0","id":`), id...), []byte(`,"result":{}}`)...)
	connection := "close"
	if keep {
		connection = "keep-alive"
	}
	_, err := fmt.Fprintf(conn, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: %s\r\n\r\n%s", len(body), connection, body)
	return err
}

func TestPrivateRPCAllMethodsUseSOCKSAndIgnoreEnvironment(t *testing.T) {
	trap, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer trap.Close()
	for _, name := range []string{"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"} {
		t.Setenv(name, "http://"+trap.Addr().String())
	}
	t.Setenv("NO_PROXY", "")
	t.Setenv("no_proxy", "")
	proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
		if _, err := acceptPrivateSOCKS(conn); err != nil {
			return err
		}
		reader := bufio.NewReader(conn)
		for _, method := range []string{"status", "block", "commit", "broadcast_tx_sync"} {
			id, actual, err := privateRPCRequest(reader)
			if err != nil {
				return err
			}
			if actual != method {
				return errors.New("wrong RPC method")
			}
			if err := privateRPCReply(conn, id, true); err != nil {
				return err
			}
		}
		return socksExpectClosed(conn) // close() must close the idle connection.
	})
	p, err := newPeerForOptions(SyncOptions{Endpoint: privateTestEndpoint, SOCKSProxy: proxy})
	if err != nil {
		t.Fatal(err)
	}
	defer p.close()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	h := int64(1)
	if _, err := p.Status(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := p.Block(ctx, &h); err != nil {
		t.Fatal(err)
	}
	if _, err := p.Commit(ctx, &h); err != nil {
		t.Fatal(err)
	}
	if _, err := p.BroadcastTxSync(ctx, types.Tx{1, 2, 3}); err != nil {
		t.Fatal(err)
	}
	p.close()
	socksFixtureDone(t, done)
	_ = trap.(*net.TCPListener).SetDeadline(time.Now().Add(30 * time.Millisecond))
	if c, err := trap.Accept(); err == nil {
		c.Close()
		t.Fatal("environment proxy used")
	} else if ne, ok := err.(net.Error); !ok || !ne.Timeout() {
		t.Fatal(err)
	}
}

func TestPrivateRPCPerPeerIsolationAndReconnection(t *testing.T) {
	seen := make(chan string, 3)
	proxy, done := socksFixture(t, 3, func(conn net.Conn) error {
		isolation, err := acceptPrivateSOCKS(conn)
		if err != nil {
			return err
		}
		seen <- isolation
		id, _, err := privateRPCRequest(bufio.NewReader(conn))
		if err != nil {
			return err
		}
		return privateRPCReply(conn, id, false)
	})
	p, err := newPrivatePeer(privateTestEndpoint, proxy)
	if err != nil {
		t.Fatal(err)
	}
	defer p.close()
	q, err := newPrivatePeer(privateTestEndpoint, proxy)
	if err != nil {
		t.Fatal(err)
	}
	defer q.close()
	for _, p := range []*peer{p, p, q} {
		if _, err := p.Status(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	socksFixtureDone(t, done)
	a, b, c := <-seen, <-seen, <-seen
	if a != b || a == c || p.transport == q.transport {
		t.Fatal("isolation boundary violated (values suppressed)")
	}
}

func TestPrivateRPCHTTPRejectionAndNoRedirectFallback(t *testing.T) {
	for _, response := range []string{
		"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1/\r\nContent-Length: 0\r\n\r\n",
		"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 0\r\n\r\n",
		"HTTP/1.1 200 OK\r\nContent-Length: 2097153\r\n\r\n",
	} {
		proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
			if _, err := acceptPrivateSOCKS(conn); err != nil {
				return err
			}
			if _, _, err := privateRPCRequest(bufio.NewReader(conn)); err != nil {
				return err
			}
			return writeSOCKS(conn, []byte(response))
		})
		p, err := newPrivatePeer(privateTestEndpoint, proxy)
		if err != nil {
			t.Fatal(err)
		}
		_, err = p.Status(context.Background())
		p.close()
		if err == nil || !errors.Is(err, ErrResponse) {
			t.Fatalf("HTTP rejection did not preserve response error: %v", err)
		}
		socksFixtureDone(t, done)
	}
	// Streaming/chunked responses must keep the same 2 MiB reader boundary.
	proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
		if _, err := acceptPrivateSOCKS(conn); err != nil {
			return err
		}
		if _, _, err := privateRPCRequest(bufio.NewReader(conn)); err != nil {
			return err
		}
		_, err := fmt.Fprintf(conn, "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n%x\r\n%s\r\n0\r\n\r\n", maxResponseBytes+1, strings.Repeat(" ", int(maxResponseBytes)+1))
		// Closing on overflow can interrupt the fixture's final write.
		if err != nil && !errors.Is(err, net.ErrClosed) {
			return nil
		}
		return nil
	})
	p, err := newPrivatePeer(privateTestEndpoint, proxy)
	if err != nil {
		t.Fatal(err)
	}
	_, err = p.Status(context.Background())
	p.close()
	if !errors.Is(err, ErrResponse) {
		t.Fatalf("streaming body bound not enforced: %v", err)
	}
	socksFixtureDone(t, done)
}

type privateEntropyFailure struct{}

func (privateEntropyFailure) Read([]byte) (int, error) { return 0, io.ErrUnexpectedEOF }

func TestPrivateRPCRefusesMissingEntropyAndNeverDefaultsProxy(t *testing.T) {
	previous := rand.Reader
	rand.Reader = privateEntropyFailure{}
	defer func() { rand.Reader = previous }()
	if p, err := newPrivatePeer(privateTestEndpoint, "127.0.0.1:9050"); p != nil || err != errPrivateSOCKS {
		t.Fatal("missing entropy accepted")
	}
	for _, o := range []SyncOptions{
		{Endpoint: privateTestEndpoint},
		{Endpoint: "http://127.0.0.1:8080", SOCKSProxy: "127.0.0.1:9050"},
		{Endpoint: privateTestEndpoint, SOCKSProxy: "localhost:9050"},
	} {
		if p, err := newPeerForOptions(o); p != nil || err != ErrEndpoint {
			t.Fatal("invalid route fell back")
		}
	}
}

func FuzzPrivateRPCEndpoint(f *testing.F) {
	for _, endpoint := range []string{privateTestEndpoint, "http://127.0.0.1:8080", "", privateTestEndpoint + "/"} {
		f.Add(endpoint, "127.0.0.1:9050")
	}
	f.Fuzz(func(t *testing.T, endpoint, proxy string) {
		if ValidatePrivateRPC(endpoint, proxy) != nil {
			return
		}
		host, port, err := parseOnionEndpoint(endpoint)
		if err != nil || endpoint != "http://"+net.JoinHostPort(host, strconv.Itoa(int(port))) || ValidateEndpoint("http://"+proxy) != nil || ValidateEndpoint(endpoint) == nil {
			t.Fatal("accepted noncanonical private route")
		}
	})
}

func TestPrivateRPCRequestCancellationStopsPendingSOCKS(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	proxy, done := socksFixture(t, 1, func(conn net.Conn) error {
		if err := socksExpect(conn, []byte{5, 1, 2}); err != nil {
			return err
		}
		cancel()
		return socksExpectClosed(conn)
	})
	p, err := newPrivatePeer(privateTestEndpoint, proxy)
	if err != nil {
		t.Fatal(err)
	}
	defer p.close()
	if _, err := p.Status(ctx); err == nil {
		t.Fatal("cancelled request succeeded")
	}
	// Do not close the peer first: CloseIdleConnections could mask a detached
	// cancellation bug by eventually cleaning up the abandoned dial itself.
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("HTTP cancellation did not stop the pending SOCKS socket")
	}
}

func TestPrivateRPCUnavailableProxyFailsWithoutFallback(t *testing.T) {
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	proxy := listener.Addr().String()
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	p, err := newPeerForOptions(SyncOptions{Endpoint: privateTestEndpoint, SOCKSProxy: proxy})
	if err != nil {
		t.Fatal(err)
	}
	defer p.close()
	if _, err := p.Status(context.Background()); !errors.Is(err, errPrivateSOCKS) {
		t.Fatalf("unavailable explicit proxy did not fail closed: %v", err)
	}
}
