# Validation report

Date: 2026-09-22

Scope: `TASK-001` through `TASK-016` plus `TASK-033` maintenance acceptance: deterministic local evidence engine, authorization-safe installed-document discovery, stdio MCP adapter with model-facing MIL-STD reading guidance, official-source integrity boundary, PDF/derived-outline/reviewed-structure/corpus compilers, honest coverage, concise responses, exact page/structure spans, source-linked scoped discovery, lossless storage/wire compression, policy-bound installation of the downloaded local MIL-STD corpus, prepared end-user distribution, and post-build documentation/code-comment cleanup

Repository state at validation: local uncommitted development working tree

## StandardsForge rename verification

The project was renamed locally to StandardsForge on 2026-09-21. The distribution and Python module are `standardsforge`; the console commands are `standardsforge` and `standardsforge-mcp`. The README uses the new name and contains no emojis.

After the rename, editable installation succeeded, all existing tests passed, and contract validation returned the same two fixture digests recorded below. Both renamed console entry points returned help successfully, and both README demo blocks completed successfully. README file links and heading anchors were checked. The old editable distribution was removed from the local virtual environment.

Historical input names, build results, schema IDs, and pack provenance below retain their original identities. Existing evidence was not rewritten. New default local state is stored under `.standardsforge/`; `START_HERE.md` describes how to point the renamed commands at an existing store.

## Requirements addressed

Thirty-one bounded requirements are represented in `docs/requirements/requirements.json`, including identity/pinning, exact evidence, dependency context, pack contracts, all seven read operations, exhaustive scoped traversal, edition comparison, rights-policy separation, offline operation, continuation binding, rebuildable indexes, completeness dimensions, official-source integrity, deterministic PDF compilation, extraction-fidelity separation, coverage propagation, source-spanned structure, concise responses, batching, versioned authorization-safe caches, exact scoped discovery, and authorization-safe installed-document inventory. `TASK-033` adds the maintenance release inventory and bounded near-match slice without changing the sealed compiler-0.3 corpus boundary.

The `v0.1.0a2` maintenance slice is based on immutable `v0.1.0a1` source commit `6f112ab` so the shipped compiler-0.3 corpus remains accepted without broadening current main's compiler boundary. It adds only query-side store, service, CLI, MCP, contract, test, documentation, and version metadata. `list_documents` returns current principal-authorized packages in a stable signed traversal with exact identity, representation, digest, record count, and declared coverage. Exact resolution returns only bounded authorized exact-selector, prefix, or family candidates and reauthorizes them immediately before the typed failure. The maintenance suite passed 79 tests in 10.126 seconds; contract parsing reported 13 documents, 31 requirements, and tasks `TASK-001` through `TASK-016` plus `TASK-033`; compilation and `git diff --check` passed. Prepared-archive, reproducible-wheel, clean-extraction, public-download, and remote-CI evidence is recorded only after those separate release steps complete.

The `v0.1.0a3` issue-#3 maintenance slice preserves the same immutable compiler-0.3 corpus boundary and changes only query-side projections, service behavior, CLI and MCP adapters, contracts, tests, documentation, and version metadata. Search now has four explicit modes: compatibility-default `all_terms`, `exact_phrase`, `any_terms`, and `natural_language`. Natural-language discovery uses a separate rebuildable schema-5 Porter FTS projection, a fixed stopword policy that preserves engineering modality and condition terms, strict stemmed AND followed by at most one disclosed stemmed OR fallback, and row-local length-normalized scoring unaffected by unauthorized rows. Raw queries and parsed terms are bounded before FTS execution. MCP tool titles and every input field are documented, while `list_documents` and exact `resolve_document` remain the identifier and edition-selection path. This remains offline lexical candidate discovery; it does not decide applicability, completeness, or compliance. The maintenance suite passed 89 tests in 10.759 seconds; contract parsing reported 13 documents, 31 requirements, and tasks `TASK-001` through `TASK-016` plus `TASK-033`; compilation, dependency checking, and `git diff --check` passed. Prepared-archive, reproducible-wheel, clean-extraction, public-download, and remote-CI evidence will be recorded only after those separate release steps complete.

