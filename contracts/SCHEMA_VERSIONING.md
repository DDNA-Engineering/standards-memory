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

### 2026-09-22

- Added `corpus-extraction-report.schema.json` for the multi-component DLA corpus report. The existing `extraction-report.schema.json` remains the single-PDF report contract; the two shapes are no longer conflated.
- Added release evidence, CycloneDX SBOM, build statement, wheel provenance, starter bundle and receipt, engineering handoff, benchmark, doctor, parser protocol, and prepared-distribution contracts at their initial declared versions.
- Added `structure-annotations` 0.2.0 with bounded ordered multi-span nodes and reviewed semantic provenance while retaining the one-span 0.1.0 contract.
- Added `structure-annotations` 0.3.0 for explicit source-bound `sequence_after` procedure-step relationships while retaining 0.1.0 and 0.2.0 behavior.
- Added prepared-distribution 1.2 with a pinned MCP runtime requirement and hash-bound offline wheelhouse identity; 1.1 artifacts remain identifiable but are not accepted by the current setup path.
- Added offset-backed page records 0.2.0 while retaining records 0.1.0 for existing structural and curated packs.
- Added query response 0.2.0 for explicit lexical modes and conservative edition-alignment evidence while retaining the established operation-specific 0.1.0 packets where applicable.
- Added query response 0.3.0 for authorization-safe installed-document inventory and retained the complete six-operation 0.2.0 schema under `query-response-v0.2.schema.json`.
- Added query response and success envelope 0.4.0 for bounded natural-language discovery, retained query response 0.3.0 and its success envelope under versioned filenames, and eliminated the prior unversioned success-envelope identifier.

Future changes append a dated entry here in the same commit as the schema, generator, validation, migration or compatibility behavior, and negative tests.
