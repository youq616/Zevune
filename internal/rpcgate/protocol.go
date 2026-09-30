// Package rpcgate implements the restricted, loopback-only RPC service boundary.
// It is not a verifier, an anonymous transport, or a general reverse proxy.
package rpcgate

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"strconv"
	"unicode/utf8"
)

const (
	MaxRequestBytes     = 65536
	MaxResponseBytes    = 2 * 1024 * 1024
	MaxTransactionBytes = 28134
	maxID               = 9007199254740991
)

var (
	ErrConfiguration = errors.New("gateway configuration rejected")
	ErrRequest       = errors.New("gateway request rejected")
	ErrUpstream      = errors.New("gateway upstream unavailable")
	ErrService       = errors.New("gateway service failed")
	ErrReady         = errors.New("gateway readiness failed")
)

type request struct {
	id     uint64
	method string
	height int64
	tx     []byte
}

// Objects are parsed before binding to structs: encoding/json alone accepts
// duplicate names (including escaped aliases), unknown fields and null values.
func object(raw []byte, names ...string) (map[string]json.RawMessage, error) {
	d := json.NewDecoder(bytes.NewReader(raw))
	first, err := d.Token()
	if err != nil || first != json.Delim('{') {
		return nil, ErrRequest
	}
	out := make(map[string]json.RawMessage, len(names))
	for d.More() {
		k, err := d.Token()
		name, ok := k.(string)
		if err != nil || !ok {
			return nil, ErrRequest
		}
		allowed := false
		for _, n := range names {
			if n == name {
				allowed = true
				break
			}
		}
		if !allowed {
			return nil, ErrRequest
		}
		if _, exists := out[name]; exists {
			return nil, ErrRequest
		}
		var v json.RawMessage
		if d.Decode(&v) != nil {
			return nil, ErrRequest
		}
		out[name] = v
	}
	last, err := d.Token()
	if err != nil || last != json.Delim('}') || len(out) != len(names) {
		return nil, ErrRequest
	}
	if _, err = d.Token(); err != io.EOF {
		return nil, ErrRequest
	}
	return out, nil
}

func decimal(s string, maximum uint64, allowZero bool) (uint64, error) {
	if len(s) == 0 || len(s) > 20 || len(s) > 1 && s[0] == '0' {
		return 0, ErrRequest
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, ErrRequest
		}
	}
	n, err := strconv.ParseUint(s, 10, 64)
	if err != nil || n > maximum || !allowZero && n == 0 {
		return 0, ErrRequest
	}
	return n, nil
}

func text(raw json.RawMessage) (string, error) {
	if len(raw) < 2 || raw[0] != '"' {
		return "", ErrRequest
	}
	var s string
	if json.Unmarshal(raw, &s) != nil {
		return "", ErrRequest
	}
	return s, nil
}

func decode(raw []byte, maxHeight int64) (request, error) {
	var q request
	if maxHeight <= 0 || len(raw) == 0 || len(raw) > MaxRequestBytes || !utf8.Valid(raw) {
		return q, ErrRequest
	}
	o, err := object(raw, "jsonrpc", "id", "method", "params")
	if err != nil {
		return q, err
	}
	version, err := text(o["jsonrpc"])
	if err != nil || version != "2.0" {
		return q, ErrRequest
	}
	if q.id, err = decimal(string(o["id"]), maxID, true); err != nil {
		return request{}, err
	}
	if q.method, err = text(o["method"]); err != nil {
		return request{}, err
	}
	switch q.method {
	case "status":
		_, err = object(o["params"])
	case "block", "commit":
		var p map[string]json.RawMessage
		p, err = object(o["params"], "height")
		if err == nil {
			var value string
			value, err = text(p["height"])
			if err == nil {
				var height uint64
				height, err = decimal(value, uint64(maxHeight), false)
				q.height = int64(height)
			}
		}
	case "broadcast_tx_sync":
		var p map[string]json.RawMessage
		p, err = object(o["params"], "tx")
		if err == nil {
			var value string
			value, err = text(p["tx"])
			if err == nil {
				if len(value) == 0 || len(value) > base64.StdEncoding.EncodedLen(MaxTransactionBytes) {
					return request{}, ErrRequest
				}
				q.tx, err = base64.StdEncoding.Strict().DecodeString(value)
				if err == nil && (len(q.tx) == 0 || len(q.tx) > MaxTransactionBytes || base64.StdEncoding.EncodeToString(q.tx) != value) {
					err = ErrRequest
				}
			}
		}
	default:
		err = ErrRequest
	}
	if err != nil {
		return request{}, ErrRequest
	}
	return q, nil
}

func envelope(id uint64, result json.RawMessage) ([]byte, error) {
	if len(result) == 0 || len(result) > MaxResponseBytes || !json.Valid(result) {
		return nil, ErrUpstream
	}
	// Do not re-encode the inner CometBFT result using standard struct semantics.
	prefix := []byte(`{"jsonrpc":"2.0","id":` + strconv.FormatUint(id, 10) + `,"result":`)
	if len(prefix)+len(result)+1 > MaxResponseBytes {
		return nil, ErrUpstream
	}
	out := append(prefix, result...)
	return append(out, '}'), nil
}
