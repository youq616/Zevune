package rpcgate

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"io"
	"log"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	maxConnections = 32
	maxActive      = 2
	// Complete buffering consumes the downstream client's 5s header budget.
	// This tighter 4s upstream budget leaves margin, not a promise of success.
	upstreamBudget = 4 * time.Second
	requestBudget  = 8 * time.Second
)

// Backend is implemented by the fixed, typed CometBFT adapter, never by an
// arbitrary request-selected URL. Block/Commit return upstream cmtjson bytes.
// Calls must honor ctx and must not start detached work or retry broadcasts.
// Accepting doubles belong only in *_test.go.
type Backend interface {
	Status(context.Context) (string, int64, error)
	Block(context.Context, int64) (json.RawMessage, error)
	Commit(context.Context, int64) (json.RawMessage, error)
	Broadcast(context.Context, []byte) (uint32, []byte, error)
}

type Config struct {
	Listen string
	// Host was checksum/version-validated by the labnet entry point. The core
	// additionally checks its canonical syntax; Host is routing, not Tor auth.
	Host      string
	MaxHeight int64
}

func ValidateListen(address string) error {
	if len(address) > len("127.0.0.1:65535") {
		return ErrConfiguration
	}
	host, port, err := net.SplitHostPort(address)
	if err != nil || host != "127.0.0.1" {
		return ErrConfiguration
	}
	n, err := decimal(port, 65535, false)
	if err != nil || n < 1024 || address != host+":"+strconv.FormatUint(n, 10) {
		return ErrConfiguration
	}
	return nil
}

func (c Config) validate() error {
	if ValidateListen(c.Listen) != nil || c.MaxHeight <= 0 {
		return ErrConfiguration
	}
	host, port, err := net.SplitHostPort(c.Host)
	if err != nil || len(host) != 62 || !strings.HasSuffix(host, ".onion") {
		return ErrConfiguration
	}
	for _, ch := range host[:56] {
		if !(ch >= 'a' && ch <= 'z' || ch >= '2' && ch <= '7') {
			return ErrConfiguration
		}
	}
	n, err := decimal(port, 65535, false)
	if err != nil || c.Host != host+":"+strconv.FormatUint(n, 10) {
		return ErrConfiguration
	}
	return nil
}

// Service owns all sockets and the root context. Wait includes admitted
// handlers, including their body close/response flush; it never closes Backend.
// The caller closes the shared peer's idle connections only AFTER Wait.
type Service struct {
	config   Config
	backend  Backend
	listener *limitedListener
	server   *http.Server
	cancel   context.CancelFunc
	done     chan struct{}
	mu       sync.Mutex
	stopping bool
	active   int
	handlers sync.WaitGroup
	err      error
}

func Start(parent context.Context, c Config, backend Backend) (*Service, error) {
	if parent == nil || parent.Err() != nil || backend == nil || c.validate() != nil {
		return nil, ErrConfiguration
	}
	l, err := net.Listen("tcp4", c.Listen)
	if err != nil {
		return nil, ErrService
	}
	ctx, cancel := context.WithCancel(parent)
	s := &Service{config: c, backend: backend, listener: &limitedListener{Listener: l, conns: make(map[*trackedConn]struct{})}, cancel: cancel, done: make(chan struct{})}
	s.server = &http.Server{
		Handler: s, BaseContext: func(net.Listener) context.Context { return ctx },
		ReadHeaderTimeout: 2 * time.Second, ReadTimeout: 5 * time.Second,
		WriteTimeout: 10 * time.Second, IdleTimeout: 10 * time.Second,
		MaxHeaderBytes: 32 * 1024, ErrorLog: log.New(io.Discard, "", 0),
	}
	go s.run(ctx)
	return s, nil
}

func (s *Service) run(ctx context.Context) {
	served := make(chan error, 1)
	go func() { served <- s.server.Serve(s.listener) }()
	var serveErr error
	var ended bool
	select {
	case <-ctx.Done():
	case serveErr = <-served:
		ended = true
	}
	// Add and stop share this lock: Wait can never race a new registered handler.
	s.mu.Lock()
	s.stopping = true
	s.mu.Unlock()
	s.cancel()
	_ = s.listener.Close()
	_ = s.server.Close()
	s.listener.closeConnections()
	if !ended {
		serveErr = <-served
	}
	s.handlers.Wait()
	// Serve should only stop because WE closed it. An unexpected exit is failure,
	// even if it happens to return http.ErrServerClosed.
	if ended {
		s.err = ErrService
	}
	_ = serveErr // no untrusted endpoint/error text reaches the caller
	close(s.done)
}

func (s *Service) Stop()       { s.cancel() }
func (s *Service) Wait() error { <-s.done; return s.err }

