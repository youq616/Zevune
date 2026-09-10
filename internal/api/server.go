// Package api exposes a loopback-only diagnostic API, not a payment network.
package api

import (
	"encoding/json"
	"errors"
	"github.com/youq616/Zevune/internal/ledger"
	"github.com/youq616/Zevune/internal/protocol"
	"io"
	"net/http"
)

func reply(w http.ResponseWriter, code int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(value)
}

// New always installs the rejecting backend. There is no flag to bypass it.
func New(chain string) (http.Handler, error) {
	engine, err := ledger.New(chain, nil, ledger.UnavailableVerifier{})
	if err != nil {
		return nil, err
	}
	return newHandler(engine), nil
}

// NewPersistent uses the same rejecting verifier as New. Only local state storage
// changes; no payment or block-submission endpoint is enabled.
func NewPersistent(chain, dir string) (http.Handler, func() error, error) {
	engine, err := ledger.OpenPersistent(chain, dir, nil, ledger.UnavailableVerifier{})
	if err != nil {
		return nil, nil, err
	}
	return newHandler(engine), engine.Close, nil
}

func newHandler(engine *ledger.Engine) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		reply(w, 200, map[string]any{"process_running": true, "payments_enabled": false})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		reply(w, 503, map[string]any{"ready": false, "zk_backend": "not_implemented", "consensus": "not_implemented"})
	})
	mux.HandleFunc("GET /v1/status", func(w http.ResponseWriter, r *http.Request) {
		reply(w, 200, map[string]any{"stage": "state_machine_scaffold", "network": "local_only", "payments_enabled": false, "finality_available": false, "ledger": engine.Summary(), "storage": engine.StorageStatus()})
	})
	mux.HandleFunc("POST /v1/transactions", func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Content-Type") != "application/octet-stream" {
			reply(w, 415, map[string]string{"error": "binary prototype envelopes only; no cleartext payment endpoint"})
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, protocol.MaxTxBytes)
		body, err := io.ReadAll(r.Body)
		if err != nil {
			var tooBig *http.MaxBytesError
			if errors.As(err, &tooBig) {
				reply(w, 413, map[string]string{"error": "envelope too large"})
			} else {
				reply(w, 400, map[string]string{"error": "invalid request body"})
			}
			return
		}
		tx, err := protocol.DecodeBinary(body)
		if err != nil {
			reply(w, 400, map[string]string{"error": "invalid prototype envelope"})
			return
		}
		err = engine.CheckTx(tx)
		if errors.Is(err, ledger.ErrProofBackendUnavailable) {
			reply(w, 503, map[string]string{"error": ledger.ErrProofBackendUnavailable.Error()})
			return
		}
		if err != nil {
			reply(w, 400, map[string]string{"error": "transaction preflight rejected"})
			return
		}
		// Defensive gate: even a future verifier implementation must not turn this
		// diagnostic endpoint into an unaudited payment/mempool service by accident.
		reply(w, 503, map[string]string{"error": "payment admission is intentionally disabled in this scaffold"})
	})
	return mux
}
