# Prepared offline library

The prepared StandardsForge release is the normal end-user path. It already contains the dependency-free StandardsForge wheel, compressed public MIL-STD packs, exact local policies, setup and launcher scripts, and recorded provenance. Users do not reacquire PDFs or compile the corpus.

The GitHub prepared release and the PyPI project are separate channels. The prepared release carries the rights-qualified corpus and supports an offline core setup. PyPI carries independently built StandardsForge code only; it does not bundle, fetch, or authorize standards content.

Return to the [three-minute root quickstart](../../README.md#start-the-offline-library) when you only need the commands.

## Requirements

- 64-bit Windows or Linux, or Intel or Apple silicon macOS.
- CPython 3.11 or newer.
- Windows PowerShell for the Windows examples, or a POSIX shell for the Linux and macOS wrappers.
- A Python build whose SQLite includes FTS5.
- Enough local space for the approximately 1 GB archive plus its extracted packs, virtual environment, object store, and index.

A Git clone is not required.

## Install

1. Download the prepared `standardsforge-ready-<version>.zip` and matching `.sha256` from the [GitHub releases page](https://github.com/DDNA-Engineering/standards-memory/releases).
2. Optionally compare the archive with the published SHA-256 file.
3. Extract the ZIP to a durable local directory.
4. Open PowerShell or a POSIX shell in the extracted directory.
5. Run the platform-appropriate offline core setup.

PowerShell:

```powershell
python .\setup.py
```

Linux or macOS:

```sh
sh ./setup.sh
```

`setup.py` is the portable implementation; `setup.sh` invokes it with `python3`. Setup validates the closed bundle inventory before writes, creates an isolated environment, installs only the bundled wheel with package-index access disabled, validates and installs the included packs, builds the local index, runs full-integrity doctor and search smokes, and records a receipt. It does not acquire standards, compile PDFs, call a model, or need a Git checkout.

Rerunning setup revalidates the bundle and installed state rather than trusting a marker.

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

On 64-bit Windows with CPython 3.12, `setup.ps1` remains the fully offline MCP path. It installs the exact hash-locked MCP dependency closure from the archive's Windows wheelhouse and proves a real stdio round trip before marking MCP ready. Use `standardsforge-mcp.ps1` as the model-host command.

On Linux or macOS, complete the offline core setup first. Then create a separate environment outside the closed prepared directory and install the exact code/MCP package from PyPI:

```sh
MCP_VENV=/absolute/path/to/standardsforge-mcp-venv
python3 -m venv "$MCP_VENV"
"$MCP_VENV/bin/python" -m pip install "standardsforge[mcp]==0.1.0a4"
```

The pip command is an explicit networked code/dependency installation. It does not download the prepared corpus or any standards content. Start the installed module with absolute paths to the prepared distribution's `.standardsforge/memory.db` and `.standardsforge/objects`; the [model integration guide](MODEL_INTEGRATION.md) gives the full command and host boundary.

## Snapshot scope

The prepared library is a fixed acquisition snapshot completed September 21, 2026 against the DLA ASSIST dataset marked updated September 18, 2026. The complete 438-pack inventory is in the [root README](../../README.md#complete-prepared-library-snapshot).

The prepared set contains every selected publicly exposed current component for those packs. Twenty-five packs are explicitly partial because their current DLA composition also includes restricted components. Restricted bytes and restricted-only records are not included.

Snapshot currentness does not establish a project's approved baseline, and public availability does not establish blanket redistribution permission.

## Next steps

- Learn the seven evidence operations in the [query guide](QUERY_GUIDE.md).
- Connect a local model using [MCP](MODEL_INTEGRATION.md).
- Read the [architecture and trust boundaries](ARCHITECTURE_AND_TRUST.md).
