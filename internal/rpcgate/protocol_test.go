package rpcgate

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

func wire(method, params string) string {
	return `{"jsonrpc":"2.0","id":0,"method":"` + method + `","params":` + params + `}`
}

func TestStrictRequestMatrix(t *testing.T) {
	valid := []string{
		wire("status", `{}`), wire("block", `{"height":"1"}`), wire("commit", `{"height":"100"}`), wire("broadcast_tx_sync", `{"tx":"AA=="}`),
		strings.Replace(wire("status", `{}`), `"id":0`, `"id":9007199254740991`, 1),
	}
	for _, raw := range valid {
		if _, err := decode([]byte(raw), 100); err != nil {
			t.Fatalf("valid rejected: %s", raw)
		}
	}
	invalid := []string{
		"", `null`, `[]`, `[` + wire("status", `{}`) + `]`,
		wire("status", `{}`) + " null", wire("status", `{"extra":1}`), wire("status", `null`), wire("status", `[]`),
		wire("abci_query", `{}`), wire("net_info", `{}`), wire("genesis", `{}`), wire("dump_consensus_state", `{}`), wire("subscribe", `{}`),
		`{"jsonrpc":"2.0","method":"status","params":{}}`,
		strings.Replace(wire("status", `{}`), `"id":0`, `"id":0,"id":1`, 1),
		strings.Replace(wire("status", `{}`), `"id":0`, `"id":0,"\u0069d":1`, 1),
		strings.Replace(wire("status", `{}`), `"id":0`, `"ID":0`, 1),
		strings.Replace(wire("status", `{}`), `"id":0`, `"id":0,"x":{}`, 1),
		strings.Replace(wire("status", `{}`), `"2.0"`, `"1.0"`, 1),
		wire("block", `{"height":"1","height":"2"}`), wire("commit", `{"height":"1","\u0068eight":"2"}`),
		wire("block", `{"height":"1","extra":1}`), wire("block", `{}`),
		wire("broadcast_tx_sync", `{"tx":"AA==","tx":"AA=="}`), wire("broadcast_tx_sync", `{"tx":"AA==","height":"1"}`),
	}
	for _, id := range []string{`null`, `true`, `"0"`, `-1`, `-0`, `0.0`, `1e0`, `01`, `9007199254740992`, `18446744073709551616`} {
		invalid = append(invalid, strings.Replace(wire("status", `{}`), `"id":0`, `"id":`+id, 1))
	}
	for _, h := range []string{`0`, `00`, `01`, `-1`, `+1`, `1.0`, `1e0`, ` 1`, `101`, `18446744073709551616`} {
		invalid = append(invalid, wire("block", `{"height":"`+h+`"}`))
	}
	for _, h := range []string{`null`, `true`, `1`, `[]`, `{}`} {
		invalid = append(invalid, wire("block", `{"height":`+h+`}`))
	}
	for _, b := range []string{``, `AA`, `AB==`, `AA==\n`, `AA==\r`, `AA== `, `_A==`} {
		invalid = append(invalid, wire("broadcast_tx_sync", `{"tx":"`+b+`"}`))
	}
	invalid = append(invalid, wire("broadcast_tx_sync", `{"tx":null}`), wire("broadcast_tx_sync", `{"tx":1}`))
	for _, raw := range invalid {
		if _, err := decode([]byte(raw), 100); err == nil {
			t.Fatalf("invalid accepted: %s", raw)
		}
	}
	if _, err := decode(append([]byte(wire("status", `{}`)), 0xff), 100); err == nil {
		t.Fatal("invalid UTF8")
	}
	if _, err := decode([]byte(valid[0]), 0); err == nil {
		t.Fatal("no profile")
	}
}

func TestRequestAndResponseExactBounds(t *testing.T) {
	for _, n := range []int{1, MaxTransactionBytes, MaxTransactionBytes + 1} {
		raw := wire("broadcast_tx_sync", `{"tx":"`+base64.StdEncoding.EncodeToString(make([]byte, n))+`"}`)
		q, err := decode([]byte(raw), 100)
		if (err == nil) != (n <= MaxTransactionBytes) {
			t.Fatalf("tx bound %d: %v", n, err)
		}
		if err == nil && len(q.tx) != n {
			t.Fatal("tx changed")
		}
	}
	raw := []byte(wire("status", `{}`))
	padded := append(bytes.Repeat([]byte(" "), MaxRequestBytes-len(raw)), raw...)
	if _, err := decode(padded, 100); err != nil {
		t.Fatal("exact request size")
	}
	if _, err := decode(append(padded, ' '), 100); err == nil {
		t.Fatal("oversized request")
	}
	small, err := envelope(0, json.RawMessage(`""`))
	if err != nil || !bytes.Contains(small, []byte(`"id":0`)) {
		t.Fatal("id zero lost")
	}
	result := append([]byte{'"'}, bytes.Repeat([]byte("x"), MaxResponseBytes-len(small))...)
	result = append(result, '"')
	if b, err := envelope(0, result); err != nil || len(b) != MaxResponseBytes {
		t.Fatal("exact envelope size", err)
	}
	result = append([]byte{'"'}, result...)
	if _, err := envelope(0, result); err == nil {
		t.Fatal("invalid response")
	}
	if _, err := envelope(0, bytes.Repeat([]byte(" "), MaxResponseBytes+1)); err == nil {
		t.Fatal("oversized response")
	}
}

func FuzzGatewayRequest(f *testing.F) {
	for _, v := range []string{wire("status", `{}`), wire("block", `{"height":"1"}`), wire("commit", `{"height":"99"}`), wire("broadcast_tx_sync", `{"tx":"AA=="}`), `null`, `[]`} {
		f.Add([]byte(v))
	}
	f.Fuzz(func(t *testing.T, raw []byte) {
		q, err := decode(raw, 1000000)
		if err != nil {
			return
		}
		if len(raw) > MaxRequestBytes || q.id > maxID {
			t.Fatal("bounds")
		}
		switch q.method {
		case "status":
			if q.height != 0 || len(q.tx) != 0 {
				t.Fatal("state")
			}
		case "block", "commit":
			if q.height < 1 || q.height > 1000000 {
				t.Fatal("height")
			}
		case "broadcast_tx_sync":
			if len(q.tx) < 1 || len(q.tx) > MaxTransactionBytes {
				t.Fatal("tx")
			}
		default:
			t.Fatal("method")
		}
		b, err := envelope(q.id, json.RawMessage(`{}`))
		if err != nil || !json.Valid(b) {
			t.Fatal(fmt.Sprint(err))
		}
	})
}