The `v0.1.0a3` wheel was built twice from clean, fixed-epoch source and was byte-identical at 100,103 bytes with SHA-256 `99bc6af31f2d0e7f303cac0b519dfad53a73d21d7557d8d719be59d1b4cffd72`. An outside-checkout core install, dependency check, and empty-authorized-store search passed. The prepared archive is 1,058,599,844 bytes with SHA-256 `6c989a8b03c2b5208dded606c99c3bc14b6ecdc136f2f7052da0ddc105cb58ac`. Independent closure verified all 484 declared files with no missing or extra files and exact byte lengths and hashes. A fresh extraction under a path containing spaces and non-ASCII text installed 438 corpus packs plus the derived outline; both the initial setup and a repeated setup passed. The real launcher returned five candidates for a prose low-pressure query in `natural_language` mode with `stemmed_all_terms` disclosed. A real stdio MCP client observed exactly seven read tools, a title and description for every input, all four search modes with `all_terms` as default, and a successful natural-language search with five candidates. These are local release-acceptance results; public asset availability and remote CI remain separate evidence.

## Official-source seed corpus

The tracked catalogs record stable DLA Quick Search detail URLs and exact identities for three foundational format authorities plus MIL-STD-810H Change 1. Their PDF bytes are local ignored inputs under `.standardsforge/sources/dla/`; they are not repository content. The catalogs record publisher/source page counts, while local verification checks directory closure, regular-file properties, PDF signatures, byte lengths, and SHA-256 digests.

| Document | Edition | Bytes | Pages declared | SHA-256 |
|---|---|---:|---:|---|
| `MIL-STD-961` | Revision E, Change 5, 2025-11-25 | 7,272,070 | 127 | `92e0e2c1d39cb1b751d0c6807799ed651c81f20fb102cb3f26c3b392708876bd` |
| `MIL-STD-962` | Revision D, Change 3, 2025-05-06 | 6,099,517 | 85 | `663cf289b6c4ccc4773cd7709b674e6cc6aaa4d670b9db34bfdec96818fea2df` |
| `MIL-STD-967` | Change 3, 2025-08-27 | 4,964,679 | 67 | `f14dce9126a03f08a75a3c4273f42327c499dd074e7a518f9d00252f4a58d661` |
| `MIL-STD-810` | Revision H, Change 1, 2022-05-18 | 35,214,720 | 1,107 | `b34534a6e849b63b2c31c5a5d235b822e01849300b4ff9d4b18e692161f13935` |

This tracked seed set is not a project-applicability decision or the complete local military-standard acquisition. The larger acquisition manifest and its ignored local source bytes are compiled separately by `TASK-013`. The supplied product material explicitly names MIL-STD-961; MIL-STD-962 and MIL-STD-967 complete the format-authority set, while the user explicitly selected MIL-STD-810H for environmental-engineering coverage.

## Input provenance

The attached documents were treated as proposed product/build guidance and were not treated as evidence that a runtime already existed.

| Input | SHA-256 |
|---|---|
| `AGENTS.md` | `c634916cf29b1b90e0d04f2cf520483826bdffad6f0417c2bd3560c0f27ba140` |
| `START_HERE.md` | `bf87a035ff196943a7201800743945dca815b127f22790b54fa4d7d2f6160b38` |
| `Standards_Memory_PRD.docx` | `5a346b0660f4904422c7df13426c7e9f6b73c0397b2daae389a8028a47ae308f` |
| `Standards_Memory_Architecture_and_ADRs.docx` | `897b35823f1e3d0505b873f6f80b2e162295ef5b7e1aa749ccf3aa76acdd1aeb` |

## Commands and observed results

Runtime environment: Windows, Python 3.12.14, SQLite 3.53.1, MCP Python SDK 2.2.0, pypdf 6.19.0. Isolated builds use the `setuptools==84.0.0` backend pinned in `pyproject.toml`.

