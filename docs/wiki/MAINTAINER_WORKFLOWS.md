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

## Build the prepared distribution

First build and retain the reproducible wheel:

```powershell
& $Python scripts/validate_installed_wheel.py `
  --build-tool-dir build/toolchain-cache `
  --output-dir build/prepared-wheel
```

Acquire the pinned MCP dependency closure into a dedicated wheelhouse. This is a maintainer build input; prepared setup never contacts a package index:

```powershell
& $Python -m pip download `
  --disable-pip-version-check `
  --only-binary=:all: `
  --dest build/prepared-mcp-wheelhouse `
  mcp==2.2.0
```

Then bind the completed corpus, acquisition snapshot, qualified outline, wheel, policy, and provenance:

```powershell
& $Python scripts/build_prepared_distribution.py `
  --corpus-index .standardsforge/corpus/mil-std-current/corpus.json `
  --acquisition-manifest .standardsforge/sources/dla/mil-std/manifest.json `
  --outline-pack .standardsforge/compiled/mil-std-810h-derived-outline `
  --wheel build/prepared-wheel/standardsforge-0.1.0a1-py3-none-any.whl `
  --wheel-provenance build/prepared-wheel/standardsforge-0.1.0a1-py3-none-any.whl.provenance.json `
  --mcp-wheelhouse build/prepared-mcp-wheelhouse `
  --output build/standardsforge-ready-0.1.0a1.zip `
  --version 0.1.0a1
```

The builder must reject incomplete scope, mismatched acquisition identity, changed archives, duplicate packages, unauthorized policy scope, unqualified outline claims, wheel/source drift, a malformed or unpinned MCP wheelhouse, and an unclosed final archive.

## Rights boundary

Do not add acquired PDFs or generated packs to Git. Distribution Statement A does not itself establish blanket republication rights. Do not bulk-download or redistribute licensed standards text without applicable processing and sharing rights. Keep source access, compilation permission, model-use permission, and redistribution permission separate.

See [validation and releases](VALIDATION_AND_RELEASES.md) before publishing anything.
