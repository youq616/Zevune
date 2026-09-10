$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & go test ./... -count=1
    if ($LASTEXITCODE -ne 0) { throw 'go test failed' }
    & go vet ./...
    if ($LASTEXITCODE -ne 0) { throw 'go vet failed' }
    & go run ./cmd/latency-report -input ./examples/latency-SYNTHETIC.jsonl
    if ($LASTEXITCODE -ne 0) { throw 'sample report failed' }
} finally { Pop-Location }
