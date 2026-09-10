package api

import (
	"encoding/json"
	"net/http"
	"testing"
)

func TestStatusReportsSoftwareVersionWithoutEnablingPayments(t *testing.T) {
	w := request(t, "GET", "/v1/status", "", nil)
	var s struct {
		Version  string `json:"software_version"`
		Payments bool   `json:"payments_enabled"`
		Finality bool   `json:"finality_available"`
		Stage    string `json:"stage"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &s); err != nil {
		t.Fatal(err)
	}
	if w.Code != http.StatusOK || s.Version != SoftwareVersion || s.Payments || s.Finality || s.Stage != "state_machine_scaffold" {
		t.Fatal(w.Body.String())
	}
}

func TestNoHTTPBlockOrPreviewCommitEndpoint(t *testing.T) {
	for _, path := range []string{"/v1/blocks", "/v1/preview", "/v1/commit"} {
		if w := request(t, "POST", path, "application/json", []byte(`{}`)); w.Code != http.StatusNotFound {
			t.Fatal("unexpected state-changing endpoint", path, w.Code)
		}
	}
}
