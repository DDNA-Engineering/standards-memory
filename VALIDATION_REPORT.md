# Validation report

Date: 2026-09-21

Scope: `TASK-001` through `TASK-003` deterministic local evidence engine and stdio MCP adapter

Repository state at validation: local uncommitted development working tree

## StandardsForge rename verification

The project was renamed locally to StandardsForge on 2026-09-21. The distribution and Python module are `standardsforge`; the console commands are `standardsforge` and `standardsforge-mcp`. The README uses the new name and contains no emojis.

After the rename, editable installation succeeded, all 18 existing tests passed, and contract validation returned the same two fixture digests recorded below. Both renamed console entry points returned help successfully, and both README demo blocks completed successfully. README file links and heading anchors were checked. The old editable distribution was removed from the local virtual environment.

Historical input names, build results, schema IDs, and pack provenance below retain their original identities. Existing evidence was not rewritten. New default local state is stored under `.standardsforge/`; `START_HERE.md` describes how to point the renamed commands at an existing store.

## Requirements addressed

Twenty bounded requirements are represented in `docs/requirements/requirements.json`, including identity/pinning, exact evidence, dependency context, pack contracts, all six read operations, exhaustive scoped traversal, edition comparison, rights-policy separation, offline operation, continuation binding, rebuildable indexes, and completeness dimensions. `TASK-003` applies the existing read-operation, authorization, offline, administration-separation, continuation, budget, and completeness requirements to the local MCP boundary.

## Input provenance

The attached documents were treated as proposed product/build guidance and were not treated as evidence that a runtime already existed.

| Input | SHA-256 |
|---|---|
| `AGENTS.md` | `c634916cf29b1b90e0d04f2cf520483826bdffad6f0417c2bd3560c0f27ba140` |
| `START_HERE.md` | `bf87a035ff196943a7201800743945dca815b127f22790b54fa4d7d2f6160b38` |
| `Standards_Memory_PRD.docx` | `5a346b0660f4904422c7df13426c7e9f6b73c0397b2daae389a8028a47ae308f` |
| `Standards_Memory_Architecture_and_ADRs.docx` | `897b35823f1e3d0505b873f6f80b2e162295ef5b7e1aa749ccf3aa76acdd1aeb` |

## Commands and observed results

Environment: Windows, Python 3.12.14, SQLite 3.53.1, setuptools 84.0.0, MCP Python SDK 2.2.0.

```powershell
python -m pip install -e ".[mcp]"
```

Observed: exit 0; the editable package and exact `mcp==2.2.0` optional dependency installed into an isolated local virtual environment. `python -m pip check` subsequently reported no broken requirements.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python scripts/validate_contracts.py
```

Observed: exit 0. Seven machine contract documents parsed; 20 task requirements resolved across `TASK-001` through `TASK-003`; both three-record fixture packs validated.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m unittest discover -s tests -v
```

Observed: exit 0; 18 tests passed in 2.196 seconds. The suite exercised authorized install, all six core read operations with sockets denied, multi-clause dependency deduplication, signed policy-bound pagination, dependency-sensitive edition comparison, schema v1-to-v2 migration, ZIP portability, edition pin stability, inventory tampering, untracked executable content, rights-policy denial, atomic byte-budget refusal, revocation recheck, and authorization-scoped FTS5 search. Four MCP tests additionally proved the exact six-tool schema, read-only/closed-world annotations, absence of caller-selected principal/admin inputs, disabled server telemetry middleware, all-operation result parity with socket creation denied, typed non-leaking denial, and a real stdio subprocess round trip.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m compileall -q src tests scripts
```

Observed: exit 0.

```powershell
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir <temporary-directory>
```

Observed: exit 0; `standards_memory-0.1.0a1-py3-none-any.whl` built successfully and contained the MCP server module plus both console entry points. The temporary artifact was removed after validation.

The pre-publication credential-pattern and absolute-local-path scans passed with zero matches.

## Fixture digests

| Pack | Edition | Package digest |
|---|---|---|
| `example.vehicle-adapter.1.0` | `example:spec-100:2025-a` | `3c27ee682401e154425f806614a800d744f472f1be41e9e412f9214460f12117` |
| `example.vehicle-adapter.2.0` | `example:spec-100:2026-b` | `ad93262351fbf1138f841e7f964fca95ffe7c5139778996ec851bdd91df33ad3` |

## Security and rights effects

Pack rights records are preserved as claims and cannot authorize installation or serving. An external operator policy must authorize the exact pack ID and content class; its fingerprint is stored with a digest-bound principal grant. Reads check active authorization before access and again before returning an evidence packet. Query operations do not import, activate, publish, execute, download, invoke models, or create sockets.

The MCP adapter accepts its principal only from trusted process startup configuration and exposes no administrative tool. It runs only over stdio, creates no listener, and removes the pinned SDK's OpenTelemetry middleware before accepting calls. Expected domain failures are marked as MCP errors and carry the existing typed JSON error envelope without returning the bound principal.

Data-only suffix restrictions, inventory closure, byte counts, hashes, source quote checks, dependency resolution, path traversal checks, symlink denial, and bounded archive size/file counts are enforced during validation.

## Migration and rollback

The local database is schema version 2. A tested v1-to-v2 migration adds explicit derivation/statement-role fields and marks legacy rows `unknown`/`unreviewed`; it never invents obligation classifications. Installation is content-addressed and metadata activation is transactional. To roll back a development instance, stop using the local CLI and remove only its explicitly selected database/object directory. Grant revocation provides immediate logical denial without deleting evidence bytes.

## Limitations

- Synthetic text fixtures only; no real PDF, table, figure, OCR, or visual-fidelity qualification.
- The six read operations are implemented in the local library, CLI, and stdio MCP adapter; no HTTP transport or shared-server profile is implemented.
- No reader UI, compilation worker, model adapter, PostgreSQL profile, shared tenancy, performance benchmark, SBOM, or signed release artifact.
- Exact quote presence is not proof of PDF fidelity, and returned evidence is not an applicability, compliance, or human approval decision.
