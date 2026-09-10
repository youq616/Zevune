// Package latency summarizes explicitly labelled per-transaction latency samples.
// It never benchmarks proofs, consensus or a network by itself.
package latency

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"sort"
)

type Sample struct {
	ID        string   `json:"tx_id"`
	Source    string   `json:"source"`
	Proof     *float64 `json:"proof_ms"`
	Admission *float64 `json:"admission_ms"`
	Finality  *float64 `json:"finality_ms"`
	Scan      *float64 `json:"wallet_scan_ms"`
}
type Stats struct {
	P50 float64 `json:"p50_ms"`
	P95 float64 `json:"p95_ms"`
	Max float64 `json:"max_ms"`
}
type Report struct {
	Kind        string `json:"kind"`
	Count       int    `json:"count"`
	Environment string `json:"environment"`
	EndToEnd    Stats  `json:"end_to_end"`
	Proof       Stats  `json:"proof"`
	Finality    Stats  `json:"post_admission_finality"`
	Note        string `json:"note"`
}

func stats(v []float64) Stats {
	sort.Float64s(v)
	at := func(p float64) float64 { return v[int(math.Ceil(p*float64(len(v))))-1] }
	return Stats{at(.5), at(.95), v[len(v)-1]}
}
func Summarize(r io.Reader, environment string) (Report, error) {
	var out Report
	scan := bufio.NewScanner(r)
	scan.Buffer(make([]byte, 4096), 16384)
	ids := map[string]bool{}
	var total, proof, finality []float64
	source := ""
	line := 0
	for scan.Scan() {
		line++
		if line > 100000 {
			return out, errors.New("too many samples")
		}
		if len(bytes.TrimSpace(scan.Bytes())) == 0 {
			return out, fmt.Errorf("blank record at line %d", line)
		}
		var s Sample
		dec := json.NewDecoder(bytes.NewReader(scan.Bytes()))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&s); err != nil {
			return out, fmt.Errorf("line %d: %w", line, err)
		}
		var extra any
		if err := dec.Decode(&extra); err != io.EOF {
			return out, errors.New("trailing data")
		}
		if s.ID == "" || ids[s.ID] {
			return out, errors.New("missing or duplicate tx_id")
		}
		ids[s.ID] = true
		if s.Source != "synthetic" && s.Source != "measurement" {
			return out, errors.New("source must be synthetic or measurement")
		}
		if source != "" && source != s.Source {
			return out, errors.New("cannot mix synthetic and measured samples")
		}
		source = s.Source
		sum := 0.0
		for _, v := range []*float64{s.Proof, s.Admission, s.Finality, s.Scan} {
			if v == nil || math.IsNaN(*v) || math.IsInf(*v, 0) || *v < 0 || *v > 86_400_000 {
				return out, errors.New("missing, invalid or unbounded duration")
			}
			sum += *v
		}
		total = append(total, sum)
		proof = append(proof, *s.Proof)
		finality = append(finality, *s.Finality)
	}
	if err := scan.Err(); err != nil {
		return out, err
	}
	if len(total) == 0 {
		return out, errors.New("no samples")
	}
	if source == "measurement" && environment == "" {
		return out, errors.New("measured data requires an environment description")
	}
	kind := "SYNTHETIC_NOT_NETWORK_BENCHMARK"
	if source == "measurement" {
		kind = "USER_SUPPLIED_MEASUREMENTS_NOT_INDEPENDENTLY_VERIFIED"
	}
	return Report{kind, len(total), environment, stats(total), stats(proof), stats(finality), "Nearest-rank percentiles. End-to-end computed per transaction, not by adding stage percentiles. Include timed-out and failed payments in the separate failure report."}, nil
}