```powershell
python -m pip install -e ".[mcp,compiler]"
```

Observed: exit 0; the editable package and exact optional dependencies `mcp==2.2.0` and `pypdf==6.19.0` installed into an isolated local virtual environment. `python -m pip check` subsequently reported no broken requirements.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python scripts/validate_contracts.py
```

Observed: exit 0. Thirteen machine contract documents parsed; 30 requirement identities resolved across `TASK-001` through `TASK-016`; two source catalogs loaded four unique document/edition/file identities; both three-record fixture packs validated.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m unittest discover -s tests -v
```

Observed: exit 0; 62 tests passed in 6.423 seconds. In addition to the earlier install/read/tamper/coverage/cache cases, the suite preserves distinct ambiguous candidate sets and derivations, validates exact single-pass response budgets, migrates and rebuilds external-content FTS5, keeps FTS synchronized across insert/update/delete, reconstructs records 0.2 page text only from verified UTF-8 offsets, rejects PDF and sidecar tampering, proves deterministic archive identity, and exercises both backward-compatible and `structured_only` MCP stdio modes.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m standardsforge verify-source-set catalog/mil-format-authorities.json --source-root .standardsforge/sources/dla/format-authorities
python -m standardsforge verify-source-set catalog/mil-std-810h.json --source-root .standardsforge/sources/dla/mil-std-810h
```

Observed: exit 0. Four local PDFs and 53,550,986 bytes were verified without network access. Every file matched its cataloged signature, byte count, and SHA-256 digest. Page counts were reported as declared metadata and were not recomputed by this command.

```powershell
python -m standardsforge compile-pdf catalog/mil-std-810h.json MIL-STD-810 `
  .standardsforge/compiled/mil-std-810h `
  --source-root .standardsforge/sources/dla/mil-std-810h
```

Observed: exit 0. The 1,107-page source produced 1,107 unreviewed page records, a 7,799,076-byte extracted-text sidecar, an 8,910,893-byte records document, and a 414,816-byte extraction report. The generated pack digest is `123e17f14c0e484eca5c03a4b34f3c5929f4946ff792711ee052b8fcd633b04c`. A second complete compile to a different directory produced the same digest. Rotated text was retained, with degraded layout and all visual fidelity still marked unverified.

The full pack validated, installed into an isolated local store in 3.218 seconds, resolved its exact edition, returned five ranked hits for `explosive atmosphere`, and retrieved the selected page with both raw-PDF and extracted-text hashes reverified. No OCR, model, or network fallback was used.

```powershell
python -m standardsforge compile-structure catalog/mil-std-810h.json MIL-STD-810 `
  .standardsforge/annotations/mil-std-810h-method-500.6-2.2.2.json `
  .standardsforge/compiled/mil-std-810h-method-500.6-2.2.2 `
  --source-root .standardsforge/sources/dla/mil-std-810h
```

Observed: exit 0. The explicitly agent-reviewed Method 500.6 section 2.2.2 slice on physical pages 86–87 produced six structural records and package digest `2babee8bf4085d2c3612939b4205613b83341dc0a97356b63943dbf18933dcbe`. Independent pack verification passed. An isolated authorized install and retrieval of item 2.2.2.d returned its governing NOTE as required evidence, retained the out-of-scope paragraph 1.3 reference, and reported `partial_reviewed_structural_section_only` with aggregate completeness false. This is not a document-wide semantic or human-review claim.

Canonical fixture measurements after compact-profile implementation were 3,342 detailed versus 3,412 compact bytes for one two-record clause packet, and 4,072 detailed versus 3,901 compact bytes for a three-record multi-clause context. The compact profile is therefore a measured reduction only for the latter fixture. No local tokenizer is configured; token counts are reported as unavailable rather than inferred from bytes.

