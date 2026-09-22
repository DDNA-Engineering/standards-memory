$ErrorActionPreference = 'Stop'

$DistributionRoot = $PSScriptRoot
$Python = Join-Path $DistributionRoot '.venv\Scripts\python.exe'
$ReadyMarker = Join-Path $DistributionRoot '.standardsforge\prepared-distribution.json'
if (-not (Test-Path -LiteralPath $Python) -or -not (Test-Path -LiteralPath $ReadyMarker)) {
    & (Join-Path $DistributionRoot 'setup.ps1')
}

$Database = Join-Path $DistributionRoot '.standardsforge\memory.db'
$ObjectStore = Join-Path $DistributionRoot '.standardsforge\objects'
& $Python -I -m standardsforge --db $Database --store $ObjectStore @args
exit $LASTEXITCODE
