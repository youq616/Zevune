# Start only an already-initialized local test-asset cluster; never reset state.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$NetworkHome)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$ext = if ($IsWindows -or $env:OS -eq 'Windows_NT') { '.exe' } else { '' }
$net = Join-Path $root "bin/zevune-paynet$ext"
$crypto = Join-Path $root "bin/zevune-crypto$ext"
foreach ($path in @($net,$crypto)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Build the payment laboratory before starting it.' } }
& $net -action start -home $NetworkHome -crypto $crypto
if ($LASTEXITCODE -ne 0) { throw 'Local cluster stopped with an error. Preserve its directory and signing state.' }
