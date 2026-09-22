$ErrorActionPreference = 'Stop'

$DistributionRoot = $PSScriptRoot
$Python = Join-Path $DistributionRoot '.venv\Scripts\python.exe'
$ReadyMarker = Join-Path $DistributionRoot '.standardsforge\prepared-distribution.json'
if ($args.Count -ne 0) {
    [Console]::Error.WriteLine('standardsforge-mcp.ps1 does not accept state, principal, or server overrides.')
    exit 2
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or -not (Test-Path -LiteralPath $ReadyMarker -PathType Leaf)) {
    [Console]::Error.WriteLine('StandardsForge is not ready. Run setup.ps1 before connecting an MCP host.')
    exit 1
}
try {
    $Marker = Get-Content -LiteralPath $ReadyMarker -Raw -Encoding utf8 | ConvertFrom-Json
} catch {
    [Console]::Error.WriteLine('StandardsForge readiness state is invalid. Run setup.ps1 again.')
    exit 1
}
if ($Marker.status -ne 'ready' -or $Marker.mcp_status -ne 'ready' -or $Marker.principal_id -ne 'local-user') {
    [Console]::Error.WriteLine('StandardsForge MCP readiness is not valid. Run setup.ps1 again.')
    exit 1
}

$Database = Join-Path $DistributionRoot '.standardsforge\memory.db'
$ObjectStore = Join-Path $DistributionRoot '.standardsforge\objects'
& $Python -I -m standardsforge.mcp_server --db $Database --store $ObjectStore --principal local-user --result-mode structured_only
exit $LASTEXITCODE