func (s *Service) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	if s.stopping {
		s.mu.Unlock()
		return
	}
	s.handlers.Add(1)
	admitted := s.active < maxActive
	if admitted {
		s.active++
	}
	s.mu.Unlock()
	defer s.handlers.Done()
	if admitted {
		defer func() { s.mu.Lock(); s.active--; s.mu.Unlock() }()
	}

	// Every response closes its connection, an explicit cost of this first
	// gateway. No keep-alive drain can sit outside the active-request budget.
	w.Header().Set("Connection", "close")
	w.Header()["Date"] = nil
	control := http.NewResponseController(w)
	if control.EnableFullDuplex() != nil {
		return
	} // actual HTTP/1 server supports it
	defer func() {
		// finishRequest may Close an unread body even with Connection: close.
		// Expire its socket read deadline before doing so, while still registered.
		_ = control.SetReadDeadline(time.Now())
		_ = r.Body.Close()
	}()
	if !admitted {
		reject(w, r, http.StatusServiceUnavailable, "busy", nil)
		return
	}
	if !s.validHTTP(r) {
		reject(w, r, http.StatusBadRequest, "request_rejected", nil)
		return
	}
	if r.ContentLength > MaxRequestBytes {
		reject(w, r, http.StatusRequestEntityTooLarge, "request_rejected", nil)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), requestBudget)
	defer cancel()
	raw, err := io.ReadAll(io.LimitReader(r.Body, MaxRequestBytes+1))
	if err != nil || len(raw) > MaxRequestBytes || len(r.Trailer) > 0 {
		reject(w, r, http.StatusBadRequest, "request_rejected", nil)
		return
	}
	q, err := decode(raw, s.config.MaxHeight)
	if err != nil {
		reject(w, r, http.StatusBadRequest, "request_rejected", nil)
		return
	}
	// Do not start an upstream call after cancellation or a failed body read.
	if ctx.Err() != nil {
		reject(w, r, http.StatusBadGateway, "upstream_unavailable", &q.id)
		return
	}
	callCtx, callCancel := context.WithTimeout(ctx, upstreamBudget)
	result, err := s.call(callCtx, q)
	callCancel()
	if err != nil || ctx.Err() != nil {
		reject(w, r, http.StatusBadGateway, "upstream_unavailable", &q.id)
		return
	}
	body, err := envelope(q.id, result)
	if err != nil {
		reject(w, r, http.StatusBadGateway, "upstream_unavailable", &q.id)
		return
	}
	writeResponse(w, http.StatusOK, body, deadline(ctx, time.Second))
}

func deadline(ctx context.Context, budget time.Duration) time.Time {
	end := time.Now().Add(budget)
	if d, ok := ctx.Deadline(); ok && d.Before(end) {
		return d
	}
	return end
}

func (s *Service) validHTTP(r *http.Request) bool {
	if r.ProtoMajor != 1 || (r.ProtoMinor != 0 && r.ProtoMinor != 1) || r.Method != "POST" || r.RequestURI != "/" || r.Host != s.config.Host || r.URL == nil {
		return false
	}
	u := r.URL
	if u.Scheme != "" || u.Host != "" || u.User != nil || u.Path != "/" || u.RawPath != "" || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || u.Opaque != "" {
		return false
	}
	content := r.Header.Values("Content-Type")
	if len(content) != 1 || content[0] != "application/json" || len(r.Trailer) != 0 {
		return false
	}
	for name, values := range r.Header {
		switch strings.ToLower(name) {
		case "content-encoding", "upgrade", "origin", "cookie", "authorization", "proxy-authorization", "trailer", "expect":
			return false // presence, not just a nonempty Get
		case "connection":
			if len(values) != 1 || !(strings.EqualFold(values[0], "close") || strings.EqualFold(values[0], "keep-alive")) {
				return false
			}
		}
	}
	if len(r.TransferEncoding) > 1 || len(r.TransferEncoding) == 1 && r.TransferEncoding[0] != "chunked" {
		return false
	}
	return true
}

func reject(w http.ResponseWriter, r *http.Request, status int, message string, id *uint64) {
	// R1: expire the read side BEFORE writing or Close, never drain an unsent
	// body. No user/upstream string is interpolated into these fixed errors.
	c := http.NewResponseController(w)
	_ = c.SetReadDeadline(time.Now())
	idText := "null"
	if id != nil {
		idText = strconv.FormatUint(*id, 10)
	}
	body := []byte(`{"jsonrpc":"2.0","id":` + idText + `,"error":{"code":-32000,"message":"` + message + `"}}`)
	writeResponse(w, status, body, time.Now().Add(time.Second))
}

func writeResponse(w http.ResponseWriter, status int, body []byte, until time.Time) {
	control := http.NewResponseController(w)
	if control.SetWriteDeadline(until) != nil {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	if _, err := w.Write(body); err == nil {
		_ = control.Flush()
	}
}

func (s *Service) call(ctx context.Context, q request) (json.RawMessage, error) {
	var result json.RawMessage
	var err error
	switch q.method {
	case "status":
		var network string
		var height int64
		network, height, err = s.backend.Status(ctx)
		if err == nil {
			if len(network) == 0 || len(network) > 128 || height < 0 || height > s.config.MaxHeight {
				return nil, ErrUpstream
			}
			// Explicit string height; no local node ID/listen address/moniker.
			result, err = json.Marshal(struct {
				Node struct {
					Network string `json:"network"`
				} `json:"node_info"`
				Sync struct {
					Height string `json:"latest_block_height"`
				} `json:"sync_info"`
			}{Node: struct {
				Network string `json:"network"`
			}{network}, Sync: struct {
				Height string `json:"latest_block_height"`
			}{strconv.FormatInt(height, 10)}})
		}
	case "block":
		result, err = s.backend.Block(ctx, q.height)
	case "commit":
		result, err = s.backend.Commit(ctx, q.height)
	case "broadcast_tx_sync":
		var code uint32
		var hash []byte
		code, hash, err = s.backend.Broadcast(ctx, q.tx)
		if err == nil {
			if len(hash) != 32 {
				return nil, ErrUpstream
			}
			result, err = json.Marshal(struct {
				Code uint32 `json:"code"`
				Hash string `json:"hash"`
			}{code, strings.ToUpper(hex.EncodeToString(hash))})
		}
	default:
		return nil, ErrRequest
	}
	if err != nil || ctx.Err() != nil {
		return nil, ErrUpstream
	}
	return result, nil
}
