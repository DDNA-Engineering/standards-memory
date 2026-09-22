$ErrorActionPreference = 'Stop'

$DistributionRoot = $PSScriptRoot
$VirtualEnvironment = Join-Path $DistributionRoot '.venv'
$Python = Join-Path $VirtualEnvironment 'Scripts\python.exe'
$Database = Join-Path $DistributionRoot '.standardsforge\memory.db'
$ObjectStore = Join-Path $DistributionRoot '.standardsforge\objects'
$ReadyMarker = Join-Path $DistributionRoot '.standardsforge\prepared-distribution.json'
$BundleManifest = Join-Path $DistributionRoot 'bundle-manifest.json'
$McpRequirementsPath = Join-Path $DistributionRoot 'provenance\mcp-wheelhouse-win-amd64-cp312.txt'

function Test-PreparedDistribution {
    if (-not (Test-Path -LiteralPath $BundleManifest -PathType Leaf)) {
        throw 'The prepared-distribution manifest is missing.'
    }
    try {
        $Manifest = Get-Content -LiteralPath $BundleManifest -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        throw 'The prepared-distribution manifest is not valid JSON.'
    }
    if ($Manifest.schema_version -ne '1.2' -or $Manifest.product -ne 'StandardsForge prepared distribution') {
        throw 'The prepared-distribution manifest identity is invalid.'
    }
    if ($Manifest.build.archive_source_date_epoch -ne 1767225600 -or
        $Manifest.build.wheel_build_backend -ne 'setuptools==84.0.0' -or
        $Manifest.build.wheel_generator -ne 'setuptools (84.0.0)' -or
        $Manifest.build.mcp_requirement -ne 'mcp==2.2.0' -or
        $Manifest.build.runtime_python -ne 'CPython 3.12' -or
        $Manifest.build.runtime_platform -ne 'win_amd64' -or
        [int]$Manifest.build.mcp_wheel_count -lt 1) {
        throw 'The prepared-distribution build identity is invalid.'
    }
    $RootPath = [System.IO.Path]::GetFullPath($DistributionRoot).TrimEnd('\', '/')
    $RootPrefix = $RootPath + [System.IO.Path]::DirectorySeparatorChar
    $Seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($Entry in @($Manifest.files)) {
        $RelativePath = [string]$Entry.path
        if ([string]::IsNullOrWhiteSpace($RelativePath) -or [System.IO.Path]::IsPathRooted($RelativePath)) {
            throw 'The prepared-distribution inventory contains an invalid path.'
        }
        $Segments = $RelativePath -split '[\\/]'
        if ($Segments -contains '..' -or -not $Seen.Add(($Segments -join '/'))) {
            throw 'The prepared-distribution inventory contains an unsafe or duplicate path.'
        }
        $Target = [System.IO.Path]::GetFullPath((Join-Path $DistributionRoot $RelativePath))
        if (-not $Target.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'The prepared-distribution inventory escapes the distribution root.'
        }
        $File = Get-Item -LiteralPath $Target -ErrorAction Stop
        if ($File.PSIsContainer -or $File.Length -ne [long]$Entry.bytes) {
            throw "Prepared-distribution size validation failed: $RelativePath"
        }
        $Digest = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Digest -ne [string]$Entry.sha256) {
            throw "Prepared-distribution digest validation failed: $RelativePath"
        }
    }
    if ($Seen.Count -eq 0) {
        throw 'The prepared-distribution inventory is empty.'
    }
    $McpWheels = @($Manifest.files | Where-Object { ([string]$_.path) -like 'wheelhouse/*.whl' })
    if ($McpWheels.Count -ne [int]$Manifest.build.mcp_wheel_count) {
        throw 'The prepared-distribution MCP wheelhouse count is inconsistent.'
    }
    $McpWheelByName = @{}
    [string[]]$McpWheelNames = @($McpWheels | ForEach-Object {
        $WheelName = ([string]$_.path -split '/')[-1]
        $McpWheelByName[$WheelName] = $_
        $WheelName
    })
    [System.Array]::Sort($McpWheelNames, [System.StringComparer]::Ordinal)
    $InventoryRows = @($McpWheelNames | ForEach-Object {
        $Entry = $McpWheelByName[$_]
        "$(($Entry.sha256).ToString()) $([long]$Entry.bytes) $_`n"
    })
    $InventoryBytes = [System.Text.Encoding]::UTF8.GetBytes(($InventoryRows -join ''))
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $InventoryDigest = ([System.BitConverter]::ToString($Hasher.ComputeHash($InventoryBytes))).Replace('-', '').ToLowerInvariant()
    } finally {
        $Hasher.Dispose()
    }
    if ($InventoryDigest -ne [string]$Manifest.build.mcp_wheelhouse_sha256) {
        throw 'The prepared-distribution MCP wheelhouse digest is inconsistent.'
    }
    $McpRequirementsDigest = (Get-FileHash -LiteralPath $McpRequirementsPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($McpRequirementsDigest -ne [string]$Manifest.build.mcp_requirements_sha256) {
        throw 'The prepared-distribution MCP requirements digest is inconsistent.'
    }

    $ScopePath = Join-Path $DistributionRoot 'provenance\source-baseline.json'
    $AcquisitionPath = Join-Path $DistributionRoot 'provenance\acquisition-manifest.json'
    try {
        $Scope = Get-Content -LiteralPath $ScopePath -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        throw 'The prepared-distribution source baseline is missing or invalid.'
    }
    if ($Scope.acquisition.manifest_path -ne 'provenance/acquisition-manifest.json') {
        throw 'The source baseline points to an unexpected acquisition manifest.'
    }
    $AcquisitionDigest = (Get-FileHash -LiteralPath $AcquisitionPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($AcquisitionDigest -ne [string]$Scope.acquisition.manifest_sha256) {
        throw 'The bundled acquisition manifest does not match the source baseline.'
    }

    $WheelProvenancePath = Join-Path $DistributionRoot 'provenance\wheel-build.json'
    try {
        $WheelProvenance = Get-Content -LiteralPath $WheelProvenancePath -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        throw 'The prepared-distribution wheel provenance is missing or invalid.'
    }
    if ($WheelProvenance.wheel.sha256 -ne [string]$Manifest.build.wheel_sha256 -or
        $WheelProvenance.source_date_epoch -ne $Manifest.build.archive_source_date_epoch -or
        $WheelProvenance.build_backend -ne $Manifest.build.wheel_build_backend -or
        $WheelProvenance.wheel_generator -ne $Manifest.build.wheel_generator) {
        throw 'The bundled wheel provenance does not match the distribution build identity.'
    }
    return $Manifest
}

$Manifest = Test-PreparedDistribution
$RuntimeProbe = "import platform,sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) and platform.machine().lower() in {'amd64', 'x86_64'} else 1)"

if (-not (Test-Path -LiteralPath $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -I -c $RuntimeProbe
        if ($LASTEXITCODE -ne 0) { throw 'The prepared distribution requires 64-bit CPython 3.12 on Windows.' }
        py -3.12 -I -m venv $VirtualEnvironment
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -I -c $RuntimeProbe
        if ($LASTEXITCODE -ne 0) { throw 'The prepared distribution requires 64-bit CPython 3.12 on Windows.' }
        python -I -m venv $VirtualEnvironment
    } else {
        throw '64-bit CPython 3.12 was not found on PATH.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the StandardsForge virtual environment.' }
}

& $Python -I -c $RuntimeProbe
if ($LASTEXITCODE -ne 0) { throw 'The prepared distribution requires 64-bit CPython 3.12 on Windows.' }

$Wheels = @(Get-ChildItem -LiteralPath (Join-Path $DistributionRoot 'wheel') -Filter 'standardsforge-*.whl' -File)
if ($Wheels.Count -ne 1) { throw 'Expected exactly one StandardsForge wheel in the distribution.' }

$Wheelhouse = Join-Path $DistributionRoot 'wheelhouse'
& $Python -I -m pip install --disable-pip-version-check --no-index --find-links $Wheelhouse --require-hashes --no-deps --force-reinstall --requirement $McpRequirementsPath
if ($LASTEXITCODE -ne 0) { throw 'Unable to install the exact MCP dependency closure from the bundled wheelhouse.' }
& $Python -I -m pip install --disable-pip-version-check --no-index --no-deps --force-reinstall $Wheels[0].FullName
if ($LASTEXITCODE -ne 0) { throw 'Unable to install StandardsForge from the bundled wheel.' }
& $Python -I -m pip check
if ($LASTEXITCODE -ne 0) { throw 'The bundled StandardsForge MCP environment has inconsistent dependencies.' }
& $Python -I (Join-Path $DistributionRoot 'verify_mcp_environment.py') --requirements $McpRequirementsPath --standardsforge-version ([string]$Manifest.version)
if ($LASTEXITCODE -ne 0) { throw 'The prepared environment differs from its exact runtime lock.' }

if (-not (Test-Path -LiteralPath $ReadyMarker)) {
    & $Python -I -m standardsforge --db $Database --store $ObjectStore install-corpus `
        (Join-Path $DistributionRoot 'corpus\corpus.json') `
        --policy (Join-Path $DistributionRoot 'policies\mil-std-corpus-local.json')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install the precompiled MIL-STD corpus.' }

    & $Python -I -m standardsforge --db $Database --store $ObjectStore install `
        (Join-Path $DistributionRoot 'packs\mil-std-810h-derived-outline.zip') `
        --policy (Join-Path $DistributionRoot 'policies\mil-std-810h-derived-outline-local.json')
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install the precompiled MIL-STD-810H outline.' }
}

& $Python -I -m standardsforge --db $Database --store $ObjectStore search 'environmental testing' --principal local-user --limit 1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'The prepared MIL-STD corpus did not pass its smoke query.' }
& $Python -I (Join-Path $DistributionRoot 'smoke_mcp.py') --db $Database --store $ObjectStore --principal local-user --query 'environmental testing'
if ($LASTEXITCODE -ne 0) { throw 'The prepared MIL-STD MCP server did not pass its stdio smoke query.' }

$Marker = @{
    installed_at = (Get-Date).ToUniversalTime().ToString('o')
    principal_id = 'local-user'
    status = 'ready'
    mcp_status = 'ready'
} | ConvertTo-Json
New-Item -ItemType Directory -Path (Split-Path -Parent $ReadyMarker) -Force | Out-Null
Set-Content -LiteralPath $ReadyMarker -Value $Marker -Encoding utf8

Write-Host 'StandardsForge is ready.'
Write-Host '.\standardsforge.ps1 search "environmental testing" --principal local-user --limit 5'
Write-Host '.\standardsforge-mcp.ps1'