`TASK-011` measured the exact MCP text JSON with the locally cached `tiktoken==0.9.0` `o200k_base` encoding; socket access was not needed. The two-record fixture measured 898 detailed, 905 compact, and 853 concise tokens. Three-record fixture context measured 1,121 / 1,060 / 999; one real page measured 1,042 / 1,106 / 1,015; eight pages measured 11,406 / 10,189 / 10,035; 64 pages measured 79,471 / 68,006 / 67,348; and reviewed structural evidence measured 2,456 / 2,370 / 1,779. These measurements name the encoding and representation; the product still reports token measurement unavailable because no runtime tokenizer is configured.

Post-`TASK-010` measurement on a disposable database copy of the installed 1,107-record MIL-STD-810H pack returned the same 511,658-byte 64-record detailed packet while reading the same two files and 43,013,796 bytes once per request. Ten warm runs measured p50 51.734 ms and p95 52.542 ms, compared with the pre-change audit's p50 766.055 ms and p95 812.378 ms. Fixture obligation enumeration measured p50 2.216 ms versus 4.936 ms before the change, with one 536-byte source read and five SQLite connections instead of two reads totaling 1,072 bytes and ten connections. These are local warm diagnostic samples, not production service-level guarantees.

A fresh `TASK-011` compile of all 1,107 MIL-STD-810H pages produced package digest `f4a5b84c1c9732ce7a073479c5dd4148e9ef1ba8dd548d7b3dc6f758ab662ae5`, explicit `page_text` representation metadata, and exact half-open sidecar offsets. Record IDs and exact text matched the earlier compile. Across 15 interleaved warm 64-page retrievals, first/middle/last groups measured p50 33.912 / 34.631 / 36.374 ms and p95 36.094 / 36.620 / 40.153 ms. The pre-fix audit measured p50 53.574 / 124.564 / 252.692 ms and p95 60.163 / 147.968 / 273.335 ms. Request-local peak Python allocation for the last 64 pages fell from the audit's approximately 90.5 MiB to 12.701 MiB by stream-hashing the preserved PDF while retaining the sidecar bytes needed for exact slices. The request still freshly hashes both preserved files; the change removes position-sensitive whole-sidecar quote searches and avoids retaining unused PDF bytes rather than weakening integrity checks.

Enriched real-pack search preserves the prior top-hit identities while adding FTS5 body snippets. After simplifying it to one FTS scan, 50 warm local SQL calls for `explosive atmosphere` returned 12 hits at p50 1.213 ms and p95 1.299 ms. Search and retrieval timings are diagnostic samples on this machine, not service-level guarantees.

`TASK-012` recompiled the complete 1,107-page source with offset-backed records schema 0.2. The uncompressed pack fell from 52,419,193 to 44,370,691 bytes, saving 8,048,502 bytes (15.35%); `records.json` fell from 8,988,094 to 939,593 bytes. Deterministic Deflate level 6 produced a 34,036,018-byte archive in 1.422 seconds and preserved package digest `469c7b5bb4dda187e5e913a0cf12d7a0d6087d5ceabfb913967514d9de479cb3` after extraction.

Installing that archive into a fresh schema-4 store produced a 12,603,392-byte database; the prior content-copy FTS database was 21,528,576 bytes. The authoritative `records` table remained 9,580,544 bytes and the FTS index data was 2,310,144 bytes, with no `records_fts_content` table. On 30 warm runs, one-page concise retrieval measured p50/p95 25.689/26.398 ms and a 64-page 481,283-byte concise packet measured 30.545/31.273 ms. The byte-identical finalizer fell from p50 6.723 to 2.391 ms; search measured p50/p95 1.656/1.844 ms across 50 runs. These remain machine-local warm-cache diagnostics.

Cross-package hard-link deduplication was not enabled. It would let mutation through any one package path alter every linked package. Safe transparent sharing requires filesystem-supported copy-on-write/block cloning or a contract-level package-path indirection and coordinated reference management; neither is silently assumed.

