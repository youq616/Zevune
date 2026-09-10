# Local wallet wrapper. Passwords go directly to hidden Rust prompts, never arguments.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('New','Address','Backup','Restore','Balance','Send')][string]$Action,
    [Parameter(Mandatory=$true)][string]$Wallet,
    [string]$NetworkHome,
    [string]$Destination,
    [string]$Recipient,
    [UInt64]$Units = 0
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$ext = if ($IsWindows -or $env:OS -eq 'Windows_NT') { '.exe' } else { '' }
$crypto = Join-Path $root "bin/zevune-crypto$ext"
$net = Join-Path $root "bin/zevune-paynet$ext"
foreach ($path in @($crypto,$net)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Build the local laboratory first.' } }
function Invoke-Checked([string]$Program,[string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Local command failed: $($Arguments[0])." }
}
switch ($Action) {
    'New' { Invoke-Checked $crypto @('wallet-new',$Wallet); return }
    'Address' { Invoke-Checked $crypto @('address',$Wallet); return }
    'Backup' { if (-not $Destination) { throw 'Destination is required; it must not exist.' }; Invoke-Checked $crypto @('backup',$Wallet,$Destination); return }
    'Restore' { if (-not $Destination) { throw 'Destination is required; it must not exist.' }; Invoke-Checked $crypto @('restore',$Wallet,$Destination); return }
}
if (-not $NetworkHome) { throw 'NetworkHome is required for Balance and Send.' }
if ($Action -eq 'Send' -and (-not $Recipient -or $Units -eq 0)) { throw 'Recipient and positive test Units are required.' }
$session = Join-Path ([IO.Path]::GetTempPath()) ('Zevune-payment-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $session | Out-Null
$export = Join-Path $session 'verified-public-history.json'
$tx = Join-Path $session 'prepared-public-transaction.bin'
$genesis = Join-Path $NetworkHome 'payment-genesis.bin'
Invoke-Checked $net @('-action','export','-home',$NetworkHome,'-out',$export)
if ($Action -eq 'Balance') { Invoke-Checked $crypto @('balance',$Wallet,$export,$genesis); return }
Invoke-Checked $crypto @('prepare',$Wallet,$export,$genesis,$Recipient,$Units.ToString([Globalization.CultureInfo]::InvariantCulture),$tx)
Write-Host "Prepared public transaction retained at: $tx"
& $net -action submit -home $NetworkHome -tx $tx
if ($LASTEXITCODE -ne 0) {
    throw "Submission did not produce a confirmed receipt. Preserve $tx and check the network history before preparing another transaction."
}
Write-Host 'Only valueless local test assets were used. The public transaction file is retained for receipt checking.'
