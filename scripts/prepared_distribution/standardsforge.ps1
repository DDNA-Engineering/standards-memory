$ErrorActionPreference = 'Stop'
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    [Console]::Error.WriteLine('Run setup.py before querying the prepared library.')
    exit 1
}
& $Python -I (Join-Path $PSScriptRoot 'run.py') @args
exit $LASTEXITCODE
