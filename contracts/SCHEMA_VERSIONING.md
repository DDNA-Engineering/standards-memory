# Contract versioning and change log

StandardsForge machine contracts are closed interfaces, not examples. Every schema declares a draft, a stable `$id`, and an exact instance `schema_version`. Build and test tooling checks each schema against its declared metaschema and validates generated representative artifacts against the matching contract.

## Version policy

- A documentation-only correction that does not change accepted instances may retain the contract version.
- Any change to required fields, accepted values, field meaning, bounds, or cross-field interpretation requires a new instance version. Tightening and widening are both versioned changes.
- A new incompatible version is represented explicitly in the schema and generator. Older versions remain accepted only when the runtime contains a deliberate validation or migration path for them.
- A migration must preserve source identity and evidence. It may not invent classifications, relationships, review, applicability, or approval.
- Generators emit one exact version. Consumers reject unknown versions rather than guessing or silently coercing them.
- Runtime checks remain stricter than JSON Schema when validation depends on files, hashes, canonical serialization, authorization, or relationships across documents.
- Every generated artifact family used by a compiler, distribution builder, query adapter, benchmark, diagnostic, or handoff must have a schema-validation test. A schema-valid document is not accepted when its runtime cross-file or semantic invariants fail.

## Change log

Entries are in chronological order. Each heading names the commit that recorded the change and the first published release that contains it.

### 2026-09-22

- Added `corpus-extraction-report.schema.json` for the multi-component DLA corpus report. The existing `extraction-report.schema.json` remains the single-PDF report contract; the two shapes are no longer conflated.
- Added release evidence, CycloneDX SBOM, build statement, wheel provenance, starter bundle and receipt, engineering handoff, benchmark, doctor, parser protocol, and prepared-distribution contracts at their initial declared versions.
- Added `structure-annotations` 0.2.0 with bounded ordered multi-span nodes and reviewed semantic provenance while retaining the one-span 0.1.0 contract.
- Added `structure-annotations` 0.3.0 for explicit source-bound `sequence_after` procedure-step relationships while retaining 0.1.0 and 0.2.0 behavior.
- Added `outline-review-draft` 0.1.0 and `outline-review-decision` 0.1.0 for a single exact candidate's unreviewed proposal and explicit content-bound review decision. `structure-annotations` 0.4.0 binds the reviewed result to the exact verified page-text package, derived-outline package, candidate, and proposal without changing the older simple-extraction contracts.
- Added `outline-review-selection` and `outline-review-shard` 0.1.0 for deterministic bounded partial review sets. `structure-annotations` 0.5.0 binds each selected node to its own proposal, decision, and reviewer provenance; 0.4.0 and earlier annotation paths remain accepted unchanged.
- Added `outline-review-draft` 0.2.0 for exact ambiguous-numbered unsupported candidates pending an explicit reviewer kind/reference decision; 0.1.0 ordinary drafts and 0.1.0 content-bound decisions remain accepted.
- Added prepared-distribution 1.2 with a pinned MCP runtime requirement and hash-bound offline wheelhouse identity; 1.1 artifacts remain identifiable but are not accepted by the current setup path.
- Added offset-backed page records 0.2.0 while retaining records 0.1.0 for existing structural and curated packs.
- Added query response 0.2.0 for explicit lexical modes and conservative edition-alignment evidence while retaining the established operation-specific 0.1.0 packets where applicable.
- Added query response 0.3.0 for authorization-safe installed-document inventory and retained the complete six-operation 0.2.0 schema under `query-response-v0.2.schema.json`.
- Added query response and success envelope 0.4.0 for bounded natural-language discovery, retained query response 0.3.0 and its success envelope under versioned filenames, and eliminated the prior unversioned success-envelope identifier.

Future changes append a dated entry here in the same commit as the schema, generator, validation, migration or compatibility behavior, and negative tests.

### 2026-10-08 — scan recovery and source qualification (`ea57a73`; published in 0.1.0a6)

