# Maintainer workflows

These workflows rebuild or refresh artifacts. They are not required to use the prepared offline library.

Run them from the repository root in an isolated environment. Source acquisition and generated corpus state live under ignored `.standardsforge/` paths.

## Prepare the environment

```powershell
py -3 -m venv .venv
$Python = Join-Path $PWD '.venv\Scripts\python.exe'
& $Python -m pip install --upgrade pip
& $Python -m pip install -e '.[compiler,mcp,contract]'
```

## Acquire the active public MIL-STD inventory

```powershell
& $Python -m standardsforge acquire-mil-std
& $Python -m standardsforge verify-mil-std-acquisition `
  .standardsforge/sources/dla/mil-std/manifest.json
```

The administrative downloader targets official DLA ASSIST current records and records restricted components as inventory metadata without requesting their bytes. Every downloaded PDF is signature-checked, hashed, atomically activated, and closed against the manifest. Query operations never acquire sources.

Use `--inventory-only` to enumerate without downloading. Use `--reuse-inventory` only with a completed inventory snapshot and verified restored files.

## Verify tracked seed catalogs

```powershell
& $Python -m standardsforge verify-source-set catalog/mil-format-authorities.json `
  --source-root .standardsforge/sources/dla/format-authorities

& $Python -m standardsforge verify-source-set catalog/mil-std-810h.json `
  --source-root .standardsforge/sources/dla/mil-std-810h
```

Verification is offline and closed-set. Unexpected files, non-PDF bytes, path violations, size differences, and digest differences fail validation.

## Compile and install the corpus

```powershell
& $Python -m standardsforge compile-mil-std-corpus `
  .standardsforge/sources/dla/mil-std/manifest.json `
  .standardsforge/corpus/mil-std-current `
  --source-root .standardsforge/sources/dla/mil-std

& $Python -m standardsforge write-corpus-policy `
  .standardsforge/corpus/mil-std-current/corpus.json `
  .standardsforge/policies/mil-std-corpus-local.json `
  --principal local-user

& $Python -m standardsforge install-corpus `
  .standardsforge/corpus/mil-std-current/corpus.json `
  --policy .standardsforge/policies/mil-std-corpus-local.json
```

One pack represents one ordered DLA current-component set. Mixed public/restricted compositions remain explicitly partial; restricted-only records produce no pack. Parser failure keeps the component and corpus incomplete.

## Build an automated outline

```powershell
& $Python -m standardsforge compile-derived-outline `
  <page-pack-or-archive> `
  <output-directory>
```

Derived outlines preserve exact spans and unsupported regions. They are automated navigation candidates, not reviewed semantic interpretation, applicability, or compliance.

## Review one outline candidate against its exact page pack

Select the derived outline, its exact base page-text pack (the digest is inventoried in the outline's `derivations/base-pack.json`), and one candidate `record_id`. The exporter verifies both complete packs, source component and sidecar identities, quote hashes, and UTF-8 boundaries before rebasing the outline's global sidecar span to the same page's local layout-text coordinates. It does not re-extract in simple mode or claim review.

```powershell
& $Python -m standardsforge export-outline-draft `
  <derived-outline-pack> <exact-base-page-pack> <candidate-record-id> `
  .standardsforge/annotations/selected-draft.json
```

The emitted file is a `proposed_unreviewed` draft, not a compileable reviewed annotation. Inspect the cited source and correct the node's heading, kind, exact text, spans, and role as needed. Write a separate JSON decision with exactly `schema_version: "0.1.0"`, the emitted `draft_sha256`, a complete `review` object, and one `node` copied and deliberately reviewed from `proposed_node`. Replace its `derivation.review_status: "proposed"` with the truthful `agent_reviewed`, `human_reviewed`, or `human_reviewed_with_uncertainty` state. The review object must name the reviewer, reviewer type, timestamp, method, tool provenance (required for agents), unresolved issues, and `attestation: "extraction_review_not_project_applicability_or_approval"`. A source candidate's parent is recorded separately in the draft because this single-node slice does not assert an out-of-scope reviewed hierarchy; do not invent relationships, obligation classification, applicability, or approval.

```powershell
& $Python -m standardsforge promote-outline-review `
  .standardsforge/annotations/selected-draft.json `
  .standardsforge/annotations/selected-decision.json `
  <derived-outline-pack> <exact-base-page-pack> `
  .standardsforge/annotations/selected-reviewed.json

& $Python -m standardsforge compile-structure-from-pack `
  <exact-base-page-pack> <derived-outline-pack> `
  .standardsforge/annotations/selected-reviewed.json `
  .standardsforge/compiled/selected-reviewed
```

Promotion and compilation reverify the exact outline proposal, base package, page text, reviewer status, and edited source spans. The resulting pack is a reviewed representation of only that selected node. It is not a document-wide reviewed outline. The output includes the complete source PDF for offline evidence, preserves its input rights claims, and does not grant processing or redistribution permission; do not publish or share it without independently confirmed rights. The prior catalog-based `compile-structure` remains available for its separately pinned simple-extraction annotations; its catalog identity is not silently substituted for the corpus component.

## Build the prepared distribution

First build and retain the reproducible wheel:

```powershell
& $Python scripts/validate_installed_wheel.py `
  --build-tool-dir build/toolchain-cache `
  --output-dir build/prepared-wheel
```

Acquire the pinned Windows MCP dependency closure into a dedicated wheelhouse. This is a maintainer build input; portable core setup and the Windows offline MCP setup never contact a package index:

```powershell
& $Python -m pip download `
  --disable-pip-version-check `
  --only-binary=:all: `
  --require-hashes `
  --no-deps `
  --dest build/prepared-mcp-wheelhouse `
  -r scripts/prepared_distribution/mcp-wheelhouse-win-amd64-cp312.txt
```

Then bind the completed corpus, acquisition snapshot, qualified outline, wheel, policy, and provenance:

```powershell
$PreparedVersion = '0.1.0a5'
& $Python scripts/build_prepared_distribution.py `
  --corpus-index .standardsforge/corpus/mil-std-current/corpus.json `
  --acquisition-manifest .standardsforge/sources/dla/mil-std/manifest.json `
  --outline-pack .standardsforge/compiled/mil-std-810h-derived-outline `
  --wheel "build/prepared-wheel/standardsforge-$PreparedVersion-py3-none-any.whl" `
  --wheel-provenance "build/prepared-wheel/standardsforge-$PreparedVersion-py3-none-any.whl.provenance.json" `
  --mcp-wheelhouse build/prepared-mcp-wheelhouse `
  --mcp-requirements scripts/prepared_distribution/mcp-wheelhouse-win-amd64-cp312.txt `
  --output "build/standardsforge-ready-$PreparedVersion.zip" `
  --version $PreparedVersion
```

The builder must reject incomplete scope, mismatched acquisition identity, changed archives, duplicate packages, unauthorized policy scope, unqualified outline claims, wheel/source drift, a malformed or unpinned MCP wheelhouse, and an unclosed final archive. The wheelhouse is the fully offline Windows x64 CPython 3.12 MCP profile. The portable prepared core uses the bundled dependency-free wheel on each declared platform; POSIX MCP is installed later through the separate PyPI code channel and is not part of corpus acquisition or compilation.

## Rights boundary

Do not add acquired PDFs or generated packs to Git. Distribution Statement A does not itself establish blanket republication rights. Do not bulk-download or redistribute licensed standards text without applicable processing and sharing rights. Keep source access, compilation permission, model-use permission, and redistribution permission separate.

See [validation and releases](VALIDATION_AND_RELEASES.md) before publishing anything.
