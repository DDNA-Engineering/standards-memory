# Start here

StandardsForge is a standalone, source-first standards compiler and evidence engine. It runs locally; host applications and models consume its read-only evidence interface rather than becoming core dependencies.

## Current baseline

- Seven query operations are implemented in the library, CLI, and principal-bound stdio MCP adapter, including authorization-safe installed-document discovery.
- Official-source verification, deterministic PDF page compilation, restartable DLA corpus compilation, automated derived outlines, and reviewed structural or bounded semantic annotations are separate administrative stages.
- Installed evidence is immutable and package-pinned. Authorization comes from trusted local policy, not imported rights claims.
- Search is discovery only. Its compatibility default remains strict `all_terms`; the opt-in `natural_language` mode uses a separate local Porter index, fixed question stop words, and at most one disclosed strict-to-relaxed fallback. Ranking is row-local so records outside the caller's authorization cannot alter visible scores or order. Retrieval reauthorizes, rechecks exact source hashes and spans, and reports coverage and unresolved context.
- `page_text`, `derived_structure`, `reviewed_structure`, and `curated_records` remain distinct representations.
- MCP initialization and tool descriptions provide the [MIL-STD model reading protocol](docs/MODEL_READING_GUIDE.md).
- The CLI `doctor` command diagnoses an existing store without creating or migrating it, reconciles a trusted policy and principal, validates package integrity at an explicit coverage level, and proves one exact source-verifying query through the read-only service path.
- A deterministic cross-platform synthetic starter bundles the verified core wheel, exact fictional packs and policy, portable setup and launcher, and content-bound receipt for a complete offline onboarding and integration path.
- The administrative `export-handoff` command writes one deterministic no-script source-first reader plus neutral candidate handoff from the existing authorized detailed retrieval path; it transfers no authority and cannot decide applicability, compliance, tailoring, baseline selection, or approval.
- Deterministic release sidecars bind the exact wheel and starter to CycloneDX 1.7 SBOMs, unsigned in-toto/SLSA-shaped statements, source and dependency locks, and a clean-commit-capable offline verifier. Authenticated GitHub attestations remain a separate protected-main CI result.
- Every production pypdf path runs in a disposable worker. POSIX resource limits or a Windows Job Object are installed before parsing; the parent accepts only a closed digest-bound page-file result, and parser failure makes the component and corpus incomplete rather than silently becoming an empty-text page.

The synthetic starter and prepared distribution are separate products. The starter proves fictional contract behavior and portable installation only. The prepared distribution contains 438 precompiled page-text packs covering 912 verified PDFs and 35,218 unclassified records. Its qualified MIL-STD-810H derived outline contains 7,788 exact-span records; it remains automated and unreviewed. The next rebuilt prepared artifact also preserves the exact acquisition snapshot, its machine-readable scope qualification, and the reproducible wheel's source/build provenance. Portable core setup verifies the bundle, installs the bundled wheel with package indexes disabled, then validates and indexes the included packs locally without source acquisition or PDF compilation. The Windows x64 CPython 3.12 profile retains a fully offline MCP wheelhouse; POSIX MCP is a separate explicit PyPI code install against distribution-local state and does not carry or fetch corpus content. Current evidence and measurements are recorded in [VALIDATION_REPORT.md](VALIDATION_REPORT.md).

## Start working

Use the root [README](README.md) for the prepared-release quickstart and complete dated library inventory. Use the version-controlled [wiki](docs/wiki/README.md) for query reference, model integration, maintainer rebuilds, architecture and trust boundaries, and release validation. Before changing behavior, also read the [PRD](docs/PRD.md), [architecture](docs/ARCHITECTURE.md), relevant [decision index](docs/adr/README.md), and selected task in [backlog/tasks.json](backlog/tasks.json).

Run the required checks from the repository root:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m pip install -e ".[mcp,compiler,contract]"
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

Page and derived-outline compilation do not establish document-wide visual fidelity, table-cell or figure interpretation, OCR completeness, reviewed semantic extraction, applicability, compliance, or approval. The fixed parser limits are enforced by cross-platform CI tests and passed the local 1,107-page MIL-STD-810H acceptance source on Windows; the protected Linux matrix has not been observed for these uncommitted changes, and no broader all-corpus peak-resource claim is made. Restricted content remains outside the supported local public-source profile. Do not commit, publish, or redistribute locally acquired standards bytes without explicit authority.
