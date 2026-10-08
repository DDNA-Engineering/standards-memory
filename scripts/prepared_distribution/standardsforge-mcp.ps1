$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0) {
    [Console]::Error.WriteLine('The prepared MCP launcher does not accept overrides.')
    exit 2
}
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    [Console]::Error.WriteLine('Run setup.cmd before connecting a model.')
    exit 1
}
& $Python -I (Join-Path $PSScriptRoot 'run_mcp.py')
exit $LASTEXITCODE
