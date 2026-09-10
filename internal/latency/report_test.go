package latency

import (
	"strings"
	"testing"
)

const sample = `{"tx_id":"a","source":"synthetic","proof_ms":800,"admission_ms":100,"finality_ms":1500,"wallet_scan_ms":200}`

func TestSyntheticLabel(t *testing.T) {
	r, e := Summarize(strings.NewReader(sample), "")
	if e != nil {
		t.Fatal(e)
	}
	if r.Kind != "SYNTHETIC_NOT_NETWORK_BENCHMARK" || r.EndToEnd.P95 != 2600 {
		t.Fatal(r)
	}
}
func TestPercentile(t *testing.T) {
	s := stats([]float64{3, 1, 2})
	if s.P50 != 2 || s.P95 != 3 || s.Max != 3 {
		t.Fatal(s)
	}
}
func TestInvalidSamples(t *testing.T) {
	cases := map[string]string{"empty": "", "blank": "\n", "duplicate": sample + "\n" + sample, "negative": strings.Replace(sample, `"proof_ms":800`, `"proof_ms":-1`, 1), "missing": strings.Replace(sample, `"proof_ms":800,`, "", 1), "unknown": strings.Replace(sample, `"proof_ms":800`, `"unexpected":800`, 1), "source": strings.Replace(sample, `"synthetic"`, `"unlabelled"`, 1), "trailing": sample + " {}", "measurement-no-environment": strings.Replace(sample, `"synthetic"`, `"measurement"`, 1), "huge": strings.Replace(sample, `"proof_ms":800`, `"proof_ms":86400001`, 1)}
	for n, input := range cases {
		t.Run(n, func(t *testing.T) {
			if _, e := Summarize(strings.NewReader(input), ""); e == nil {
				t.Fatal("invalid sample accepted")
			}
		})
	}
}
func TestCannotMixSyntheticAndMeasurement(t *testing.T) {
	b := strings.Replace(strings.Replace(sample, `"synthetic"`, `"measurement"`, 1), `"a"`, `"b"`, 1)
	if _, e := Summarize(strings.NewReader(sample+"\n"+b), "test lab"); e == nil {
		t.Fatal("mixed sources accepted")
	}
}
func TestMeasurementsNotIndependentlyVerified(t *testing.T) {
	r, e := Summarize(strings.NewReader(strings.Replace(sample, `"synthetic"`, `"measurement"`, 1)), "lab")
	if e != nil || r.Kind != "USER_SUPPLIED_MEASUREMENTS_NOT_INDEPENDENTLY_VERIFIED" {
		t.Fatal(r, e)
	}
}
