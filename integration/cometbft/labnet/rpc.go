package labnet

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"time"

	rpc "github.com/cometbft/cometbft/rpc/client/http"
	ctypes "github.com/cometbft/cometbft/rpc/core/types"
	"github.com/cometbft/cometbft/types"
)

const maxResponseBytes int64 = 2 * 1024 * 1024
const maxHeight int64 = 10000
const maxSyncBlocks uint64 = 128

// Endpoint validation intentionally disallows DNS, proxies, user-info, redirects,
// remote IPs and URL-supplied query/path fragments. This is a local test client,
// NOT an anonymous transport or an unrestricted RPC utility.
func ValidateEndpoint(endpoint string) error {
	u, err := url.Parse(endpoint)
	if err != nil || u.Scheme != "http" || u.User != nil || u.Hostname() != "127.0.0.1" || u.Path != "" || u.RawPath != "" || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" {
		return ErrEndpoint
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil || port < 1024 || port > 65535 || strconv.Itoa(port) != u.Port() || u.Host != "127.0.0.1:"+u.Port() || endpoint != "http://127.0.0.1:"+u.Port() {
		return ErrEndpoint
	}
	return nil
}

type boundedBody struct {
	io.ReadCloser
	remaining int64
}

func (b *boundedBody) Read(p []byte) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}
	if b.remaining == 0 {
		var extra [1]byte
		n, err := b.ReadCloser.Read(extra[:])
		if n != 0 {
			return 0, ErrResponse
		}
		return 0, err
	}
	if int64(len(p)) > b.remaining {
		p = p[:b.remaining]
	}
	n, err := b.ReadCloser.Read(p)
	b.remaining -= int64(n)
	return n, err
}

type boundedTransport struct {
	base *http.Transport
	host string
}

func (t *boundedTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	if r.URL.Scheme != "http" || r.URL.Host != t.host || r.URL.User != nil || (r.URL.Path != "" && r.URL.Path != "/") || r.Method != http.MethodPost || r.URL.RawQuery != "" || r.URL.ForceQuery || r.URL.Fragment != "" || r.URL.RawPath != "" || r.URL.Opaque != "" || (r.Host != "" && r.Host != t.host) {
		return nil, ErrEndpoint
	}
	response, err := t.base.RoundTrip(r)
	if err != nil {
		return nil, err
	}
	if response.StatusCode != http.StatusOK || response.ContentLength > maxResponseBytes || response.Header.Get("Content-Encoding") != "" {
		response.Body.Close()
		return nil, ErrResponse
	}
	response.Body = &boundedBody{ReadCloser: response.Body, remaining: maxResponseBytes}
	return response, nil
}

type rpcSource interface {
	Status(context.Context) (*ctypes.ResultStatus, error)
	Block(context.Context, *int64) (*ctypes.ResultBlock, error)
	Commit(context.Context, *int64) (*ctypes.ResultCommit, error)
	BroadcastTxSync(context.Context, types.Tx) (*ctypes.ResultBroadcastTx, error)
}
type peer struct {
	*rpc.HTTP
	transport *http.Transport
}

func newPeer(endpoint string) (*peer, error) {
	if err := ValidateEndpoint(endpoint); err != nil {
		return nil, err
	}
	u, _ := url.Parse(endpoint)
	transport := &http.Transport{
		Proxy:              nil,
		DialContext:        (&net.Dialer{Timeout: 2 * time.Second}).DialContext,
		DisableCompression: true, MaxConnsPerHost: 2, MaxIdleConnsPerHost: 2,
		MaxResponseHeaderBytes: 32 * 1024, ResponseHeaderTimeout: 5 * time.Second,
		IdleConnTimeout: 10 * time.Second,
	}
	client := &http.Client{
		Timeout:       10 * time.Second,
		Transport:     &boundedTransport{base: transport, host: u.Host},
		CheckRedirect: func(*http.Request, []*http.Request) error { return ErrEndpoint },
	}
	upstream, err := rpc.NewWithClient(endpoint, "/websocket", client)
	if err != nil {
		transport.CloseIdleConnections()
		return nil, ErrEndpoint
	}
	// WSEvents is never started: only explicitly bounded HTTP calls are used.
	return &peer{HTTP: upstream, transport: transport}, nil
}
func (p *peer) close() { p.transport.CloseIdleConnections() }
