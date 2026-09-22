# StandardsForge ready-to-query distribution

This package contains StandardsForge and a precompiled local evidence corpus for the publicly distributed current MIL-STD components included in its recorded DLA source baseline. No standards download, PDF compilation, or network access is required. The one-time local setup validates and indexes the compiled packs in the extracted directory.

The exact acquisition snapshot is preserved at `provenance/acquisition-manifest.json`. Its digest, selection rules, exclusions, failed-acquisition and extraction counts, and representation review coverage are recorded in `provenance/source-baseline.json`. The included `corpus/corpus.json` inventories the compiled pack set. Publisher currentness does not replace a project's approved contractual baseline.

`provenance/wheel-build.json` binds the bundled wheel to its exact source-file inventory, fixed source epoch, pinned build backend, two byte-identical clean builds, and isolated core smoke. `bundle-manifest.json` records and inventories that provenance alongside every release file.

## Start the offline core

The prepared core supports 64-bit Windows and Linux plus Intel and Apple silicon macOS with CPython 3.11 or newer. It installs the bundled core wheel and corpus with package-index access disabled. Choose the commands for the host platform.

PowerShell:

```powershell
python .\setup.py
python .\run.py search "environmental testing" --principal local-user --limit 5
```

POSIX shell:

```sh
sh ./setup.sh
sh ./standardsforge.sh search "environmental testing" --principal local-user --limit 5
```

`setup.py` is the portable implementation; `setup.sh` invokes it with `python3`. `run.py` and `standardsforge.sh` validate the manifest-bound receipt and owned runtime before every launch, anchor the database and object store to this extracted directory, and forward only the CLI arguments. Rerun setup for a full closed-bundle revalidation. Setup validates and installs the already-compiled packs and proves full-integrity doctor plus a real search. It does not acquire standards, compile PDFs, call a model, or resolve a package from the network.

## Choose an MCP channel

The prepared GitHub archive and the PyPI project are separate distribution channels. This archive contains the rights-qualified corpus and never needs PyPI for core setup or query. The PyPI project contains independently built code only; it neither bundles nor downloads standards content.

For a fully offline MCP installation, use 64-bit Windows with CPython 3.12:

```powershell
.\setup.ps1
```

That Windows-only path installs StandardsForge and its exact hash-locked MCP dependency closure from the included wheelhouse, then proves a real stdio MCP round trip. Model hosts use `standardsforge-mcp.ps1`.

On Linux or macOS, first complete the offline core setup above. MCP then requires this explicit networked code/dependency install from PyPI into a separate environment outside the distribution; replace `PREPARED_VERSION` with the exact `version` in `bundle-manifest.json`:

```sh
MCP_VENV=/absolute/path/to/standardsforge-mcp-venv
PREPARED_ROOT=/absolute/path/to/standardsforge-ready-PREPARED_VERSION
python3 -m venv "$MCP_VENV"
"$MCP_VENV/bin/python" -m pip install "standardsforge[mcp]==PREPARED_VERSION"
"$MCP_VENV/bin/python" -I -m standardsforge.mcp_server \
  --db "$PREPARED_ROOT/.standardsforge/memory.db" \
  --store "$PREPARED_ROOT/.standardsforge/objects" \
  --principal local-user \
  --result-mode structured_only
```

Keep the networked MCP environment outside the extracted archive so the archive's closed inventory remains unchanged. The server command uses the distribution-local corpus state and does not fetch standards. Use the same absolute paths in a model host.

## Connect Claude Desktop, Claude Code, or Cursor

Replace the example directory with the absolute path to this extracted release. Claude Desktop and Cursor both accept an `mcpServers` entry; for Cursor place it in `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "standardsforge": {
      "command": "powershell.exe",
      "args": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\absolute\\path\\to\\standardsforge-ready-PREPARED_VERSION\\standardsforge-mcp.ps1"]
    }
  }
}
```

Claude Code can register the same local stdio process:

```powershell
claude mcp add standardsforge -- powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\absolute\path\to\standardsforge-ready-PREPARED_VERSION\standardsforge-mcp.ps1"
claude mcp get standardsforge
```

The launcher fixes the trusted principal to `local-user`, exposes only the seven declared read tools, and writes no startup banner to protocol stdout. Use `list_documents` when the exact installed identifier is unknown; the returned packages and continuations remain bound to that principal.

The bundle is offline and read-only during queries. Its database contains grants only for the generic local principal `local-user`.

## Evidence boundary

The corpus contains source-linked physical-page text and a separate automated, unreviewed MIL-STD-810H outline. Search results identify evidence candidates; they do not establish product applicability, approved requirements, test adequacy, or compliance. Review [CONTENT-NOTICE.md](CONTENT-NOTICE.md) before redistributing the standards evidence.
