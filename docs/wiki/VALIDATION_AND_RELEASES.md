# Validation and releases

Validation evidence must state exactly what ran and what it proves. Local source checks, installed-wheel acceptance, protected CI, publication, anonymous download, clean extraction, and end-user acceptance are separate facts.

## Standard local gate

From an isolated environment at the repository root:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m pip install -e ".[mcp,compiler,contract]"
python -m pip check
python scripts/validate_contracts.py
python -m unittest discover -s tests -v
python scripts/run_benchmark.py benchmarks/synthetic-contract-v1.json
python -m compileall -q src tests scripts
git diff --check
```

The benchmark qualifies the synthetic contracts and harness only. It does not establish real-document semantic quality, visual fidelity, applicability accuracy, or engineer-time savings.

## Installed wheel and starter

```powershell
python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: `
  --dest build/toolchain-cache setuptools==84.0.0

python scripts/validate_installed_wheel.py `
  --build-tool-dir build/toolchain-cache `
  --output-dir build/ci-wheel

python scripts/build_starter_distribution.py `
  --wheel-dir build/ci-wheel `
  --output build/standardsforge-starter.zip

python scripts/validate_starter_distribution.py `
  build/standardsforge-starter.zip
```

This gate proves the retained wheel installs and the synthetic starter is closed, deterministic, and executable outside the checkout. It does not qualify the prepared MIL-STD corpus.

## Release evidence

```powershell
python scripts/release_evidence.py generate `
  --wheel-dir build/ci-wheel `
  --starter build/standardsforge-starter.zip `
  --output build/release-evidence `
  --repository OWNER/REPOSITORY `
  --repository-uri https://github.com/OWNER/REPOSITORY

python scripts/verify_release_evidence.py build/release-evidence `
  --wheel-dir build/ci-wheel `
  --starter build/standardsforge-starter.zip
```

Local deterministic evidence proves digest and source consistency. It is unsigned and does not prove producer identity. Authenticated GitHub attestations are a separate protected-main result; follow [release evidence verification](../RELEASE_EVIDENCE.md).

## Prepared distribution acceptance

A prepared release is not complete until all of the following are separately observed:

1. the acquisition manifest verifies against the source snapshot;
2. corpus compilation is complete with zero hidden failures;
3. every pack archive and policy closes exactly;
4. the release wheel matches its reproducible build provenance;
5. the outer ZIP and checksum are deterministic and inventoried;
6. a clean extraction performs setup without source acquisition or PDF compilation;
7. full-integrity doctor succeeds;
8. exact resolve, search, and evidence retrieval succeed;
9. the published asset and checksum are anonymously downloadable;
10. protected CI and any signed attestation are reported separately.

Record current results and limits in the [validation report](../../VALIDATION_REPORT.md). Do not rewrite historical validation as if it ran against a newer commit or artifact.
