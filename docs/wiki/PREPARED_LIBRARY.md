# Prepared offline library

The published [StandardsForge `v0.1.0a7` release](https://github.com/DDNA-Engineering/standards-memory/releases/tag/v0.1.0a7) is the normal end-user path. It already contains the dependency-free StandardsForge wheel, compressed MIL-STD packs from the recorded public-source acquisition snapshot, exact local policies, setup and launcher scripts, and recorded provenance. Users do not reacquire PDFs or compile the corpus.

The GitHub prepared release and the PyPI project are separate channels. The prepared release carries the rights-qualified corpus and supports an offline core setup. PyPI carries independently built StandardsForge code only; it does not bundle, fetch, or authorize standards content.

Return to the [root quickstart](../../README.md#use-the-prepared-library-with-your-model) when you only need the commands.

## Requirements

- 64-bit Windows or Linux, or Intel or Apple silicon macOS.
- CPython 3.11 or newer with `venv`/`ensurepip`; Debian/Ubuntu system Python may require its matching `python3-venv` package.
- Windows PowerShell for the Windows examples, or a POSIX shell for the Linux and macOS wrappers.
- A Python build whose SQLite includes FTS5.
- About 4 GB of free disk space: the 1.1 GB download, 1.1 GB once extracted, and about 1.9 GB for the local index and Python environment (measured for a7 on Linux). The ZIP can be deleted after extraction. First setup checks free space before it starts indexing and stops with the amount needed.

A Git clone is not required.

## Install

1. Download the prepared `standardsforge-ready-<version>.zip` and matching `.sha256` from the [GitHub releases page](https://github.com/DDNA-Engineering/standards-memory/releases).
2. Optionally compare the archive with the published SHA-256 file.
3. Extract the ZIP to a durable local directory.
4. Open PowerShell or a POSIX shell in the extracted directory.
5. For a model connection, double-click `setup.cmd` on Windows with 64-bit Python 3.11, 3.12 or 3.13, or run `sh setup.sh --mcp-online` on Linux/macOS. Setup prints generated host configuration with the actual paths. Add `--connect claude-desktop`, `--connect cursor` or `--connect codex` to have setup add the entry for you; see [model integration](MODEL_INTEGRATION.md#connect-your-model-host).

Do not add your own files to the extracted folder: setup checks that it contains exactly the released files and names any file that does not belong. Files that macOS Finder and Windows Explorer create on their own (`.DS_Store`, `._*`, `Thumbs.db`, `desktop.ini`) are ignored.

For a terminal-only installation, use the offline core commands below.

PowerShell:

```powershell
python .\setup.py
```

Linux or macOS:

```sh
sh ./setup.sh
```

`setup.py` is the portable implementation; `setup.sh` invokes it with `python3`. Setup validates the closed bundle inventory before writes, creates an isolated environment, installs only the bundled wheel with package-index access disabled, validates and installs the included packs, builds the local index, runs full-integrity doctor and search smokes, and records a receipt. It does not acquire standards, compile PDFs, call a model, or need a Git checkout.

Rerunning setup revalidates the bundle and installed state. MCP setup also proves a real stdio query and writes `.standardsforge/mcp-config.json` and `.standardsforge/codex-mcp.toml`. Only `--mcp-online` resolves dependencies from the network; core code and standards always use the bundled files. Extract upgrades into a new folder and switch the host configuration after setup succeeds.

## Prove readiness

```powershell
python .\run.py doctor `
  --policy policies\prepared-local.json `
  --principal local-user `
  --full-integrity
```

```sh
sh ./standardsforge.sh doctor \
  --policy policies/prepared-local.json \
  --principal local-user \
  --full-integrity
```

A completed ready report exits `0`. A completed `not_ready` report exits `3`; typed command errors exit `2`, and unexpected internal failures exit `1`. `doctor` opens the existing store read-only. It does not repair, migrate, fetch, install, revoke, or invoke a model.

`run.py` and `standardsforge.sh` validate the manifest-bound receipt and owned runtime, anchor all state to the extracted directory, and forward only the query arguments. Rerun setup for a full closed-bundle revalidation. The shell launcher therefore works independently of the caller's current directory.

## Search

```powershell
python .\run.py search "environmental testing" `
  --principal local-user `
  --limit 5
```

```sh
sh ./standardsforge.sh search "environmental testing" \
  --principal local-user \
  --limit 5
```

Search returns candidate records with package identity, citations, coverage, and interpretation limits. Search is discovery, not a determination that a standard applies.

## Pin a representation

When multiple representations exist for one edition, resolve the exact representation and reuse its package digest:

```powershell
$resolved = python .\run.py resolve 'MIL-STD-810H(1)' `
  --representation derived_structure `
  --principal local-user | ConvertFrom-Json

$pin = $resolved.result.package_digest

python .\run.py search "low pressure" `
  --package-digest $pin `
  --principal local-user `
  --limit 5
```

The digest pins the installed package bytes. It does not select a project baseline or approve applicability.

## Local state

Runtime state stays inside the extracted distribution. Keep the extracted directory together if you move or back it up. The source repository's ignored `.standardsforge/` directory is separate machine-local development state and is not the end-user distribution.

## MCP installation choices

On Windows x64 CPython 3.11, 3.12 or 3.13, double-click `setup.cmd` or run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`. One command installs the library and bundled MCP dependencies offline, choosing the hash lock that matches the prepared environment's Python version. `setup.ps1` also accepts `--connect <host>` and `--host-config <file>`.

On Linux/macOS, run `sh ./setup.sh --mcp-online`. This explicit option downloads MCP dependencies for the bundled code wheel into the same owned environment. Standards queries remain offline.

Both paths generate host configuration with the actual absolute paths, install the bundled `o200k_base` token counter for `select_evidence` budgets, and prove a real stdio query, including a token-budgeted evidence selection. See [model integration](MODEL_INTEGRATION.md#connect-your-model-host) for host configuration locations.

## Snapshot scope

The prepared library is a fixed acquisition snapshot completed September 21, 2026 against the DLA ASSIST dataset marked updated September 18, 2026. The complete 438-pack inventory is in the [root README](../../README.md#complete-prepared-library-snapshot).

The published a7 archive contains 441 packages: 438 page-text packs from 912 verified PDFs, a separate automated, unreviewed 8,319-record MIL-STD-810H `outline-v3` pack, and two bounded MIL-STD-1661 recovery packs. This content baseline is unchanged from a6. Later source-only outline (`outline-v4`, `outline-v5`) and reviewer changes are not part of this frozen release. Its included `CONTENT-NOTICE.md` is frozen with that archive; the [source template](../../scripts/prepared_distribution/CONTENT-NOTICE.md) describes the notice for future builds and must not be mistaken for an update to the published asset.

The prepared set contains every selected publicly exposed current component for those packs. Twenty-five packs are explicitly partial because their current DLA composition also includes restricted components. Restricted bytes and restricted-only records are not included.

Snapshot currentness does not establish a project's approved baseline, and public availability does not establish blanket redistribution permission.

## Next steps

- Learn the eleven evidence operations in the [query guide](QUERY_GUIDE.md).
- Connect a local model using [MCP](MODEL_INTEGRATION.md).
- Read the [architecture and trust boundaries](ARCHITECTURE_AND_TRUST.md).
