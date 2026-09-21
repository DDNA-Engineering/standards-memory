# Contributing

Contributions must preserve exact source evidence, immutable package/edition identity, explicit uncertainty, rights-policy separation, and read-only query behavior.

Before opening a pull request:

1. Use synthetic or demonstrably redistributable fixtures only. Do not submit proprietary standards text, private customer data, credentials, or controlled information.
2. Update contracts, requirements, examples, migrations, and affected tests together when semantics change.
3. Run `python scripts/validate_contracts.py` and `python -m unittest discover -s tests -v` with `PYTHONPATH=src`.
4. Describe requirements addressed, observed tests, fixture digests, limitations, security/rights effects, and migration/rollback impact.
5. Sign every commit using the Developer Certificate of Origin convention: `git commit -s`.

Security reports belong in GitHub's private vulnerability reporting flow described in `SECURITY.md`, not in public issues.
