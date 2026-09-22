<div align="center">

<img src="assets/brand/standardsforge-mark.png" alt="StandardsForge SF monogram in navy and orange" width="144" height="144">

# StandardsForge

**Turn MIL-STD evidence into stronger products, requirements, and test plans.**

StandardsForge helps teams building physical products gather the military standards that may shape their design, retrieve the exact source evidence, and use it to develop requirements, test plans, and a standards-aware product roadmap.<br>
It is an offline-first compiler and evidence engine: every result stays tied to the source, edition, governing conditions, and known evidence limits.

[![Version: 0.1.0a1](https://img.shields.io/badge/version-0.1.0a1-253247?style=flat-square)](pyproject.toml)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)](pyproject.toml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-253247?style=flat-square)](LICENSE)
[![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-EA6A23?style=flat-square)](docs/PRD.md)

[![Queries: offline](https://img.shields.io/badge/queries-offline-253247?style=flat-square)](docs/ARCHITECTURE.md)
[![MCP: local stdio](https://img.shields.io/badge/MCP-local_stdio-253247?style=flat-square)](#connect-a-local-mcp-host)
[![Storage: SQLite FTS5](https://img.shields.io/badge/storage-SQLite_FTS5-253247?style=flat-square)](docs/ARCHITECTURE.md)
[![Core dependencies: zero](https://img.shields.io/badge/core_dependencies-zero-253247?style=flat-square)](pyproject.toml)

**Topics:** [defense-engineering](https://github.com/topics/defense-engineering) · [military-standards](https://github.com/topics/military-standards) · [mil-std](https://github.com/topics/mil-std) · [systems-engineering](https://github.com/topics/systems-engineering) · [requirements-engineering](https://github.com/topics/requirements-engineering) · [mcp](https://github.com/topics/mcp) · [offline-first](https://github.com/topics/offline-first)

[Quickstart](#run-the-portable-synthetic-starter) · [Prepared corpus](#query-the-prebuilt-corpus) · [Commands](#six-ways-to-read) · [Architecture](#under-the-hood) · [Roadmap](#where-this-is-going) · [Contributing](CONTRIBUTING.md)

</div>

---

## From physical product to defensible plan

Physical products are shaped by more than a list of standard numbers. Teams need to know which editions they are evaluating, what the source actually says, which conditions and exceptions travel with a requirement, and where that evidence affects the design and verification strategy.

StandardsForge provides the evidence backbone for that work:

- **Gather authorized MIL-STD sources locally.** Preserve the publisher identity, exact edition, notices, component files, and source hashes instead of building from an untraceable document folder.
- **Discover standards evidence relevant to the product.** Search an authorized local corpus, resolve the intended edition and representation, and pin the exact package used for the engineering baseline.
- **Build traceable requirements and test plans.** Retrieve exact clauses with their governing notes, conditions, exceptions, citations, and declared dependencies so engineers can turn evidence into design inputs and verification work.
- **Harden the product roadmap.** Use source-linked evidence to expose missing decisions, qualification work, test assets, design changes, and review gates before they become late-program surprises.

For example, a technical standard may require a connector to withstand **80 N for 60 seconds**, while a governing note requires **two hours at 23 °C ± 2 °C** first. Retrieving only the clause produces an incomplete test basis. StandardsForge follows the pack's declared dependencies and returns both with exact source text, locations, and hashes.

The engine supplies evidence, not engineering approval. It does not decide whether a standard applies to a specific product, approve a requirement or test plan, or certify compliance. Those decisions stay with the responsible engineering and program authorities; StandardsForge makes their source basis explicit and reviewable.

## Run the portable synthetic starter

The smallest complete product path is a deterministic ZIP containing the dependency-free core wheel, two fictional contract packs, their exact trusted policy, and portable setup and launcher scripts. It is suitable for learning, CI, and integration work without downloading standards or relying on a source checkout at runtime.

Build and exercise it from a checkout on Windows or POSIX with Python 3.11 or newer:

```text
python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: --dest build/toolchain-cache setuptools==84.0.0
python scripts/validate_installed_wheel.py --build-tool-dir build/toolchain-cache --output-dir build/starter-wheel
python scripts/build_starter_distribution.py --wheel-dir build/starter-wheel --output build/standardsforge-starter.zip
python scripts/validate_starter_distribution.py build/standardsforge-starter.zip
python -m zipfile -e build/standardsforge-starter.zip build/starter-extracted
python -I build/starter-extracted/standardsforge-starter-0.1.0a1/setup.py
python -I build/starter-extracted/standardsforge-starter-0.1.0a1/run.py search "axial load" --query-mode exact_phrase --principal local-user
```

Setup validates every immutable bundle byte before writing, installs only the included wheel with package indexes and dependency resolution disabled, validates and installs the exact packs, runs full readiness and evidence smokes, then writes a content-bound receipt. A rerun revalidates the bundle, receipt, installed packages, policy, doctor result, and evidence path. The starter proves fictional contract behavior only; it is not evidence of real-document discovery quality, semantic fidelity, applicability, compliance, approval, or a substitute for the prepared public corpus.

## Query the prebuilt corpus

The prepared StandardsForge release is already compiled for use. It contains the recorded active MIL-STD baseline's selected current Distribution Statement A components in verified compressed packs, plus an automated, unreviewed MIL-STD-810H derived outline. It does not include other DLA document classes, historical editions, restricted bytes, or document-wide reviewed semantic interpretation. The bundled machine-readable source baseline records the acquisition snapshot, selection rules, exclusions, failures, extraction gaps, and review coverage. You do **not** need to download hundreds of PDFs or compile standards before searching the included baseline.

The current prepared baseline contains:

- **438** compiled MIL-STD page-text packs from **912** verified source PDFs.
- **35,218** source-linked page records across **35,235** physical pages.
- About **1.0 GB** of deterministic compressed packs.
- A one-command local setup that validates and indexes the included packs for offline queries.

Download and extract [standardsforge-ready-0.1.0a1.zip](https://github.com/DDNA-Engineering/standards-memory/releases/download/v0.1.0a1/standardsforge-ready-0.1.0a1.zip), and optionally verify its [published SHA-256 checksum](https://github.com/DDNA-Engineering/standards-memory/releases/download/v0.1.0a1/standardsforge-ready-0.1.0a1.zip.sha256). You need **Python 3.11+** with SQLite FTS5 support. Open **PowerShell** in the extracted directory and run:

```powershell
# Create the isolated local environment and index the included compiled packs.
.\setup.ps1

# Confirm the installed state, policy, every package, and exact evidence query path.
.\standardsforge.ps1 doctor --policy policies\mil-std-corpus-local.json `
  --principal local-user `
  --full-integrity

# Search the installed MIL-STD corpus.
.\standardsforge.ps1 search "environmental testing" --principal local-user --limit 5

# Resolve the prepared MIL-STD-810H representation and capture its immutable package pin.
$resolved = .\standardsforge.ps1 resolve 'MIL-STD-810H(1)' --representation derived_structure --principal local-user | ConvertFrom-Json
$pin = $resolved.result.package_digest

# Search only that pinned edition and representation.
.\standardsforge.ps1 search "low pressure" --package-digest $pin --principal local-user --limit 5
```

The one-time setup installs only the bundled wheel and precompiled packs; it does not fetch standards or call a model. `doctor` opens that state read-only, validates every installed package in this example, reconciles the selected policy scope, and executes one exact source-verifying query through the real read path. It exits `0` only when ready and `3` after a completed `not_ready` report; typed command failures remain exit `2` and unexpected internal failures remain exit `1`. Commands return source-linked JSON with package identity, exact citations, coverage, and interpretation limits. Local state stays inside the extracted distribution.

The source repository also supports an optional MCP adapter for local model hosts:

```powershell
python -m pip install -e ".[mcp]"
standardsforge-mcp --db .standardsforge/memory.db --store .standardsforge/objects --principal local-user
```

The host owns the MCP process, so the final command intentionally stays running when launched directly.

> **Distribution boundary:** `.standardsforge/` remains excluded from the source-only Git repository because it is machine-local runtime state. The prepared release asset carries the verified precompiled public corpus separately. A plain Git clone contains the compiler and example packs; end users should use the prepared release. The rebuild workflow below is for maintainers creating or refreshing that release.

<details>
<summary><strong>Try the small fictional example instead</strong></summary>

```powershell
python -m standardsforge verify-pack examples/packs/fictional-adapter-v1
python -m standardsforge install examples/packs/fictional-adapter-v1 --policy examples/policies/local-synthetic.json
python -m standardsforge doctor --policy examples/policies/local-synthetic.json --principal local-user --full-integrity
$example = python -m standardsforge resolve EXAMPLE-SPEC-100 --edition example:spec-100:2025-a --representation curated_records --principal local-user | ConvertFrom-Json
python -m standardsforge get-clause $example.result.package_digest 4.2.1 --principal local-user
```

This returns the connector-retention clause with its governing conditioning note and is useful for development without the prepared corpus.

</details>

## Rebuild or refresh the official-source corpus

This is a maintainer workflow, not a prerequisite for using a prepared StandardsForge distribution. Run it only when creating the corpus from authoritative publisher files or refreshing it against a newly approved source baseline.

Source acquisition writes to ignored local state. The repository tracks provenance and integrity metadata rather than committing third-party PDFs.

The first compiler seed catalog contains the current DLA ASSIST editions of MIL-STD-961, MIL-STD-962, and MIL-STD-967—the format authorities for specifications, standards, and handbooks. A separate catalog pins MIL-STD-810 Revision H Change 1 for environmental-engineering compilation and qualification. Catalog inclusion is not a declaration that a standard applies to a particular product.

Use [DLA ASSIST Quick Search](https://quicksearch.dla.mil/) as the authoritative source. To acquire every current publicly exposed component of every active `MIL-STD-` record, run the resumable administrative downloader and then close the local files against its manifest:

```powershell
python -m standardsforge acquire-mil-std
python -m standardsforge verify-mil-std-acquisition `
  .standardsforge/sources/dla/mil-std/manifest.json
```

The acquisition scope is explicit: active records only; leading notices plus the first substantive current revision or incorporated change; Distribution Statement A files only. Restricted components remain inventory metadata and are not requested. Each completed PDF is signature-checked, hashed during transfer, atomically installed, and checkpointed for restart. Use `--inventory-only` to enumerate without downloading and `--reuse-inventory` to resume from a completed inventory snapshot.

For the smaller tracked seed catalogs, place each file at the exact name declared by its catalog and verify the sets locally:

```powershell
python -m standardsforge verify-source-set catalog/mil-format-authorities.json `
  --source-root .standardsforge/sources/dla/format-authorities

python -m standardsforge verify-source-set catalog/mil-std-810h.json `
  --source-root .standardsforge/sources/dla/mil-std-810h
```

Verification is offline and closed-set: every declared file must be present, no unexpected directory entries are accepted, and the PDF signature, byte length, and SHA-256 digest must match. Page counts are recorded publisher/source metadata and are not recomputed by this command.

EverySpec is useful for discovery, but its [published terms](https://everyspec.com/terms_of_use.php) prohibit automated downloading and processing. StandardsForge therefore does not scrape it. Bulk acquisition is an explicit administrative action against the official DLA publisher source, separate from every read operation; query tools never fetch URLs.

## Compile verified source material

Install the separately pinned compiler dependency, then compile a catalog-pinned source into an installable local pack:

```powershell
python -m pip install -e ".[compiler]"
python -m standardsforge compile-pdf catalog/mil-std-810h.json MIL-STD-810 `
  .standardsforge/compiled/mil-std-810h `
  --source-root .standardsforge/sources/dla/mil-std-810h
```

Create a deterministic compressed transport without changing the package digest:

```powershell
python -m standardsforge archive-pack .standardsforge/compiled/mil-std-810h .standardsforge/compiled/mil-std-810h.zip
```

To compile every verified downloaded DLA current component, keep notices and revisions together by DLA record, create an explicit exact-pack local policy, and install the completed corpus:

```powershell
python -m standardsforge compile-mil-std-corpus `
  .standardsforge/sources/dla/mil-std/manifest.json `
  .standardsforge/corpus/mil-std-current `
  --source-root .standardsforge/sources/dla/mil-std
python -m standardsforge write-corpus-policy `
  .standardsforge/corpus/mil-std-current/corpus.json `
  .standardsforge/policies/mil-std-corpus-local.json `
  --principal local-user
python -m standardsforge install-corpus `
  .standardsforge/corpus/mil-std-current/corpus.json `
  --policy .standardsforge/policies/mil-std-corpus-local.json
```

Corpus compilation is restartable and matches the complete ordered composition plus compiler provenance before reusing an archive. One pack represents one ordered DLA current-component set; only Distribution Statement A components may be compiled, records with both public and restricted components remain explicitly partial, and restricted-only records produce no evidence pack. The corpus compiler accepts only empty-password public encryption, namespaces every page by DLA component, and reports pages with malformed or absent text layers instead of inventing OCR or silently calling the edition fully parsed. Reinstallation revokes obsolete active grants for prior generated versions of the same corpus pack identities.

The compiler preserves the original PDF, creates a separately hashed text sidecar, emits a page record for each extractable physical page, and writes a page-level extraction report. It does not silently run OCR, infer clause boundaries, interpret tables or figures, or classify obligations. Every page record remains `unclassified` and `unreviewed` until later compiler stages add evidence-backed structure and review.

`compile-structure` accepts a separate, edition-bound reviewed-annotation document. It emits stable logical node identities and typed relationships whose node and relationship claims are bound to one or more ordered exact physical-page UTF-8 spans. Version 0.2 annotations may also carry reviewed, exact-span semantic fields for subject, action, modality, conditions, exceptions, raw quantities, definitions, governing notes, and table context. Each such record exposes its content-bound review event, leaves project applicability undecided, and retrieves declared required context transitively. The real shipped acceptance slice covers MIL-STD-810H Method 500.6 section 2.2.2 as reviewed structure only; the reviewed semantic packet is synthetic acceptance evidence, not document-wide or shipped-corpus semantic coverage.

To create navigable, explicitly unreviewed structure from any verified page-text pack or archive, run:

```powershell
python -m standardsforge compile-derived-outline <page-pack-or-archive> <output-directory>
```

The resulting `derived_structure` pack recognizes bounded headings, list items, notes, and table/figure captions while retaining exact source spans. Numeric table rows, repeated table footnotes, repeated method headers, unmatched prefixes, and unparsed pages are retained as unsupported regions. These records are candidates only: they remain `unclassified` and `automated_unreviewed`, produce no confirmed obligations, and make no table-cell, figure-visual, OCR, applicability, or compliance claim.

## Rebuild a model-ready MIL-STD-810H representation

The prepared workspace already contains this representation. Maintainers can use the following reproducible workflow to rebuild it from the completed corpus index, explicitly authorize exactly that output, install it, resolve its immutable pin, search it, and retrieve exact evidence. Run it from the repository root. The output and policy paths must not already exist.

```powershell
# Create an isolated environment and install the CLI, compiler, and MCP adapter.
py -3 -m venv .venv
$Python = Join-Path $PWD '.venv\Scripts\python.exe'
& $Python -m pip install --upgrade pip
& $Python -m pip install -e '.[compiler,mcp]'

# Select MIL-STD-810H from the already compiled downloaded corpus.
$CorpusIndex = Join-Path $PWD '.standardsforge\corpus\mil-std-current\corpus.json'
$Corpus = Get-Content -LiteralPath $CorpusIndex -Raw | ConvertFrom-Json
$Entry = $Corpus.entries | Where-Object { $_.document_id -eq 'MIL-STD-810H(1)' }
if (@($Entry).Count -ne 1) { throw 'Expected exactly one MIL-STD-810H(1) corpus entry.' }
$PagePack = Join-Path (Split-Path -Parent $CorpusIndex) $Entry.archive_path

# Compile a separate automated, unreviewed navigation representation.
$OutlinePack = Join-Path $PWD '.standardsforge\compiled\mil-std-810h-derived-outline'
& $Python -m standardsforge verify-pack $PagePack
& $Python -m standardsforge compile-derived-outline $PagePack $OutlinePack

# Explicitly authorize this exact validated pack and expected content class.
$Policy = Join-Path $PWD '.standardsforge\policies\mil-std-810h-derived-outline-local.json'
& $Python -m standardsforge write-pack-policy $OutlinePack $Policy `
  --principal local-user `
  --content-class public_government_standard
& $Python -m standardsforge install $OutlinePack --policy $Policy

# Resolve one representation, discover a candidate, then retrieve exact evidence.
$Resolved = & $Python -m standardsforge resolve 'MIL-STD-810H(1)' `
  --representation derived_structure `
  --principal local-user | ConvertFrom-Json
$Pin = $Resolved.result.package_digest
$Search = & $Python -m standardsforge search 'low pressure' `
  --package-digest $Pin `
  --principal local-user `
  --limit 3 | ConvertFrom-Json
$Hit = $Search.result.results | Select-Object -First 1
if ($null -eq $Hit) { throw 'Search returned no evidence candidate.' }
$ClauseReference = $Hit.clause_reference
$RecordId = $Hit.record_id
& $Python -m standardsforge get-clause $Pin $ClauseReference `
  --record-id $RecordId `
  --principal local-user `
  --response-profile concise_evidence_v1

# Start the read-only model tool server; this process intentionally stays running.
$Mcp = Join-Path $PWD '.venv\Scripts\standardsforge-mcp.exe'
& $Mcp --db .standardsforge/memory.db `
  --store .standardsforge/objects `
  --principal local-user `
  --result-mode structured_only
```

`write-pack-policy` does not silently trust a rights claim. The operator must name the expected content class, the validated pack must match it, and the resulting policy authorizes only that pack ID for the named principal.

## Six ways to read

| Command | The job |
| --- | --- |
| `search` | Discover relevant records through authorized lexical search, source-linked snippets, and available heading ancestry. |
| `resolve` | Turn an exact document identifier, edition, and optional representation into a package pin. |
| `get-clause` | Retrieve a uniquely referenced clause, note, or compiled page and its required dependency context. |
| `build-context` | Assemble multiple clauses without duplicating shared evidence. |
| `enumerate-obligations` | Traverse every explicitly classified obligation in a selected scope, with pagination. |
| `diff-editions` | Compare records by exact identity, report review-required alignment candidates separately, and surface side-qualified transitive required-dependency impacts. |

Pack validation (`verify-pack`) and administration (`install`, `revoke`) are separate from those six read operations. Source-set verification is also administrative; it does not install, parse, or authorize a document.

`export-handoff` is also administrative: it writes a portable source-first reader and neutral engineering-handoff artifact without expanding the six query operations or MCP surface. The caller supplies a closed candidate draft; StandardsForge retrieves the exact package-pinned record and required context, keeps the candidate separate from source evidence, and fixes applicability, compliance, tailoring, baseline selection, and approval as host-owned undecided states.

Lexical search has three explicit modes. `all_terms` is the compatibility default and requires every parsed lexical chunk; `exact_phrase` requires the chunks in adjacent order; `any_terms` accepts at least one compiled chunk. Search punctuation and familiar operators never select a mode implicitly—quotes, `OR`, wildcards, and parentheses are parsed as ordinary input rather than raw FTS syntax. Every response returns the selected mode, normalized query, and parsed chunks.

```powershell
standardsforge search 'steady axial load' --principal local-user --query-mode exact_phrase
standardsforge search 'axial ingress' --principal local-user --query-mode any_terms
```

Dots, slashes, and hyphens stay inside one reported lexical chunk so identifiers remain visible as entered; SQLite may internally tokenize such a chunk for matching. Search is still ranked candidate discovery, not exhaustive evidence retrieval or applicability.

## Connect a local MCP host

The core remains dependency-free. Install the separately pinned MCP adapter dependency when you need the local server:

```powershell
python -m pip install -e ".[mcp]"
```

Configure the MCP host to launch this stdio process against the database and object store populated by the administrative CLI:

```powershell
standardsforge-mcp --db .standardsforge/memory.db --store .standardsforge/objects --principal local-user
```

The host owns the process and talks over stdin/stdout, so the command intentionally blocks when run directly. It exposes exactly `search`, `resolve_document`, `get_clause`, `build_context`, `enumerate_obligations`, and `diff_editions`. It has no install, pack-verification, revocation, HTTP, or caller-selected-principal surface. The trusted startup principal is bound to every call, core authorization is rechecked, and the SDK telemetry middleware is removed before serving.

Successful calls carry the CLI's `{ok,result}` envelope as structured content. Anticipated domain failures are MCP error results whose text is a typed `{ok:false,error}` JSON envelope.

During MCP initialization the server gives the host a MIL-STD reading workflow, and every tool description states its interpretation boundary. Models are told to resolve exact editions and representations, pin package digests, treat search as discovery, retrieve exact evidence and governing context, distinguish tailoring from applicability, and avoid treating zero classified obligations as proof of zero requirements. See the [model reading guide](docs/MODEL_READING_GUIDE.md).

## What stays attached to the evidence

- **The exact edition.** Edition IDs describe technical editions; package digests pin inventoried content bytes. Installing a newer edition leaves existing pins intact.
- **The exact representation.** Page text, automated derived structure, reviewed structure, and curated records can coexist for one edition. Resolution reports ambiguity or accepts an explicit representation; evidence reads use the selected package digest.
- **The governing context.** Required dependencies travel with a clause. A byte budget that cannot hold the required packet produces an error instead of silently dropping evidence.
- **The original source.** Stored source hashes and exact quoted text are checked when evidence is served.
- **The access decision.** Trusted local policy authorizes access, and queries recheck it. Rights claims inside an imported pack are provenance, not permission.
- **The distinction between evidence and judgment.** Source text, derived classifications, automated checks, and human approval remain separate. Retrieved evidence does not decide applicability or certify compliance.

Exhaustive traversal follows the obligations explicitly classified in the installed pack. Its coverage depends on that pack's records and declared scope; a search result is not a completeness claim.

Edition comparison keeps exact record IDs authoritative. A unique unmatched `(kind, clause_reference)` pair is only a content-hashed, review-required candidate and cannot change statuses, dependency deltas, or impact paths. Required dependencies are traversed separately for the before and after packages; each reported path states its side, so no path can be assembled from edges that never coexisted. Source-only relocations are reported as `moved`. Reviewed cross-edition mappings, split/merge alignment, fuzzy equivalence, and semantic change classification are not inferred.

## Inspect and hand off one evidence-backed candidate

After installing the fictional pack, create a deterministic source-first reader and handoff directory:

```powershell
$resolved = standardsforge resolve EXAMPLE-SPEC-100 `
  --edition example:spec-100:2025-a `
  --representation curated_records `
  --principal local-user | ConvertFrom-Json

standardsforge export-handoff $resolved.result.package_digest `
  --record-id clause-4.2.1 `
  --principal local-user `
  --candidate examples/handoffs/fictional-adapter-requirement-draft.json `
  --output build/fictional-adapter-handoff
```

Open `build/fictional-adapter-handoff/reader.html` in a browser. It places the selected exact source language before its required governing context, citations and spans, relationships, derivation/review status, coverage, limitations, rights provenance, and the caller-authored candidate. The static file has a restrictive content-security policy, no script or form, no network or model dependency, and HTML-escapes source-controlled content. Its durable locator is a local package-and-record identity, not a bearer capability; resolving it later still requires the installed package and current authorization.

The directory is closed by `manifest.json`; `evidence-handoff.json` retains the complete detailed query packet and its digest. The draft shape is defined by [the candidate contract](contracts/handoff-candidate.schema.json). A handoff is not a requirement, test plan, applicability decision, compliance result, tailoring approval, approved baseline, or engineering approval.

## Under the hood

```mermaid
flowchart LR
    Pack["Local data-only pack"] --> Validate["Validate inventory, sources, and dependencies"]
    Policy["Trusted operator policy"] --> Install["Authorized install"]
    Validate --> Install
    Install --> Store["Immutable objects + SQLite"]
    Query["Principal + explicit selector"] --> Read["Authorize and resolve"]
    Store --> Read
    Read --> Context["Collect required context"]
    Context --> Evidence["Reverify exact spans, reauthorize, and return detailed/concise evidence"]
```

The core is a small Python library backed by SQLite and FTS5. Packs contain data and preserved sources. Query paths operate locally, with no network calls, model calls, URL fetching, or pack execution.

<details>
<summary><strong>A quick tour of the code</strong></summary>

| Module | Responsibility |
| --- | --- |
| `pack` | Validate inventories, content, citations, and dependencies. |
| `policy` | Parse trusted operator policy and authorize installation. |
| `store` | Maintain snapshots, grants, records, and lexical indexes. |
| `service` | Provide the six read operations and signed, policy-bound continuations. |
| `cli` | Expose read operations and separate administrative commands. |
| `mcp_server` | Expose only the six reads over local stdio under a startup-bound principal. |
| `source_catalog` | Validate official-source metadata and verify a closed local PDF set offline. |
| `compiler` | Compile a verified text-layer PDF into a raw-source-preserving, page-indexed pack. |
| `corpus_compiler` | Compile a verified acquisition manifest into restartable record-scoped archives and install them under exact local policy. |
| `outline_compiler` | Derive exact-span unreviewed navigation candidates and explicit unsupported regions from page records. |
| `structure_compiler` | Compile reviewed structural annotations into stable, source-spanned nodes and relationships. |
| `query_cache` | Keep bounded versioned closure/search projections without caching authorization or source verification. |
| `handoff` | Bind one authorized detailed evidence packet to a separate caller-authored candidate and deterministic no-script reader. |

Start with [the architecture](docs/ARCHITECTURE.md) or browse [the source](src/standardsforge/).

</details>

## Where this is going

The larger goal is a **standards compiler and evidence engine**: turn authorized technical documents into portable packs, then return the smallest sufficient evidence for a task.

| Stage | Scope | Status |
| --- | --- | --- |
| M0 · Foundations | Contracts, identities, and rights boundaries | Local pack subset implemented; broader decisions remain proposed |
| M1 · Local evidence engine | Pack installation, pinned retrieval, all six read operations | Implemented and locally qualified |
| M1.5 · Official source boundary | Tracked official metadata and offline local PDF integrity verification | Implemented for public-source local acquisition |
| M2 · Compilation | Raw-PDF preservation, page text, automated outlines, and reviewed source-spanned structure | Implemented; document-wide review remains incomplete |
| M3 · Identification and reading | Honest coverage, concise evidence, batched retrieval, caches, and source-linked scoped search | Implemented; derived nodes remain unreviewed candidates |
| M4 · Model access and onboarding | Principal-bound stdio MCP, model-facing MIL-STD guidance, and copy-paste local setup | Implemented; additional host adapters remain optional |
| M4.5 · Source-first handoff | Deterministic no-script reader for one pinned record, required context, and a separate caller-authored candidate | Implemented and locally qualified; corpus-wide interactive reading remains planned |

The same boundary is clearer when grouped by current product maturity:

| Status | Capabilities |
| --- | --- |
| Implemented and locally qualified | Closed data-only packs; trusted-policy authorization; six offline read operations; package-pinned search, retrieval, context, enumeration, and conservative edition comparison; detailed, compact, and concise packets; deterministic compilation stages; non-mutating doctor; content-bound synthetic benchmark; reproducible dependency-free wheel; deterministic synthetic starter; one-record source-first reader and neutral engineering handoff |
| Experimental or bounded | Automated derived outlines; reviewed exact-span structure and semantic packets; real-corpus prepared distribution assembly; local stdio MCP host integration. The fixed PDF worker policy passed the 1,107-page MIL-STD-810H acceptance source on Windows; protected Linux CI remains unobserved. Each retains explicit coverage and review limits |
| Planned or not yet qualified | Corpus-wide interactive outline/PDF reader and side-by-side rendered editions; reviewed mapping artifacts for split and merged revisions; document-wide human-reviewed semantic quality; OCR and figure interpretation |

Full visual fidelity, table-cell and figure-visual interpretation, reviewed document-wide clause segmentation, and obligation classification have not been established. A hosted multi-tenant service is not a product target. See the [validation report](VALIDATION_REPORT.md) for recorded checks and limits, and the [backlog](backlog/tasks.json) for acceptance criteria.

## Work on it

Run the existing checks from the repository root:

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
python scripts/release_evidence.py generate --wheel-dir build/ci-wheel --starter build/standardsforge-starter.zip --output build/release-evidence --repository OWNER/REPOSITORY --repository-uri https://github.com/OWNER/REPOSITORY
python scripts/verify_release_evidence.py build/release-evidence --wheel-dir build/ci-wheel --starter build/standardsforge-starter.zip
```

The suite covers pack and source integrity, policy and revocation boundaries, all read operations, MCP in-memory and stdio paths, resource-limited isolated PDF parsing, deterministic PDF/corpus/outline compilation, representation selection, response profiles and budgets, caches, database snapshots, migrations, and negative cases. The disposable PDF worker uses a closed digest-bound protocol and fixed memory, CPU, wall-time, content, text, aggregate, and metadata limits; any parser failure makes the component fail and a corpus remain incomplete. The fixed policy also compiled the tracked 35,214,720-byte, 1,107-page MIL-STD-810H acceptance source on Windows with all pages represented. The separate content-bound benchmark exercises exact resolution, all three lexical modes, required context, outside-baseline honesty, and edition comparison against fictional packs with networking denied. It qualifies synthetic contract behavior only; real-document accuracy, semantic fidelity, tokenizer efficiency beyond that acceptance source, Linux full-document resource behavior, and engineer time remain unmeasured. Real PDFs and generated packs remain ignored local inputs.

Build the prepared release only from the completed local corpus and qualified outline:

```powershell
python scripts/validate_installed_wheel.py --build-tool-dir build/toolchain-cache --output-dir build/prepared-wheel
python scripts/build_prepared_distribution.py `
  --corpus-index .standardsforge/corpus/mil-std-current/corpus.json `
  --acquisition-manifest .standardsforge/sources/dla/mil-std/manifest.json `
  --outline-pack .standardsforge/compiled/mil-std-810h-derived-outline `
  --wheel build/prepared-wheel/standardsforge-0.1.0a1-py3-none-any.whl `
  --wheel-provenance build/prepared-wheel/standardsforge-0.1.0a1-py3-none-any.whl.provenance.json `
  --output build/standardsforge-ready-0.1.0a1.zip `
  --version 0.1.0a1
```

The wheel gate installs the exact backend artifact selected by `build-toolchain.lock.json`, builds twice without index access or build isolation under a fixed source epoch, requires byte identity, installs the exact result in a fresh environment, and retains it only after the core smoke passes. The distribution builder rejects a wheel or source tree that differs from `provenance/wheel-build.json`, incomplete corpora, an acquisition manifest that does not match the corpus snapshot, inconsistent scope counts, missing or changed archives, duplicate pack identities, a derived outline that claims review or classified obligations, and policies that do not exactly authorize the public compiled pack set. It reopens the completed archive and verifies every inventoried file before publishing it. The release includes the exact `provenance/acquisition-manifest.json` snapshot, machine-readable `provenance/source-baseline.json` and `provenance/wheel-build.json` records, and a SHA-256 checksum file.

Deterministic sidecar evidence adds CycloneDX 1.7 SBOMs, unsigned in-toto/SLSA-shaped build statements, source and lock bindings, and an offline verifier. Unsigned local evidence proves digest consistency only. The protected main-branch workflow separately rebuilds the release candidate and uses a commit-pinned GitHub action to sign SBOM attestations after the matrix passes; pull-request jobs have no identity-token permission. See [release evidence and attestation verification](docs/RELEASE_EVIDENCE.md) for the online and pre-fetched offline procedures.

Before contributing, read [CONTRIBUTING.md](CONTRIBUTING.md). Bring synthetic or demonstrably redistributable fixtures, and keep source facts distinct from interpretations.

| Looking for… | Start here |
| --- | --- |
| Project orientation | [Start here](START_HERE.md) |
| Product goals and invariants | [Product baseline](docs/PRD.md) |
| Design and decisions | [Architecture](docs/ARCHITECTURE.md) · [Decision index](docs/adr/README.md) |
| Pack and query contracts | [Contracts](contracts/README.md) |
| Release ownership and content permissions | [Governance](GOVERNANCE.md) |
| Reporting a vulnerability | [Security policy](SECURITY.md) |

## License

Code is licensed under [Apache 2.0](LICENSE). Standards content has separate permissions; the code license does not grant rights to third-party documents.
