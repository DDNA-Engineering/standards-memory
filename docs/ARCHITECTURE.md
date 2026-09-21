# StandardsForge reference architecture

Document `SM-ARCH-001`, version `0.1.0-design`, is a proposed reference design. The local architecture below is implemented and qualified within the stated limits; the proposal is not an owner-approved product baseline.

## Position

The core is a framework-light Python library. Canonical data-only packs and preserved sources carry evidence; SQLite stores installed snapshots, local grants, and rebuildable external-content lexical indexes. The core does not import host applications. Querying never invokes a generation model.

Source acquisition, ingestion, and query paths are separate:

```text
official publisher source -> local ignored source directory -> offline manifest verification
verified PDF -> deterministic compiler -> preserved PDF + extracted text + fidelity report -> local pack
verified page-text pack -> deterministic outline compiler -> exact-span automated candidates + unsupported regions -> separate derived-structure pack
verified PDF + reviewed annotations -> structural compiler -> stable nodes + typed source-spanned relationships -> local pack
operator policy + local pack -> validation -> immutable object store -> atomic SQLite install
principal + explicit selector -> authorization -> snapshot-pinned batched dependency closure -> request-local page/node/relationship span re-verification -> detailed, compact, or concise evidence packet
```

The source repository carries source metadata and verification code, not third-party PDF bytes. The separate prepared distribution may carry verified compiled packs containing only components classified by the recorded publisher metadata as Distribution Statement A. Acquisition and compilation are explicit maintainer actions; end-user setup validates and indexes the included packs locally. Query code does not download or synchronize documents.

## Authority and identity

The source file is the preserved evidence. Records are extracted representations. A package digest identifies inventoried bytes, an edition ID identifies technical composition, a representation identifies page text, automated derived structure, reviewed structure, or curated records, and a document-family ID identifies a publisher-scoped family. They are never interchangeable. Resolution never chooses silently among multiple authorized representations; the package digest remains the authoritative read pin.

Rights statements inside a pack are provenance only. Operational authorization comes from a separate local policy, is persisted as a digest-bound grant, and is checked immediately before every query result. Withdrawal can disable access without changing evidence bytes.

## Implemented modules

- `pack`: strict data-only inventory, content, citation, and dependency validation.
- `policy`: trusted operator policy parsing and install authorization.
- `store`: SQLite snapshot metadata, grants, records, and FTS5 projection.
- `service`: all six read operations, signed policy-bound continuations, and separate install/revoke administration.
- `cli`: separate administrative and read-only query commands.
- `mcp_server`: local stdio adapter exposing exactly the six read operations under a startup-bound principal, with no administration, listener, or telemetry middleware.
- `source_catalog`: strict metadata validation and offline integrity verification for a closed local PDF source set.
- `compiler`: strict PDF text-layer extraction into page records, with raw PDF preservation, extracted-text sidecars, and explicit fidelity dimensions.
- `corpus_compiler`: Distribution Statement A-gated DLA acquisition composition, deterministic record-scoped unclassified page packs, composition-and-provenance-validated restartable archives, exact local policy generation, and policy-bound batch installation with obsolete-grant reconciliation.
- `outline_compiler`: deterministic exact-span method, clause, list, note, and caption candidates from verified page records, with ambiguous and unmatched content retained as unsupported regions and no automatic obligation or approval claim.
- `structure_compiler`: reviewed structural nodes and typed relationships bound to exact verified PDF/page-text spans.
- `query_cache`: bounded versioned in-process closure and search projections with checksum-verified envelopes; authorization decisions and source verification are never cached.

New page packs use records schema 0.2: portable records retain the exact sidecar path, digest, half-open UTF-8 offsets, and quote digest but do not repeat the text bytes. Validation reconstructs the in-memory record text from the verified slice before installation. Records 0.1 remains accepted for existing and structural packs. Deterministic Deflate archives are transport only and are unpacked into the same verified installed representation.

The FTS5 table is an external-content projection over `records`; transactional triggers and schema migration rebuild it from authoritative stored rows. It therefore stores index data but not a second full content table.

Document-wide reviewed semantic clause segmentation, automated dependency derivation, obligation classification, OCR, table-cell and figure-visual interpretation, optional semantic adapters, the reader, and additional local-host adapters remain outside the completed slices. Derived outlines are source-linked unreviewed navigation candidates, not semantic correctness or applicability claims. The full local corpus remains a source-linked physical-page representation unless a separate derived or reviewed pack is explicitly selected. A hosted shared-server profile is not planned; the local MCP adapter is a process boundary for a user-controlled installation.

Required closures are cached only as package-pinned record IDs and edges. Every request reloads current rows, re-reads and hashes each distinct source or sidecar once, and reauthorizes immediately before return. Search cache keys include corpus and authorization generations, the caller's active visibility fingerprint, exact filters, limit, and ranker version. Package installation/grant changes and revocation advance generations.

Verified bytes, resolved paths, and decoded UTF-8 text are shared only inside one request. Compiled page records and structural node/relationship evidence spans are checked against exact half-open UTF-8 byte offsets and quote digests. Legacy packs without page offsets retain the full-sidecar compatibility check. Structural validation requires its resolved required-edge projection to equal the retrieval dependency projection. Obligation pages expand one union closure and project the established per-obligation response shape; edition comparisons keep one verification context per package.

`concise_evidence_v1` is an opt-in progressively expandable projection. It includes each exact evidence record once, merges governing relationship declarations, and interns sources, derivations, structure nodes, and spans into packet-local registries. It retains explicit authorization and coverage. Detailed JSON remains the compatibility default, and tokenizer measurements are reported only when a tokenizer is explicitly configured or an external benchmark names the encoding.

The MCP server defaults to `text_and_structured`, returning the existing JSON text and structured result. Trusted startup configuration can select `--result-mode structured_only` to omit the duplicate success text payload; tool callers cannot select the mode, and typed errors remain text results.

MCP initialization supplies a concise MIL-STD reading protocol, and each tool carries an operation-specific interpretation boundary. The instructions route a model from exact resolution to package-pinned discovery and evidence retrieval, distinguish physical page text, automated derived structure, reviewed structure, and curated records, and prohibit converting normative wording or incomplete obligation enumeration into applicability or compliance claims. Clients that ignore MCP initialization still receive the critical boundary in each tool description and in returned coverage and derivation fields.

`write-pack-policy` is an administrative onboarding aid, not a query operation. It validates the pack, requires the operator to state the principal and expected content class, rejects a mismatch with the pack claim, and writes an exact one-pack allowlist. The subsequent install and all reads continue through the existing external-policy authorization boundary.

Lexical discovery rejects queries beyond its declared 32-term limit rather than discarding constraints. FTS5 produces matched snippets over indexed record text; results include exact source citations and structural root-to-parent ancestry when present. Exact identifier resolution remains a separate operation with no hidden lexical, network, or model fallback.
