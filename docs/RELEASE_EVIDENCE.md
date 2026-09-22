# Release evidence and attestation verification

StandardsForge separates local digest consistency from authenticated producer identity.

The release evidence generator emits deterministic CycloneDX 1.7 SBOMs and unsigned in-toto Statement v1 documents using the SLSA provenance v1 predicate shape. The closed evidence index binds the exact wheel, starter archive, wheel provenance, current source inventory, dependency lock, build-tool lock, and expected GitHub repository/workflow identity. Its local verification result can establish byte and cross-document consistency without a network connection. It deliberately reports `signature_status: not_present` and `authenticity_verified: false`.

The protected `main` push job is the only workflow with identity-token and attestation permissions. After all matrix checks succeed, it independently rebuilds and exercises the wheel and starter, regenerates and verifies the local evidence from a clean exact commit, and invokes the immutable pinned GitHub attestation action separately for the wheel and starter SBOMs. A pull-request job never receives identity-token permission.

## Build and verify local evidence

Acquire the exact backend artifact declared by `build-toolchain.lock.json`, then perform the network-disabled build:

```powershell
python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: --dest build/toolchain-cache setuptools==84.0.0
python scripts/validate_installed_wheel.py --build-tool-dir build/toolchain-cache --output-dir build/release-wheel
python scripts/build_starter_distribution.py --wheel-dir build/release-wheel --output build/standardsforge-starter.zip
python scripts/validate_starter_distribution.py build/standardsforge-starter.zip
python scripts/release_evidence.py generate --wheel-dir build/release-wheel --starter build/standardsforge-starter.zip --output build/release-evidence --repository OWNER/REPOSITORY --repository-uri https://github.com/OWNER/REPOSITORY --require-clean-vcs
python scripts/verify_release_evidence.py build/release-evidence --wheel-dir build/release-wheel --starter build/standardsforge-starter.zip --require-exact-commit
```

The acquisition command uses the network; the locked build and evidence verifier do not. The build refuses a backend wheel whose filename, size, or SHA-256 differs from the lock. The core SBOM declares an explicit empty required-runtime dependency graph and labels the optional compiler, contract, and MCP profiles as not installed.

## Verify a signed release online

For each downloaded subject, require the expected repository identity. A successful command is evidence of verification; merely possessing a bundle is not.

```powershell
gh attestation verify PATH/TO/ARTIFACT -R OWNER/REPOSITORY --signer-workflow OWNER/REPOSITORY/.github/workflows/ci.yml --source-ref refs/heads/main --predicate-type https://cyclonedx.org/bom
```

Also run the local release-evidence verifier against the wheel, starter, and sidecars. The two checks answer different questions: the local verifier establishes digest consistency, while GitHub attestation verification establishes the signed workflow identity and predicate binding.

## Prepare and perform offline signature verification

On an online transfer machine, download each subject's attestation bundle and current trusted roots:

```powershell
gh attestation download PATH/TO/ARTIFACT -R OWNER/REPOSITORY
gh attestation trusted-root > trusted_root.jsonl
```

Transfer the artifact, downloaded JSONL bundle, trusted-root file, GitHub CLI, and deterministic release-evidence directory to the offline system. Then verify both the expected repository identity and the exact local subject digest:

```powershell
gh attestation verify PATH/TO/ARTIFACT -R OWNER/REPOSITORY --signer-workflow OWNER/REPOSITORY/.github/workflows/ci.yml --source-ref refs/heads/main --predicate-type https://cyclonedx.org/bom --bundle PATH/TO/ATTESTATION.jsonl --custom-trusted-root trusted_root.jsonl
python scripts/verify_release_evidence.py PATH/TO/release-evidence --wheel-dir PATH/TO/release-wheel --starter PATH/TO/standardsforge-starter.zip --require-exact-commit
```

Refresh trusted roots whenever new signed material enters the offline environment. An old root file cannot reveal later revocation or key rotation. Do not describe local statements, downloaded bundles, or checksum files as signed or verified until the applicable verification command succeeds.
