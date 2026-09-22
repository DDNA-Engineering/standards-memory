# Prepared offline library

The prepared StandardsForge release is the normal end-user path. It already contains the dependency-free StandardsForge wheel, compressed public MIL-STD packs, exact local policies, setup and launcher scripts, and recorded provenance. Users do not reacquire PDFs or compile the corpus.

Return to the [three-minute root quickstart](../../README.md#start-the-offline-library) when you only need the commands.

## Requirements

- Windows PowerShell.
- Python 3.11 or newer.
- A Python build whose SQLite includes FTS5.
- Enough local space for the approximately 1 GB archive plus its extracted packs, virtual environment, object store, and index.

A Git clone is not required.

## Install

1. Download [standardsforge-ready-0.1.0a1.zip](https://github.com/DDNA-Engineering/standards-memory/releases/download/v0.1.0a1/standardsforge-ready-0.1.0a1.zip).
2. Optionally compare it with the [published SHA-256 file](https://github.com/DDNA-Engineering/standards-memory/releases/download/v0.1.0a1/standardsforge-ready-0.1.0a1.zip.sha256).
3. Extract the ZIP to a durable local directory.
4. Open PowerShell in the extracted directory.
5. Run:

```powershell
.\setup.ps1
```

Setup validates the closed bundle inventory before writes, creates an isolated environment, installs only the bundled wheel, validates and installs the included packs, builds the local index, runs evidence smokes, and records a receipt. It does not acquire standards, compile PDFs, call a model, or need a Git checkout.

Rerunning setup revalidates the bundle and installed state rather than trusting a marker.

## Prove readiness

```powershell
.\standardsforge.ps1 doctor `
  --policy policies\mil-std-corpus-local.json `
  --principal local-user `
  --full-integrity
```

A completed ready report exits `0`. A completed `not_ready` report exits `3`; typed command errors exit `2`, and unexpected internal failures exit `1`. `doctor` opens the existing store read-only. It does not repair, migrate, fetch, install, revoke, or invoke a model.

## Search

```powershell
.\standardsforge.ps1 search "environmental testing" `
  --principal local-user `
  --limit 5
```

Search returns candidate records with package identity, citations, coverage, and interpretation limits. Search is discovery, not a determination that a standard applies.

## Pin a representation

When multiple representations exist for one edition, resolve the exact representation and reuse its package digest:

```powershell
$resolved = .\standardsforge.ps1 resolve 'MIL-STD-810H(1)' `
  --representation derived_structure `
  --principal local-user | ConvertFrom-Json

$pin = $resolved.result.package_digest

.\standardsforge.ps1 search "low pressure" `
  --package-digest $pin `
  --principal local-user `
  --limit 5
```

The digest pins the installed package bytes. It does not select a project baseline or approve applicability.

## Local state

Runtime state stays inside the extracted distribution. Keep the extracted directory together if you move or back it up. The source repository's ignored `.standardsforge/` directory is separate machine-local development state and is not the end-user distribution.

## Snapshot scope

The prepared library is a fixed acquisition snapshot completed September 21, 2026 against the DLA ASSIST dataset marked updated September 18, 2026. The complete 438-pack inventory is in the [root README](../../README.md#complete-prepared-library-snapshot).

The prepared set contains every selected publicly exposed current component for those packs. Twenty-five packs are explicitly partial because their current DLA composition also includes restricted components. Restricted bytes and restricted-only records are not included.

Snapshot currentness does not establish a project's approved baseline, and public availability does not establish blanket redistribution permission.

## Next steps

- Learn the six evidence operations in the [query guide](QUERY_GUIDE.md).
- Connect a local model using [MCP](MODEL_INTEGRATION.md).
- Read the [architecture and trust boundaries](ARCHITECTURE_AND_TRUST.md).
