# Start here

StandardsForge is a standalone, source-first standards compiler and evidence engine. It runs locally; host applications and models consume its read-only evidence interface rather than becoming core dependencies.

## Current baseline

- Seven query operations are implemented in the library, CLI, and principal-bound stdio MCP adapter, including authorization-safe installed-document discovery.
- Official-source verification, deterministic PDF page compilation, restartable DLA corpus compilation, automated derived outlines, and reviewed structural annotations are separate administrative stages.
- Installed evidence is immutable and package-pinned. Authorization comes from trusted local policy, not imported rights claims.
- Search is discovery only. Retrieval reauthorizes, rechecks exact source hashes and spans, and reports coverage and unresolved context.
- `page_text`, `derived_structure`, `reviewed_structure`, and `curated_records` remain distinct representations.
- MCP initialization and tool descriptions provide the [MIL-STD model reading protocol](docs/MODEL_READING_GUIDE.md).

The prepared distribution contains 438 precompiled page-text packs covering 912 verified PDFs and 35,218 unclassified records. Its qualified MIL-STD-810H derived outline contains 7,788 exact-span records; it remains automated and unreviewed. First-run setup validates and indexes those included packs locally without source acquisition or PDF compilation. Current evidence and measurements are recorded in [VALIDATION_REPORT.md](VALIDATION_REPORT.md).

## Start working

Use the root [README](README.md) for prepared-release setup, querying, the maintainer rebuild workflow, command reference, and limitations. Before changing behavior, also read the [PRD](docs/PRD.md), [architecture](docs/ARCHITECTURE.md), relevant [decision index](docs/adr/README.md), and selected task in [backlog/tasks.json](backlog/tasks.json).

Run the required checks from the repository root:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python scripts/validate_contracts.py
python -m unittest discover -s tests -v
```

Local state uses `.standardsforge/`. An older `.standards-memory/` store is not moved or rewritten; select it explicitly with `--db .standards-memory/memory.db --store .standards-memory/objects` before a CLI subcommand, or pass the same paths to `standardsforge-mcp`.

## Boundaries

Page and derived-outline compilation do not establish document-wide visual fidelity, table-cell or figure interpretation, OCR completeness, reviewed semantic extraction, applicability, compliance, or approval. Restricted content remains outside the supported local public-source profile. Do not commit, publish, or redistribute locally acquired standards bytes without explicit authority.
