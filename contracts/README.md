# Machine contracts

The JSON Schemas describe the public 0.1.0 pack manifest, inventory, records, rights claims, and trusted local policy shapes. Runtime validation is deliberately stricter where filesystem evidence is required: it verifies inventory closure, byte counts, SHA-256 values, source quote presence, edition consistency, dependency targets, and data-only paths.

`source-catalog.schema.json` describes tracked metadata for locally acquired official sources. Runtime validation additionally enforces stable DLA Quick Search URLs, safe PDF filenames, directory closure, PDF signatures, exact byte counts, and SHA-256 digests. The catalog is not a download script and its rights metadata does not authorize repository redistribution.

`extraction-report.schema.json` describes deterministic PDF text-layer compilation results. Compiled PDF records cite the original inventoried PDF and an exact half-open UTF-8 range in a separate inventoried text sidecar. `records-v0.2.schema.json` removes the duplicate page-text field from portable page records; validation reconstructs the exact in-memory text from that verified byte range. The 0.1 records contract remains supported for existing and structural packs. The report keeps text extraction, OCR, visual fidelity, tables, figures, clause boundaries, and obligation classification as independent dimensions.

`structure-annotations.schema.json` describes edition-bound agent or human review over exact physical-page UTF-8 spans. `records.schema.json` carries stable logical IDs, content hashes, parent relationships, typed targets, and relationship evidence spans separately from physical locations.

Pack manifests distinguish `page_text`, `derived_structure`, `reviewed_structure`, and `curated_records`. `derived_structure` is an automated, unreviewed representation: it may expose navigation candidates and unsupported regions but cannot imply semantic correctness, confirmed obligations, or human approval.

`query-operations.json` identifies the seven read operations and their authority/pinning invariants. `mcp-tools.json` fixes the local stdio MCP surface, trusted startup-principal boundary, and exact caller-visible arguments. Returned packet details remain pre-release and are locked by the acceptance tests; no HTTP adapter is implemented.

The MCP contract also records the client-visible MIL-STD reading guidance and exact per-tool descriptions. Initialization guidance covers edition/representation selection, immutable package pins, discovery versus evidence, governing context, tailoring and applicability, and honest classification coverage. This guidance does not expand the seven-tool read-only surface or grant authority.

`compact-evidence-response.schema.json` describes the opt-in `compact_evidence_v1` response profile for `get_clause` and `build_context`. Omitting `response_profile` retains the established detailed JSON response. Compact records keep exact text and canonical record IDs while packet-local references navigate deduplicated source and derivation dictionaries; byte budgets cover the complete compact JSON packet.

`concise-evidence-response.schema.json` describes the measured `concise_evidence_v1` profile. It collapses verified check dictionaries, interns structural spans and provenance, and merges duplicate governing-edge declarations while retaining exact text, canonical IDs, citations, coverage, authorization, and unresolved relationship meaning.

Search may be constrained by an authorized package digest and exact/dot-descendant clause prefix. Queries over 32 parsed terms are rejected, and returned matches carry source citations, indexed-text snippets, and available structural ancestry. These are narrowing constraints only; query execution has no synonym, network, model, or scope-broadening fallback.

`get_clause` accepts `clause_reference`, canonical `record_id`, or both. At least one selector is required; when both are supplied they must identify the same record in the pinned package. This makes the complete `evidence_selector` returned by search directly replayable without discarding canonical identity.