- Added page-transcription 0.1.0 and structure-annotations 0.6.0 for explicitly reviewed, source-package-pinned visual transcription and direct page-span semantic review. Earlier annotation versions retain their restrictions. Coverage ledgers accept declared agent/human visual review and optional verified semantic-span links; real-suite expectations accept optional modality/polarity/qualifier assertions.
- Transcription 0.2.0 adds explicit `transcribed_text` and `reviewed_blank` page dispositions. Legacy 0.1.0 remains supported without the new field. A reviewed blank has exactly empty text, retained raster/review evidence, and no text record; it stays in the physical-page ledger. The real-suite semantic assertion shape now requires the full nullable statement and exact typed qualifier objects with span indices. Earlier partial semantic assertions are rejected and require explicit review/migration; historical results remain tied to their historical runtime. Source-only suites without semantic assertions remain valid.
- Prepared distribution 1.3 accepts an optional closed `state.qualified_packs` list binding each additional archive and exact suite/run paths to its pack identity. The combined trusted policy includes these packages; both setup profiles install them and replay their regression suites before readiness. Legacy manifests without the list retain their prior behavior.

### 2026-10-08 — knowledge access and reviewed references (`db245a2`; published in 0.1.0a7)

- Query and success contracts 0.5.0 add record navigation and measured evidence selection; exact 0.4.0 schemas are retained. Concept discovery is a separate search mode, with disclosed vocabulary and ranking identity; existing lexical modes retain their behavior.
- Record navigation 0.1.0 binds pagination to package, filters, principal and grants, verifies source evidence and reports structural traversal separately from semantic completeness.
- Evidence selection and local tokenizer 0.1.0 describe pinned offline BPE measurement, exact measurement scope, lossless profile selection and explicit budget rejection. Existing evidence-profile contracts remain unchanged.
- Content bundle 0.1.0 shares exact file blobs while preserving and revalidating every original package identity. It grants no installation or serving authority.
- Offset-backed structural records 0.3.0 reconstruct one exact source span without duplicating its text in `records.json`. Existing 0.1.0/0.2.0 restrictions remain unchanged. Outline compiler 0.4.0 emits distinct `outline-v4` packages with case/punctuation-preserving logical identities and compact offset-backed records; older installed outline packages remain readable.
- Corpus outline index 0.1.0 reports each source-bound compile result and explicitly excludes semantic qualification.
- Query and success contracts 0.6.0 add `follow_references`; exact 0.5.0 copies remain versioned. New closed reference binding/navigation and answer suite/submission/adjudication/run contracts are 0.1.0. Reviewed structure compiler 0.7.0 permits direct annotations 0.6.0 to select the explicit source-PDF digest within a multi-component package, preserving the parent edition and the unreviewed status of other components.

### 2026-10-08 — original source PDFs (`f33921c`; published in 0.1.0a7) — recorded policy deviation

- Added `source-pdfs.schema.json` 0.1.0 for the `get_source_pdfs` result.
- **Deviation from the version policy above.** `query-response.schema.json` was widened in place with a `oneOf` branch referencing `source-pdfs-0.1.0`, and its description changed from ten to eleven read operations, without a new instance version. Its `$id` remained `query-response-0.6.0`. `success-response.schema.json` (`$id` `success-response-0.6.0`) was not edited but references that `$id`, so its accepted set widened with it. This entry was not recorded in that commit.
- The widened schemas shipped in published 0.1.0a7, so the published identities cannot be changed. `query-response-0.6.0` and `success-response-0.6.0` therefore name two accepted sets: the unpublished ten-operation shape recorded in `db245a2`, and the eleven-operation shape published in 0.1.0a7. Validate `get_source_pdfs` results against the a7 schema bytes. Any further change to these contracts requires a new instance version.

### 2026-10-09 — documentation only

- Recorded the deviation above, reordered this log chronologically and corrected stale "unreleased"/"unpublished" status labels. No accepted instance changed.

### 2026-10-09 — correctness review gap closure (TASK-060; unpublished)

- No instance schema changed. `contracts/mcp-tools.json` and `contracts/query-operations.json` now list every optional argument, default and enum of the eleven registered tools, and `get_source_pdfs` joins `read_operations`; `scripts/validate_contracts.py` fails on any drift between these machine contracts and the SDK-advertised tool schemas.
- MCP tool arguments are strict and closed. Wrong types and undeclared arguments return the typed error envelope with code `invalid_argument` instead of unstructured text. `code` remains a free string in `error-response`.
- Outline compiler 0.5.0 emits distinct `outline-v5` packages: a top-level numbered section is parented by its enclosing METHOD, APPENDIX or PART root, or has no parent, instead of the preceding clause. Logical and record identities are unchanged; `outline-v4` and earlier packages remain separately addressable and readable.