`TASK-013` verified the completed local DLA acquisition checkpoint at 464 active records, 967 selected current components, 912 downloaded PDFs / 1,113,274,833 source bytes, and 55 restricted metadata-only components. Manifest-driven compilation produced 438 deterministic record-scoped Deflate archives totaling 1,006,518,141 bytes. They preserve all 912 downloaded PDFs and expose 35,218 unclassified, unreviewed page records across 35,235 physical pages. The only missing text records are 17 malformed pages in MIL-STD-1661; their source bytes remain preserved and their extraction failures remain explicit. One empty-password public PDF was decrypted only for extraction while its original encrypted bytes remained the inventoried source. Compilation rejects a downloaded status unless its distribution statement is A and rejects a public component relabeled as restricted metadata.

An exact 438-pack local policy authorized installation for `local-user`. The default store contains all 438 current corpus package digests and active grants, with no index digest missing from the database or authorization set. The hardened reinstall revoked all 438 obsolete grants for the prior generated corpus version; the store retains those immutable historical objects rather than deleting them. The observed database therefore contains 877 packages and 70,439 records, while the active authorization set contains 439 grants: 438 current corpus packs plus one pre-existing three-record package. No obsolete corpus grant remains active, and all 35,218 current corpus records have statement role `unclassified`. Runtime acceptance resolved and retrieved MIL-STD-810H(1), the 129,439,361-byte MIL-STD-40051E(1) source, mixed public/restricted MIL-STD-167-2A NOT 1, and partially extracted MIL-STD-1661. Lexical search for `environmental engineering` returned source-linked MIL-STD-810H(1) evidence.

After `TASK-013`, contract validation passed for 13 contract documents, 30 requirements, and `TASK-001` through `TASK-013`. The complete local Python suite passed 67 tests in 8.579 seconds, covering networking-denied corpus composition, deterministic resume, corrupted and stale-valid archive rejection, distribution-status tampering, empty-password PDF handling, policy-bound batch install with obsolete-grant reconciliation, source retrieval, and transient Windows activation cases.

`TASK-014` compiled the current 1,107-record MIL-STD-810H page pack into a separately installable `derived_structure` pack with package digest `15546007f5f19963f3fc83cdd3da89484036348c49ff1bdf0c27f7bb42ca8f76`. The deterministic pass produced 7,788 exact-span records: 29 method headings, 240 sections, 1,627 clauses, 2,919 list items, 238 notes, 46 table captions, and 19 figure captions. It reported 188 wholly unsupported pages and 2,670 unsupported regions. Numeric table rows, repeated table-footnote runs, and repeated method headers are preserved as unsupported regions rather than allowed to alter ancestry. Every record remains `unclassified` and `automated_unreviewed`; obligation enumeration returned zero with aggregate completeness false.

The final pack installed under an exact local policy, resolved `MIL-STD-810H(1)` only when `derived_structure` was selected, and revoked the two superseded development grants. A pinned search for `low pressure` returned an exact source-linked table caption with only section 5.13 as ancestry. Exact retrieval of Method 500.6 clause 2.1 reverified the preserved PDF, extracted-text digest, physical page 85, UTF-8 bytes 636098:636643, and quote digest. Windows CLI output was additionally qualified against a CP1252-style console while emitting UTF-8 snippet markers.

After `TASK-014`, contract validation passed for 13 contract documents, 30 requirements, and `TASK-001` through `TASK-014`. The complete local Python suite passed 70 tests in 9.500 seconds, including networking-denied deterministic outline compilation, exact-span readback, table-row and footnote negative cases, non-page input rejection, sidecar tamper rejection, representation-specific resolution, exact evidence retrieval, and UTF-8 CLI output.

`TASK-015` added `write-pack-policy`, an explicit administrative command that validates one pack and requires the operator to name both the principal and expected content class before it writes an exact one-pack allowlist. Focused acceptance proved successful install and representation-specific resolution, rejection of a mismatched content class without creating a policy, rejection of an existing output, and the documented CLI argument shape. No query operation or MCP tool was added.

