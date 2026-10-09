$ErrorActionPreference = 'Stop'
# Only host-connection options pass through; the MCP mode is always the offline profile.
for ($Index = 0; $Index -lt $args.Count; $Index += 2) {
    if ($args[$Index] -notin @('--connect', '--host-config') -or $Index + 1 -ge $args.Count) {
        throw 'setup.ps1 accepts only --connect <claude-desktop|cursor|codex> and --host-config <file>. Use setup.py --help for other options.'
    }
}
$Probe = "import platform,sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] in {(3,11),(3,12),(3,13)} and platform.machine().lower() in {'amd64','x86_64'} and sys.maxsize > 2**32 else 1)"
$Candidates = @()
# Prefer a system interpreter: setup may need to replace .venv, and Windows cannot
# delete an interpreter that is running. The prepared .venv is only a last resort.
# Any of the three supported versions works offline; prefer the most widely qualified first.
if (Get-Command py -ErrorAction SilentlyContinue) { foreach ($Version in @('-3.12', '-3.13', '-3.11')) { $Candidates += ,@('py', $Version) } }
if (Get-Command python -ErrorAction SilentlyContinue) { $Candidates += ,@('python') }
$Existing = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $Existing -PathType Leaf) { $Candidates += ,@($Existing) }
foreach ($Candidate in $Candidates) {
    $Executable = $Candidate[0]
    $Prefix = @($Candidate | Select-Object -Skip 1)
    try { & $Executable @Prefix -I -c $Probe 2>$null } catch { continue }
    if ($LASTEXITCODE -eq 0) {
        & $Executable @Prefix -I (Join-Path $PSScriptRoot 'setup.py') --mcp @args
        exit $LASTEXITCODE
    }
}
throw 'Install 64-bit Python 3.11, 3.12 or 3.13 from python.org with the Python launcher, then run setup.cmd again. For another Python version, use python setup.py --mcp-online.'
