//go:build operator_e2e && wallet_network_e2e

package labnet

import (
	"encoding/json"
	"strings"
	"testing"
)

// Fixed public fixture diagnostics only; never stringify arbitrary frame fields,
// exceptions, stderr, paths, receipts, transaction bodies or password material.
func walletNetworkFailureReport(value map[string]any) string {
	report := struct {
		Step               string `json:"step"`
		Code               string `json:"code"`
		ConfigWasCanonical *bool  `json:"config_was_canonical"`
		ConfigCanonical    *bool  `json:"config_canonical"`
		ReferenceExists    *bool  `json:"reference_exists"`
		VerifiedPartial    *bool  `json:"verified_partial"`
		VerifierCalls      *int   `json:"verifier_calls"`
		NetworkCalls       *int   `json:"network_calls"`
	}{Step: "unknown", Code: "unknown"}
	step, _ := value["step"].(string)
	switch step {
	case "setup", "network-start", "initial-catchup", "real-payment-and-pending", "explicit-fixture-broadcast", "payment-rescan", "restart-rescan", "false-peer-refusal", "stale-handoff-refusal", "final-rescan", "initial-config", "initial-partial-command", "initial-partial-check", "initial-reference-copy", "readonly-pending-recovery", "submission-config", "partial-submission-refusal", "prepare-0", "prepare-1", "submit-0", "submit-1", "reconcile-0", "reconcile-1":
		report.Step = step
	}
	code, _ := value["code"].(string)
	switch code {
	case "config_canonicalization_failed", "preflight_refused", "network_call_failed", "network_result_refused", "partial_evidence_mismatch", "partial_command_mismatch", "partial_private_boundary", "missing_reference", "reference_copy_failed":
		report.Code = code
	}
	boolean := func(key string) *bool {
		v, ok := value[key].(bool)
		if !ok {
			return nil
		}
		return &v
	}
	counter := func(key string) *int {
		v, ok := value[key].(float64)
		if !ok || v < 0 || v > 2 || float64(int(v)) != v {
			return nil
		}
		n := int(v)
		return &n
	}
	report.ConfigWasCanonical = boolean("config_was_canonical")
	report.ConfigCanonical = boolean("config_canonical")
	report.ReferenceExists = boolean("reference_exists")
	report.VerifiedPartial = boolean("verified_partial")
	report.VerifierCalls = counter("verifier_calls")
	report.NetworkCalls = counter("network_calls")
	raw, _ := json.Marshal(report)
	return string(raw)
}

func TestWalletNetworkFailureReportAllowlist(t *testing.T) {
	raw := []byte(`{"stage":"failed","step":"initial-partial-command","code":"preflight_refused","config_was_canonical":false,"config_canonical":true,"reference_exists":false,"verified_partial":false,"verifier_calls":1,"network_calls":0}`)
	var value map[string]any
	if json.Unmarshal(raw, &value) != nil {
		t.Fatal("fixture JSON")
	}
	report := walletNetworkFailureReport(value)
	for _, want := range []string{`"step":"initial-partial-command"`, `"code":"preflight_refused"`, `"config_canonical":true`, `"network_calls":0`} {
		if !strings.Contains(report, want) {
			t.Fatal("required public evidence lost")
		}
	}
	value["step"] = "PRIVATE_SENTINEL"
	value["code"] = "PRIVATE_SENTINEL"
	value["config_canonical"] = "PRIVATE_SENTINEL"
	value["network_calls"] = 1000.0
	value["stderr"] = "PRIVATE_SENTINEL"
	report = walletNetworkFailureReport(value)
	if strings.Contains(report, "PRIVATE_SENTINEL") || strings.Contains(report, "stderr") || !strings.Contains(report, `"step":"unknown"`) || !strings.Contains(report, `"config_canonical":null`) || !strings.Contains(report, `"network_calls":null`) {
		t.Fatal("untrusted failure fields leaked")
	}
	for _, bad := range []any{true, -1.0, 1.5, "1", nil} {
		value["verifier_calls"] = bad
		if !strings.Contains(walletNetworkFailureReport(value), `"verifier_calls":null`) {
			t.Fatal("invalid count admitted")
		}
	}
	recovery := walletNetworkFailureReport(map[string]any{"stage": "failed", "step": "readonly-pending-recovery"})
	if !strings.Contains(recovery, `"step":"readonly-pending-recovery"`) {
		t.Fatal("PR45 recovery stage lost")
	}
	for _, step := range []string{"submission-config", "partial-submission-refusal", "prepare-0", "prepare-1", "submit-0", "submit-1", "reconcile-0", "reconcile-1"} {
		report := walletNetworkFailureReport(map[string]any{"stage": "failed", "step": step})
		if !strings.Contains(report, `"step":"`+step+`"`) {
			t.Fatal("pending scenario stage lost")
		}
	}
	legacy := walletNetworkFailureReport(map[string]any{"stage": "failed", "step": "initial-catchup"})
	if !strings.Contains(legacy, `"step":"initial-catchup"`) || !strings.Contains(legacy, `"code":"unknown"`) {
		t.Fatal("old sync failure compatibility")
	}
}
