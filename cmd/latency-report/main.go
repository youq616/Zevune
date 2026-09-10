package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"github.com/youq616/Zevune/internal/latency"
	"os"
)

func main() {
	input := flag.String("input", "", "JSONL latency sample file (required)")
	env := flag.String("environment", "", "hardware/topology/workload description for measured samples")
	flag.Parse()
	if *input == "" {
		fmt.Fprintln(os.Stderr, "-input is required")
		os.Exit(2)
	}
	f, err := os.Open(*input)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer f.Close()
	report, err := latency.Summarize(f, *env)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err = enc.Encode(report); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
