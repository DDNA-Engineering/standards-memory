$ErrorActionPreference = 'Stop'

$DistributionRoot = $PSScriptRoot
$VirtualEnvironment = Join-Path $DistributionRoot '.venv'
$Python = Join-Path $VirtualEnvironment 'Scripts\python.exe'
$Database = Join-Path $DistributionRoot '.standardsforge\memory.db'
$ObjectStore = Join-Path $DistributionRoot '.standardsforge\objects'
$ReadyMarker = Join-Path $DistributionRoot '.standardsforge\prepared-distribution.json'

if (-not (Test-Path -LiteralPath $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv $VirtualEnvironment
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv $VirtualEnvironment
    } else {
        throw 'Python 3.11 or newer was not found on PATH.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the StandardsForge virtual environment.' }
}

$Wheels = @(Get-ChildItem -LiteralPath (Join-Path $DistributionRoot 'wheel') -Filter 'standardsforge-*.whl' -File)
if ($Wheels.Count -ne 1) { throw 'Expected exactly one StandardsForge wheel in the distribution.' }

& $Python -m pip install --disable-pip-version-check --no-deps $Wheels[0].FullName
if ($LASTEXITCODE -ne 0) { throw 'Unable to install StandardsForge from the bundled wheel.' }

if (-not (Test-Path -LiteralPath $ReadyMarker)) {
    & $Python -m standardsforge --db $Database --store $ObjectStore install-corpus `
        (Join-Path $DistributionRoot 'corpus\corpus.json') `
        --policy (Join-Path $DistributionRoot 'policies\mil-std-corpus-local.json')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install the precompiled MIL-STD corpus.' }

    & $Python -m standardsforge --db $Database --store $ObjectStore install `
        (Join-Path $DistributionRoot 'packs\mil-std-810h-derived-outline.zip') `
        --policy (Join-Path $DistributionRoot 'policies\mil-std-810h-derived-outline-local.json')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install the precompiled MIL-STD-810H outline.' }
}

& $Python -m standardsforge --db $Database --store $ObjectStore search 'environmental testing' --principal local-user --limit 1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'The prepared MIL-STD corpus did not pass its smoke query.' }

$Marker = @{
    installed_at = (Get-Date).ToUniversalTime().ToString('o')
    principal_id = 'local-user'
    status = 'ready'
} | ConvertTo-Json
New-Item -ItemType Directory -Path (Split-Path -Parent $ReadyMarker) -Force | Out-Null
Set-Content -LiteralPath $ReadyMarker -Value $Marker -Encoding utf8

Write-Host 'StandardsForge is ready.'
Write-Host '.\standardsforge.ps1 search "environmental testing" --principal local-user --limit 5'
