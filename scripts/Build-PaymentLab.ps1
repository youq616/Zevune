# Build the isolated no-value payment laboratory. Does not install tools or start nodes.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
foreach ($tool in @('go','cargo','rustup')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Required build tool not found: $tool. No software was installed." }
}
$bin = Join-Path $root 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$extension = if ($IsWindows -or $env:OS -eq 'Windows_NT') { '.exe' } else { '' }
Push-Location (Join-Path $root 'integration/payment')
try {
    & cargo build --locked --release --bins
    if ($LASTEXITCODE -ne 0) { throw 'Rust build failed. Do not run stale binaries.' }
    foreach ($name in @('zevune-crypto','zevune-wallet-session')) {
        Copy-Item -LiteralPath (Join-Path 'target/release' "$name$extension") -Destination (Join-Path $bin "$name$extension") -Force
    }
} finally { Pop-Location }
Push-Location (Join-Path $root 'integration/cometbft')
try {
    & go build -mod=readonly -trimpath -o (Join-Path $bin "zevune-paynet$extension") ./cmd/zevune-paynet
    if ($LASTEXITCODE -ne 0) { throw 'Go build failed. Do not start the laboratory.' }
} finally { Pop-Location }
& (Join-Path $bin "zevune-crypto$extension") version
if ($LASTEXITCODE -ne 0) { throw 'Crypto executable check failed.' }
& (Join-Path $bin "zevune-paynet$extension") -action version
if ($LASTEXITCODE -ne 0) { throw 'Network executable check failed.' }
Write-Host 'Local test-asset binaries built. No wallet, network or real asset was created.'