The MCP initialization result now carries the MIL-STD reading workflow, and all six client-visible tool descriptions carry operation-specific interpretation boundaries. Tests use a real MCP client to verify the initialization instructions, contract-description parity, unchanged tool names and schemas, read-only/closed-world annotations, startup-bound principal, and networking denial. The instructions distinguish exact editions and representations, immutable package pins, search candidates from retrieved evidence, governing context, tailoring from applicability, source requirements from verification methods, and zero classified obligations from proof of zero requirements.

The README's end-to-end Windows block covers isolated installation, corpus entry selection, outline compilation, explicit policy creation, installation, representation-specific resolution, pinned search, exact evidence retrieval, and MCP startup. PowerShell's parser accepted the complete block with no syntax errors, and CLI help exposed both onboarding commands. After `TASK-015`, contract validation passed for 13 contract documents, 30 requirements, and `TASK-001` through `TASK-015`; the complete local Python suite passed 73 tests in 8.445 seconds.

`TASK-016` removed three unreferenced dated audit snapshots whose implemented outcomes and measurements remain in this report, plus the duplicated `agents/BUILD_AGENT.md` workflow. `START_HERE.md` was reduced from 9,848 to 2,613 bytes while retaining the active baseline, required reading, validation commands, legacy-store migration, and rights/interpretation boundaries. Brand documentation now retains only usage and asset-format guidance. The decision index and security policy were updated from stale planned/fixture-only wording to the observed local public-source and MCP implementation without asserting owner approval.

Redundant MCP function docstrings, trivial class/helper docstrings, and a compatibility-restatement comment were removed. Comments explaining source integrity, relationship deduplication, unresolved-edge preservation, byte-budget arithmetic, transaction snapshots, and telemetry suppression remain because they document non-obvious correctness or security invariants. No TODO, FIXME, HACK, or XXX markers remain in source or tests.

After `TASK-016`, every retained repository Markdown link resolved locally, stale references to the removed audits and duplicated agent guide were absent, contract validation passed for 13 contract documents and `TASK-001` through `TASK-016`, compilation passed, `git diff --check` passed, and the complete local Python suite passed 73 tests in 8.966 seconds.

The prepared-distribution acceptance built `standardsforge-ready-0.1.0a1.zip` from the completed 438-pack corpus, the qualified MIL-STD-810H derived outline, an isolated StandardsForge wheel, exact public-content policies, and a file-level integrity manifest. The artifact is 1,043,153,557 bytes with SHA-256 `b95b4fd3623bf19cc02761612a16581b95acd621d361d6db9bcca4eb118502fa`. It contains 439 compiled packs representing 912 verified PDFs, 35,218 page records, and 35,235 physical pages. Restricted-only DLA records are not included.

Acceptance used a newly extracted directory with no existing database, object store, virtual environment, or `py` launcher. `setup.ps1` fell back to `python`, installed the bundled wheel without dependencies, validated and installed all 438 corpus packs, installed the derived outline, and completed its smoke query. The distribution launcher then resolved the exact `MIL-STD-810H(1)` `derived_structure` package and completed a separate `low pressure` search. No source acquisition, PDF compilation, model call, or network access occurred during corpus setup or query. The release artifact and checksum remain ignored local build outputs and have not been published.

After the distribution change, contract validation and `git diff --check` passed. The complete suite passed 73 tests in 9.333 seconds under the repository `.venv` with pinned `pypdf==6.19.0` and MCP SDK 2.2.0. A run under the unrelated system Anaconda environment was rejected by the compiler dependency guard and incompatible MCP import, confirming that repository validation must use the documented isolated environment.

