# Standards Memory reference architecture

Document `SM-ARCH-001`, version `0.1.0-design`, is a proposed reference design. The current code implements one local vertical slice, not the complete architecture.

## Position

The core is a framework-light Python library. Canonical data-only packs and preserved sources carry evidence; SQLite stores installed snapshots, local grants, and rebuildable lexical indexes. DDNA is not imported by the core. Querying never invokes a generation model.

The ingestion and query paths are separate:

```text
operator policy + local pack -> validation -> immutable object store -> atomic SQLite install
principal + explicit selector -> authorization -> identity resolution -> dependency closure -> evidence packet
```

## Authority and identity

The source file is the preserved evidence. Records are extracted representations. A package digest identifies inventoried bytes, an edition ID identifies technical composition, and a document-family ID identifies a publisher-scoped family. They are never interchangeable.

Rights statements inside a pack are provenance only. Operational authorization comes from a separate local policy, is persisted as a digest-bound grant, and is checked immediately before every query result. Withdrawal can disable access without changing evidence bytes.

## Implemented modules

- `pack`: strict data-only inventory, content, citation, and dependency validation.
- `policy`: trusted operator policy parsing and install authorization.
- `store`: SQLite snapshot metadata, grants, records, and FTS5 projection.
- `service`: all six read operations, signed policy-bound continuations, and separate install/revoke administration.
- `cli`: separate administrative and read-only query commands.

The future compiler, HTTP/MCP adapters, optional semantic adapters, reader, and shared-server profile remain outside the completed local read core.
