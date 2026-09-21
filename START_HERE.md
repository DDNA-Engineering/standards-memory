# Start here

StandardsForge is a standalone, source-first standards compiler and evidence engine. Host applications are integration consumers, not core dependencies.

The implementation order is M0 contracts and rights, M1 deterministic local core, M2 compilation and evidence, M3 measured identification/reading improvement, and M4 shared-server integration. The current repository implements the deterministic M1 read core and local MCP boundary in `TASK-001` through `TASK-003`.

The first slice installs a fictional data-only pack, resolves its exact identity, retrieves a clause with its governing note, and returns a source-verifiable packet. It repeats without networking and demonstrates that installing a second fictional edition does not mutate evidence from the first pinned edition.

The second slice completes the six read operations with multi-clause context assembly, exhaustive obligation traversal over explicit classifications, and dependency-sensitive edition comparison. Its cursors are signed, expire, and bind the package, scope, principal, and current policy fingerprint.

The third slice exposes only those six operations through a local stdio MCP adapter. The operator binds one trusted principal at server startup; tool callers cannot select identity or invoke administrative operations. MCP SDK telemetry middleware is removed, and both in-memory socket-denial tests and a real stdio subprocess test cover the boundary.

Working commands:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m pip install -e ".[mcp]"
python scripts/validate_contracts.py
python -m unittest discover -s tests -v
python -m standardsforge --help
python -m standardsforge.mcp_server --help
```

These checks cover synthetic packs and the local deterministic path. They do not establish real-PDF extraction fidelity, production performance, tenant isolation, shared-server security, or standards applicability.

## Project rename

The distribution, Python import, and CLI are now `standardsforge`; the MCP command is `standardsforge-mcp`. Reinstall the editable package after updating a checkout, and update host launch commands and Python imports. The exported classes are `StandardsForgeService` and `StandardsForgeError`.

New CLI invocations use `.standardsforge/` for local state. To continue using an existing store, pass `--db .standards-memory/memory.db --store .standards-memory/objects` before the CLI subcommand, or as MCP server arguments. The rename does not move or rewrite existing evidence.

Existing fixture publisher statements, schema identifiers, requirement IDs, and historical validation records retain their original identities. These are provenance and contract references, not current product branding.
