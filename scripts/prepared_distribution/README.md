# StandardsForge ready-to-query distribution

This package contains StandardsForge and a precompiled local evidence corpus for the publicly distributed current MIL-STD components included in its recorded DLA source baseline. No standards download, PDF compilation, or network access is required. The one-time local setup validates and indexes the compiled packs in the extracted directory.

The exact acquisition snapshot is preserved at `provenance/acquisition-manifest.json`. Its digest, selection rules, exclusions, failed-acquisition and extraction counts, and representation review coverage are recorded in `provenance/source-baseline.json`. The included `corpus/corpus.json` inventories the compiled pack set. Publisher currentness does not replace a project's approved contractual baseline.

`provenance/wheel-build.json` binds the bundled wheel to its exact source-file inventory, fixed source epoch, pinned build backend, two byte-identical clean builds, and isolated core smoke. `bundle-manifest.json` records and inventories that provenance alongside every release file.

## Start

Install 64-bit CPython 3.12 for Windows, open PowerShell in this directory, and run:

```powershell
.\setup.ps1
.\standardsforge.ps1 search "environmental testing" --principal local-user --limit 5
```

`setup.ps1` creates an isolated Python 3.12 environment, installs StandardsForge and its exact hash-locked Windows x64 MCP dependency closure only from the offline wheelhouse, validates and installs the precompiled packs, and proves both a local query and a real stdio MCP round trip. Subsequent queries use `standardsforge.ps1`; model hosts use `standardsforge-mcp.ps1`. Both launchers resolve state from this extracted directory, independent of the host working directory.

## Connect Claude Desktop, Claude Code, or Cursor

Replace the example directory with the absolute path to this extracted release. Claude Desktop and Cursor both accept an `mcpServers` entry; for Cursor place it in `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "standardsforge": {
      "command": "powershell.exe",
      "args": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\absolute\\path\\to\\standardsforge-ready-0.1.0a1\\standardsforge-mcp.ps1"]
    }
  }
}
```

Claude Code can register the same local stdio process:

```powershell
claude mcp add standardsforge -- powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\absolute\path\to\standardsforge-ready-0.1.0a1\standardsforge-mcp.ps1"
claude mcp get standardsforge
```

The launcher fixes the trusted principal to `local-user`, exposes only the six read tools, and writes no startup banner to protocol stdout.

The bundle is offline and read-only during queries. Its database contains grants only for the generic local principal `local-user`.

## Evidence boundary

The corpus contains source-linked physical-page text and a separate automated, unreviewed MIL-STD-810H outline. Search results identify evidence candidates; they do not establish product applicability, approved requirements, test adequacy, or compliance. Review [CONTENT-NOTICE.md](CONTENT-NOTICE.md) before redistributing the standards evidence.
