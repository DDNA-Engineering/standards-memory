# Machine contracts

The JSON Schemas describe the public 0.1.0 pack manifest, inventory, records, rights claims, and trusted local policy shapes. Runtime validation is deliberately stricter where filesystem evidence is required: it verifies inventory closure, byte counts, SHA-256 values, source quote presence, edition consistency, dependency targets, and data-only paths.

`query-operations.json` identifies the six read operations and their authority/pinning invariants. `mcp-tools.json` fixes the local stdio MCP surface, trusted startup-principal boundary, and exact caller-visible arguments. Returned packet details remain pre-release and are locked by the acceptance tests; no HTTP adapter is implemented.
