#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
go test ./... -count=1
go vet ./...
go run ./cmd/latency-report -input ./examples/latency-SYNTHETIC.jsonl
