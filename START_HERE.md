# Start here

Standards Memory is a standalone, source-first standards compiler and evidence engine. DDNA is an integration consumer, not a core dependency.

The implementation order is M0 contracts and rights, M1 deterministic local core, M2 compilation and evidence, M3 measured identification/reading improvement, and M4 shared-server integration. The current repository implements the deterministic M1 read core in `TASK-001` and `TASK-002`.

The first slice installs a fictional data-only pack, resolves its exact identity, retrieves a clause with its governing note, and returns a source-verifiable packet. It repeats without networking and demonstrates that installing a second fictional edition does not mutate evidence from the first pinned edition.

The second slice completes the six read operations with multi-clause context assembly, exhaustive obligation traversal over explicit classifications, and dependency-sensitive edition comparison. Its cursors are signed, expire, and bind the package, scope, principal, and current policy fingerprint.

Working commands:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python scripts/validate_contracts.py
python -m unittest discover -s tests -v
python -m standards_memory --help
```

These checks cover synthetic packs and the local deterministic path. They do not establish real-PDF extraction fidelity, production performance, tenant isolation, public release approval, or standards applicability.
