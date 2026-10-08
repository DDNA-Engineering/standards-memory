# Start here

StandardsForge is a standalone, source-first standards compiler and evidence engine. It runs locally; host applications and models consume its read-only evidence interface rather than becoming core dependencies.

## Current baseline

The published `0.1.0a7` release adds one-command model setup, generated host configuration and eleven query tools while retaining the a6 prepared content baseline. See [a7 release evidence](docs/RELEASE_0.1.0a7.md) for hashes and observed native/public acceptance. The earlier `0.1.0a6` release added source verification for unchanged edition-comparison records, non-mutating CLI/MCP query startup, complete physical-page coverage ledgers, and bounded real-document regression qualification. See [coverage and qualification](docs/COVERAGE_AND_REAL_QUALIFICATION.md). The prepared a6 distribution installs 441 packages: the unchanged acquisition baseline, outline-v3, and both reviewed 1661 recovery packs. Its setup replays 52 bounded real-document cases; this does not establish corpus-wide semantic completeness.

- The a7 interface has eleven read operations, including `browse_records`, `select_evidence`, `follow_references` and `get_source_pdfs`, explicit concept discovery and deduplicated pack transport; see [knowledge access](docs/KNOWLEDGE_ACCESS.md) and [reference and answer qualification](docs/REVIEW_AND_REFERENCE_QUALIFICATION.md).
- Official-source verification, deterministic PDF page compilation, restartable DLA corpus compilation, automated derived outlines, and reviewed structural or bounded semantic annotations are separate administrative stages.
- Installed evidence is immutable and package-pinned. Authorization comes from trusted local policy, not imported rights claims.
- Search is discovery only. Its compatibility default remains strict `all_terms`; the opt-in `natural_language` mode uses a separate local Porter index, fixed question stop words, and at most one disclosed strict-to-relaxed fallback. Ranking is row-local so records outside the caller's authorization cannot alter visible scores or order. Retrieval reauthorizes, rechecks exact source hashes and spans, and reports coverage and unresolved context.
- `page_text`, `derived_structure`, `reviewed_structure`, and `curated_records` remain distinct representations.
- MCP initialization and tool descriptions provide the [MIL-STD model reading protocol](docs/MODEL_READING_GUIDE.md).
- The repository [skill/plugin](docs/wiki/MODEL_INTEGRATION.md#select-standardsforge-in-your-chat) makes StandardsForge selectable in supported hosts and guides questions through an existing local MCP connection; it does not install or upgrade the runtime or corpus.
- The CLI `doctor` command diagnoses an existing store without creating or migrating it, reconciles a trusted policy and principal, validates package integrity at an explicit coverage level, and proves one exact source-verifying query through the read-only service path.
- A deterministic cross-platform synthetic starter bundles the verified core wheel, exact fictional packs and policy, portable setup and launcher, and content-bound receipt for a complete offline onboarding and integration path.
- The administrative `export-handoff` command writes one deterministic no-script source-first reader plus neutral candidate handoff from the existing authorized detailed retrieval path; it transfers no authority and cannot decide applicability, compliance, tailoring, baseline selection, or approval.
- Deterministic release sidecars bind the exact wheel and starter to CycloneDX 1.7 SBOMs, unsigned in-toto/SLSA-shaped statements, source and dependency locks, and a clean-commit-capable offline verifier. Authenticated GitHub attestations remain a separate protected-main CI result.
- Every production pypdf path runs in a disposable worker. POSIX resource limits or a Windows Job Object are installed before parsing; the parent accepts only a closed digest-bound page-file result, and parser failure makes the component and corpus incomplete rather than silently becoming an empty-text page.

The synthetic starter and prepared distribution are separate products. The starter proves fictional contract behavior and portable installation only. The earlier `v0.1.0a5` prepared distribution contains 438 precompiled page-text packs covering 912 verified PDFs and 35,218 unclassified records. Its qualified MIL-STD-810H `outline-v1` pack contains 7,788 exact-span records; it remains automated and unreviewed. That published artifact preserves the exact acquisition snapshot, its machine-readable scope qualification, and the reproducible wheel's source/build provenance. Portable core setup verifies the bundle, installs the bundled wheel with package indexes disabled, then validates and indexes the included packs locally without source acquisition or PDF compilation. The Windows x64 CPython 3.12 profile retains a fully offline MCP wheelhouse; POSIX MCP is a separate explicit PyPI code install against distribution-local state and does not carry or fetch corpus content. Later source changes on `main`, including `outline-v3` and reviewer workflows, have not been published in `v0.1.0a5`. Current evidence and measurements are recorded in [VALIDATION_REPORT.md](VALIDATION_REPORT.md).

## Start working

Use the root [README](README.md) for the prepared-release quickstart and complete dated library inventory. Use the version-controlled [wiki](docs/wiki/README.md) for query reference, model integration, maintainer rebuilds, architecture and trust boundaries, and release validation. Before changing behavior, also read the [PRD](docs/PRD.md), [architecture](docs/ARCHITECTURE.md), relevant [decision index](docs/adr/README.md), and selected task in [backlog/tasks.json](backlog/tasks.json).

Run the required checks from the repository root:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m pip install -e ".[mcp,compiler,contract,tokens]"
python -m pip check
python scripts/validate_contracts.py
python -m unittest discover -s tests -v
python scripts/run_benchmark.py benchmarks/synthetic-contract-v1.json
python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: --dest build/toolchain-cache setuptools==84.0.0
python scripts/validate_installed_wheel.py --build-tool-dir build/toolchain-cache --output-dir build/ci-wheel
python scripts/build_starter_distribution.py --wheel-dir build/ci-wheel --output build/standardsforge-starter.zip
python scripts/validate_starter_distribution.py build/standardsforge-starter.zip
```

The benchmark is an offline qualification of the harness and fictional synthetic contracts only. It preserves cold and immediate-warm raw responses, recomputes all content digests and metric denominators, and leaves real-document quality, tokenizer efficiency, resource limits, and engineer time explicitly unmeasured.

Local state uses `.standardsforge/`. An older `.standards-memory/` store is not moved or rewritten; select it explicitly with `--db .standards-memory/memory.db --store .standards-memory/objects` before a CLI subcommand, or pass the same paths to `standardsforge-mcp`.

After installation, run `standardsforge doctor --policy <trusted-policy.json> --principal <principal> --full-integrity`. A completed report exits `0` only when ready and `3` when not ready; the command never repairs, migrates, fetches, installs, revokes, or invokes a model.

## Boundaries

Page and derived-outline compilation do not establish document-wide visual fidelity, table-cell or figure interpretation, OCR completeness, reviewed semantic extraction, applicability, compliance, or approval. The fixed parser limits passed the local 1,107-page MIL-STD-810H acceptance source on Windows. The protected cross-platform CI matrix passed for source commit `5cc82cd`, but that does not qualify real-document visual or semantic quality, nor does it establish a broader all-corpus peak-resource claim. Restricted content remains outside the supported local public-source profile. Do not commit, publish, or redistribute locally acquired standards bytes without explicit authority.

Latest local follow-up: [MIL-STD-1661 scan recovery](docs/SCAN_RECOVERY_2026-10-08.md) recovers all 18 pages and qualifies a separate reviewed semantic package. The unified a6 prepared release includes those recovery packs and complete semantic assertions, five separate 4.2.4 directives, and reviewed blank-page support. The standalone v2 supplement is retained as historical local validation.
