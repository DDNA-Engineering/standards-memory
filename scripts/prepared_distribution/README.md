# StandardsForge ready-to-query library

The archive contains 447 precompiled packages: 438 acquisition-pinned MIL-STD page packs, the automated MIL-STD-810H outline-v3, two bounded MIL-STD-1661 recovery packs and six bounded agent-reviewed requirement scopes (MIL-STD-882E, 461H, 464D, 704F, 1474E and 1472H). No Git clone, standards download or PDF compilation is needed. First setup validates and indexes the library, checks every package and replays 294 bounded real-document cases. Allow several minutes and about 2.4 GB of free disk space beside this folder; setup checks before it starts.

## Install with a model connection

**Windows:** install 64-bit CPython 3.11, 3.12 or 3.13 with the Python launcher, then double-click `setup.cmd`. Terminal equivalent:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

This profile is fully offline, including its hash-locked MCP dependencies. With any other Python version, explicitly choose `python setup.py --mcp-online` instead.

**Linux/macOS:** use CPython 3.11+ with `venv`, open a terminal here, and run:

```sh
sh ./setup.sh --mcp-online
```

That option explicitly downloads MCP dependencies. The core code and standards come from the verified archive. Debian/Ubuntu Python may need its matching `python3-venv` package. Queries never download content or invoke a model.

## Connect your host

Setup makes a real stdio query and prints the paths to:

- `.standardsforge/mcp-config.json`: merge the StandardsForge server into Claude Desktop or Cursor's `mcpServers` configuration.
- `.standardsforge/codex-mcp.toml`: append the StandardsForge section to Codex's `config.toml`.

All paths are already absolute and escaped. Preserve other host entries, then restart the MCP connection. The host launches `.venv` Python with `-I run_mcp.py`; do not launch it manually and wait for a terminal prompt. It communicates over stdin/stdout.

To have setup add the entry for you, add `--connect claude-desktop`, `--connect cursor` or `--connect codex` (repeatable; `setup.ps1` accepts it too). Setup keeps a byte-exact backup, changes only the `standardsforge` entry and leaves files it cannot safely rewrite untouched. `--host-config <file>` selects another file for one host. Without `--connect`, setup does not modify host settings.

Codex or Claude Code can register the same launcher from this directory:

```powershell
codex mcp add standardsforge -- (Resolve-Path .\.venv\Scripts\python.exe).Path -I (Resolve-Path .\run_mcp.py).Path
```

```sh
codex mcp add standardsforge -- "$PWD/.venv/bin/python" -I "$PWD/run_mcp.py"
```

Replace `codex` with `claude` for Claude Code. Ask: "List installed MIL-STD-810 editions, find the low-pressure section and retrieve its exact evidence with original PDF links and coverage limits."

The runtime exposes eleven read-only tools; `select_evidence` token budgets use the bundled `o200k_base` counter, and `follow_references` follows the 23 bundled agent-reviewed references. Search discovers candidates; exact evidence retrieval verifies source spans, required context and authorization. Original PDF paths refer to files on the machine running MCP. Applicability, compliance and approval remain engineering decisions.

## Terminal only, offline

```sh
python setup.py
python run.py search "environmental testing" --principal local-user --query-mode natural_language --limit 5
```

Use `python3` on Linux/macOS. Windows/Linux x64 and Intel/Apple silicon macOS need CPython 3.11+ with SQLite FTS5. Core setup uses only the bundled wheel, with package indexes disabled. All launchers anchor state to this directory regardless of the current working directory.

Rerun the same setup command to revalidate. Extract new versions into new folders, run setup and switch the host to the newly generated configuration. Keep the old installation until the new connection works. Never transplant an old virtual environment or database into the new bundle.

## Evidence and provenance

`provenance/acquisition-manifest.json` preserves the source snapshot. `provenance/source-baseline.json` records selection, exclusions and incomplete coverage. `provenance/wheel-build.json` binds the code wheel to its source inventory and reproducible build. `bundle-manifest.json` inventories all immutable files; setup names any file in this folder that is not listed there, apart from files Finder or Explorer create on their own. Local generated state stays in `.standardsforge` and `.venv`.

The library retains source PDFs, edition identities, representation distinctions and review status. Page text and automated outlines are not a corpus-wide reviewed requirements graph. The 294 checks qualify selected evidence and context only; the six reviewed scopes are agent self-review, not human or independent review. Restricted components and unresolved pages remain explicit. See `CONTENT-NOTICE.md` for content boundaries.
