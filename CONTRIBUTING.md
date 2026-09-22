# Contributing

Contributions must preserve exact source evidence, immutable package/edition identity, explicit uncertainty, rights-policy separation, and read-only query behavior.

Before opening a pull request:

1. Use synthetic or demonstrably redistributable fixtures only. Do not submit proprietary standards text, private customer data, credentials, or controlled information.
2. Update contracts, requirements, examples, migrations, and affected tests together when semantics change.
3. Install `.[mcp,compiler,contract]`, run `python -m pip check`, then run `python scripts/validate_contracts.py`, `python -m unittest discover -s tests -v`, and `python scripts/run_benchmark.py benchmarks/synthetic-contract-v1.json` with `PYTHONPATH=src`. Acquire the exact backend declared by `build-toolchain.lock.json` into `build/toolchain-cache`, run `python scripts/validate_installed_wheel.py --build-tool-dir build/toolchain-cache --output-dir build/ci-wheel`, build `build/standardsforge-starter.zip` from that retained wheel directory, exercise it, generate the deterministic release evidence, and run its offline verifier.
4. Describe requirements addressed, observed tests, fixture digests, limitations, security/rights effects, and migration/rollback impact.
5. Sign every commit using the Developer Certificate of Origin convention: `git commit -s`.

Security reports belong in GitHub's private vulnerability reporting flow described in `SECURITY.md`, not in public issues.
