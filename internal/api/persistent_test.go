package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestPersistentAPIReopensWithoutEnablingPayments(t *testing.T) {
	dir := t.TempDir()
	for _, recovered := range []bool{false, true} {
		h, closeFn, err := NewPersistent("veil-local-devnet-1", dir)
		if err != nil {
			t.Fatal(err)
		}
		func() {
			defer closeFn()
			w := httptest.NewRecorder()
			h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/status", nil))
			var got struct {
				Payments bool `json:"payments_enabled"`
				Finality bool `json:"finality_available"`
				Storage  struct {
					Mode      string `json:"mode"`
					Recovered bool   `json:"recovered"`
					Available bool   `json:"available"`
				} `json:"storage"`
			}
			if err = json.Unmarshal(w.Body.Bytes(), &got); err != nil {
				t.Fatal(err)
			}
			if w.Code != 200 || got.Payments || got.Finality || got.Storage.Mode != "journal" || got.Storage.Recovered != recovered || !got.Storage.Available {
				t.Fatal(w.Body.String())
			}
			ready := httptest.NewRecorder()
			h.ServeHTTP(ready, httptest.NewRequest("GET", "/readyz", nil))
			if ready.Code != http.StatusServiceUnavailable {
				t.Fatal("readiness must remain false")
			}
			health := httptest.NewRecorder()
			h.ServeHTTP(health, httptest.NewRequest("GET", "/healthz", nil))
			if health.Code != 200 {
				t.Fatal("process health failed")
			}
		}()
	}
}

func TestPersistentAPIWrongChainRejected(t *testing.T) {
	dir := t.TempDir()
	_, closeFn, err := NewPersistent("one", dir)
	if err != nil {
		t.Fatal(err)
	}
	_ = closeFn()
	if _, closeFn, err := NewPersistent("two", dir); err == nil {
		_ = closeFn()
		t.Fatal("wrong chain accepted")
	}
}
