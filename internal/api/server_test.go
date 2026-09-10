package api

import (
	"bytes"
	"github.com/youq616/Zevune/internal/merkle"
	"github.com/youq616/Zevune/internal/protocol"
	"net/http"
	"net/http/httptest"
	"testing"
)

func request(t *testing.T, method, path, content string, body []byte) *httptest.ResponseRecorder {
	t.Helper()
	h, e := New("veil-local-devnet-1")
	if e != nil {
		t.Fatal(e)
	}
	r := httptest.NewRequest(method, path, bytes.NewReader(body))
	r.Header.Set("Content-Type", content)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}
func TestHealthAndReadinessAreDifferent(t *testing.T) {
	if w := request(t, "GET", "/healthz", "", nil); w.Code != 200 || !bytes.Contains(w.Body.Bytes(), []byte(`"payments_enabled":false`)) {
		t.Fatal(w.Body.String())
	}
	if w := request(t, "GET", "/readyz", "", nil); w.Code != 503 {
		t.Fatal(w.Code)
	}
}
func TestStatusDoesNotClaimFinality(t *testing.T) {
	w := request(t, "GET", "/v1/status", "", nil)
	if w.Code != 200 || !bytes.Contains(w.Body.Bytes(), []byte(`"finality_available":false`)) {
		t.Fatal(w.Body.String())
	}
}
func TestNoCleartextPaymentEndpoint(t *testing.T) {
	w := request(t, "POST", "/v1/transactions", "application/json", []byte(`{"sender":"a","recipient":"b","amount":1}`))
	if w.Code != http.StatusUnsupportedMediaType {
		t.Fatal(w.Code)
	}
}
func TestMalformedBinaryRejected(t *testing.T) {
	if w := request(t, "POST", "/v1/transactions", "application/octet-stream", []byte("bad")); w.Code != 400 {
		t.Fatal(w.Code)
	}
}
func TestOversizeBinaryRejected(t *testing.T) {
	if w := request(t, "POST", "/v1/transactions", "application/octet-stream", make([]byte, protocol.MaxTxBytes+1)); w.Code != 413 {
		t.Fatal(w.Code)
	}
}
func TestStructurallyValidPaymentStillDisabled(t *testing.T) {
	x := protocol.Envelope{Version: protocol.Version, ChainID: "veil-local-devnet-1", CircuitID: protocol.CircuitID, Anchor: merkle.Root(nil), ExpiryHeight: 100, Nullifiers: []protocol.Hash{{1}}, Outputs: []protocol.Output{{Commitment: protocol.Hash{2}, EphemeralKey: protocol.Hash{3}, Ciphertext: make([]byte, protocol.CiphertextBytes)}}, Proof: []byte("fake")}
	b, _ := x.MarshalBinary()
	w := request(t, "POST", "/v1/transactions", "application/octet-stream", b)
	if w.Code != 503 || !bytes.Contains(w.Body.Bytes(), []byte("payments are disabled")) {
		t.Fatal(w.Code, w.Body.String())
	}
}
func TestInvalidChainRejected(t *testing.T) {
	if _, err := New("BAD"); err == nil {
		t.Fatal("invalid config")
	}
}
