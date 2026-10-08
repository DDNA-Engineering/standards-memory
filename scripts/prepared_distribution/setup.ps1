$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0) { throw 'Use setup.py --help for portable setup options.' }
$Probe = "import platform,sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3,12) and platform.machine().lower() in {'amd64','x86_64'} else 1)"
$Candidates = @()
$Existing = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $Existing -PathType Leaf) { $Candidates += ,@($Existing) }
if (Get-Command py -ErrorAction SilentlyContinue) { $Candidates += ,@('py', '-3.12') }
if (Get-Command python -ErrorAction SilentlyContinue) { $Candidates += ,@('python') }
foreach ($Candidate in $Candidates) {
    $Executable = $Candidate[0]
    $Prefix = @($Candidate | Select-Object -Skip 1)
    try { & $Executable @Prefix -I -c $Probe 2>$null } catch { continue }
    if ($LASTEXITCODE -eq 0) {
        & $Executable @Prefix -I (Join-Path $PSScriptRoot 'setup.py') --mcp
        exit $LASTEXITCODE
    }
}
throw 'Install 64-bit Python 3.12 from python.org with the Python launcher, then run setup.cmd again. For another Python version, use python setup.py --mcp-online.'