The first FontTools-free corpus attempt was stopped after pypdf exposed incomplete CFF Type1 decoding. Its 340,857,086 bytes of generated output were moved intact to ignored quarantine at `.standardsforge/generated-artifact-quarantine/mil-std-current-pre-fonttools`; source files were not changed. The pre-hardening 438-pack corpus and policy were likewise moved intact to ignored quarantine before regeneration. The final compiler pins `pypdf==6.19.0` and `fonttools==4.65.0`, records both versions in derivations, and was rebuilt from a fresh output root. Transient OneDrive `WinError 5` conditions during compiled-directory and object-directory activation were reproduced with focused tests and handled through bounded retry followed by the same package and archive validation.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m compileall -q src tests scripts
```

Observed: exit 0.

```powershell
python -m pip wheel . --no-deps --wheel-dir <ignored-local-directory>
```

Observed: exit 0; `standardsforge-0.1.0a1-py3-none-any.whl` built successfully with isolated build dependencies and contained the compiler, source-catalog verifier, MCP server module, and both console entry points. A stale pre-rename build directory initially caused obsolete `standards_memory` modules to leak into a wheel; those generated artifacts were quarantined under ignored local state, the wheel was rebuilt from a clean build directory, and the final wheel contains no `standards_memory` package. The artifact remains in ignored local validation state.

The pre-publication credential-pattern and absolute-local-path scans passed with zero matches.

## Fixture digests

| Pack | Edition | Package digest |
|---|---|---|
| `example.vehicle-adapter.1.0` | `example:spec-100:2025-a` | `3c27ee682401e154425f806614a800d744f472f1be41e9e412f9214460f12117` |
| `example.vehicle-adapter.2.0` | `example:spec-100:2026-b` | `ad93262351fbf1138f841e7f964fca95ffe7c5139778996ec851bdd91df33ad3` |

## Security and rights effects

Pack rights records are preserved as claims and cannot authorize installation or serving. An external operator policy must authorize the exact pack ID and content class; its fingerprint is stored with a digest-bound principal grant. Reads check active authorization before access and again before returning an evidence packet. Query operations do not import, activate, publish, execute, download, invoke models, or create sockets.

The MCP adapter accepts its principal only from trusted process startup configuration and exposes no administrative tool. It runs only over stdio, creates no listener, and removes the pinned SDK's OpenTelemetry middleware before accepting calls. Expected domain failures are marked as MCP errors and carry the existing typed JSON error envelope without returning the bound principal.

Data-only suffix restrictions, inventory closure, byte counts, hashes, source quote checks, dependency resolution, path traversal checks, symlink denial, and bounded archive size/file counts are enforced during pack validation. Source-catalog validation independently enforces a closed directory, safe single-component PDF filenames, stable official-source URLs, PDF signatures, byte counts, digests, and non-assertion of repository redistribution rights.

The single-PDF compiler rejects encrypted PDFs; the DLA corpus compiler additionally accepts empty-password public encryption and rejects non-empty passwords. Both reject mismatched declared page counts, oversized source/page streams, missing document-wide text layers, and conflicting outputs. Raw PDF sources and extracted text are independently inventoried and rechecked. PDF actions are never executed. Rights metadata remains provenance and cannot grant install or query permission.

## Migration and rollback

The local database is schema version 4. Tested v1/v2/v3-to-v4 migrations add explicit derivation/statement-role/structure fields where needed, rebuild FTS5 as an external-content projection, and mark legacy derivations `unknown`/`unreviewed`; they never invent obligation classifications or structure. Installation is content-addressed and metadata activation is transactional. To roll back a development instance, stop using the local CLI and remove only its explicitly selected database/object directory. Grant revocation provides immediate logical denial without deleting evidence bytes.

## Limitations

- Real PDF text layers are compiled and source-linked. One reviewed structural section is qualified, but document-wide visual reading order, tables, figures, OCR, semantic clauses, dependencies, and obligation classification are not qualified.
- The seven read operations are implemented in the local library, CLI, and stdio MCP adapter; no HTTP transport is implemented, and a hosted multi-tenant service is not a product target.
- No reader UI, background compilation worker, model adapter, broad performance benchmark, configured tokenizer, SBOM, or signed release artifact.
- Exact quote presence is not proof of PDF fidelity, and returned evidence is not an applicability, compliance, or human approval decision.
