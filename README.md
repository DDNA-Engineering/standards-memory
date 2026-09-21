# Standards Memory

Standards Memory is an offline-first, source-linked evidence engine for technical standards. The deterministic local core validates and installs authorized packs, resolves exact editions, searches lexical indexes, retrieves dependency-complete evidence, assembles bounded context, exhaustively traverses declared obligations, and compares editions without silently changing project baselines.

It is intentionally not a chat assistant, compliance authority, PDF compiler, public standards registry, or DDNA dependency. Only synthetic example content is included.

## Run the vertical slice

Use Python 3.11 or newer from the repository root:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
$root = Join-Path $PWD '.standards-memory'
python -m standards_memory --db "$root\memory.db" --store "$root\objects" verify-pack examples\packs\fictional-adapter-v1
python -m standards_memory --db "$root\memory.db" --store "$root\objects" install examples\packs\fictional-adapter-v1 --policy examples\policies\local-synthetic.json
python -m standards_memory --db "$root\memory.db" --store "$root\objects" resolve EXAMPLE-SPEC-100A --edition example:spec-100:2025-a --principal local-user
```

Use the returned `package_digest` as the immutable pin:

```powershell
python -m standards_memory --db "$root\memory.db" --store "$root\objects" get-clause <package-digest> 4.2.1 --principal local-user
```

Every command emits machine-readable JSON. Failures use a typed `error.code` and a nonzero exit status. Query commands perform no network calls and never activate or import content.

The six read operations are available as `search`, `resolve`, `get-clause`, `build-context`, `enumerate-obligations`, and `diff-editions`. Administrative `install` and `revoke` commands remain separate. Run `python -m standards_memory --help` for their arguments.

## Evidence boundaries

- A package digest identifies validated content bytes through its inventory.
- An edition ID identifies a technical edition and is not a package digest.
- Pack rights files are provenance claims. They do not authorize installation or serving.
- Local authorization comes from an operator-supplied policy and is rechecked on every query.
- Returned clause text remains distinct from derived completeness metadata.
- Obligation roles are explicit derivations; legacy records are never silently reclassified.
- Enumeration cursors bind the immutable package, scope, principal, and active policy fingerprint.
- The implementation verifies stored source hashes and exact quoted text at serving time.

See [START_HERE.md](START_HERE.md), [docs/PRD.md](docs/PRD.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and [GOVERNANCE.md](GOVERNANCE.md).
