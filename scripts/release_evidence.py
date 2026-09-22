from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from jsonschema.validators import validator_for

from build_prepared_distribution import _load_wheel_provenance, _validate_release_wheel
from build_starter_distribution import (
    _validate_exact_wheel_provenance,
    discover_wheel_inputs,
    validate_starter_archive,
)
from validate_installed_wheel import _source_inventory


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATE_EPOCH = 1767225600
FIXED_TIMESTAMP = "2026-01-01T00:00:00Z"
SBOM_NAMESPACE = uuid.UUID("c93c58c2-bd4e-58fb-a262-512cc8a6cc35")
EVIDENCE_FILENAMES = (
    "starter.cdx.json",
    "starter.intoto.json",
    "wheel.cdx.json",
    "wheel.intoto.json",
)
FINAL_FILENAMES = frozenset((*EVIDENCE_FILENAMES, "release-evidence.json"))
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path, name: str | None = None) -> dict[str, object]:
    return {
        "path": name or path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Expected UTF-8 JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected one JSON object: {path.name}")
    return value


def _schema(name: str) -> dict[str, Any]:
    return _load_json(ROOT / "contracts" / name)


def _validate_schema(value: dict[str, Any], name: str) -> None:
    schema = _schema(name)
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    validator_class(schema).validate(value)


def _inventory_sha256(source_files: list[dict[str, object]]) -> str:
    return _sha256_bytes(_canonical_bytes(source_files))


def _sanitize_repository_uri(value: str) -> str:
    value = value.strip()
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
        value = f"https://{host}/{path}"
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Repository identity must be a credential-free HTTPS URL.")
    parts = [part for part in parsed.path.removesuffix(".git").split("/") if part]
    if len(parts) != 2 or any(part in {".", ".."} for part in parts):
        raise ValueError("Repository identity must name one owner and repository.")
    return urlunsplit(("https", parsed.hostname.lower(), f"/{parts[0]}/{parts[1]}", "", ""))


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        shell=False,
    )


def _source_control(repository_uri: str | None, require_clean: bool) -> dict[str, object]:
    try:
        commit = _git("rev-parse", "--verify", "HEAD").stdout.strip().lower()
        if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise ValueError("Git returned an invalid commit identity.")
        status = _git("status", "--porcelain=v1", "--untracked-files=all").stdout
        clean = status == ""
        if require_clean and not clean:
            raise ValueError("Release attestation requires a clean Git worktree.")
        branch = _git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        remote = repository_uri
        if remote is None:
            observed = _git("remote", "get-url", "origin", check=False)
            remote = observed.stdout.strip() if observed.returncode == 0 else None
        result: dict[str, object] = {
            "kind": "git",
            "commit": commit,
            "worktreeState": "clean" if clean else "dirty",
            "binding": "exact_commit" if clean else "context_only",
        }
        if remote:
            result["repositoryUri"] = _sanitize_repository_uri(remote)
        if branch.returncode == 0:
            branch_name = branch.stdout.strip()
            if not branch_name or re.fullmatch(r"[A-Za-z0-9._/-]+", branch_name) is None:
                raise ValueError("Git returned an invalid branch identity.")
            result["ref"] = f"refs/heads/{branch_name}"
        return result
    except FileNotFoundError:
        if require_clean:
            raise ValueError("Release attestation requires Git source identity.") from None
        return {"kind": "unavailable", "worktreeState": "unavailable", "binding": "inventory_only"}
    except subprocess.CalledProcessError as exc:
        if require_clean:
            raise ValueError("Release attestation requires Git source identity.") from exc
        return {"kind": "unavailable", "worktreeState": "unavailable", "binding": "inventory_only"}


def _wheel_metadata(wheel: Path) -> tuple[str, list[str]]:
    try:
        with zipfile.ZipFile(wheel, "r") as archive:
            name = next(item for item in archive.namelist() if item.endswith(".dist-info/METADATA"))
            message = BytesParser(policy=policy.default).parsebytes(archive.read(name))
    except (OSError, zipfile.BadZipFile, KeyError, StopIteration) as exc:
        raise ValueError("The wheel package metadata is missing or invalid.") from exc
    version = message.get("Version")
    if not isinstance(version, str) or not version:
        raise ValueError("The wheel package version is missing.")
    requirements = [str(value) for value in message.get_all("Requires-Dist", [])]
    unconditional = [value for value in requirements if "; extra ==" not in value and "; extra !=" not in value]
    if unconditional:
        raise ValueError("The core wheel unexpectedly declares required runtime dependencies.")
    return version, requirements


def _component(
    *,
    component_type: str,
    name: str,
    version: str,
    digest: str,
    purl: str | None,
    apache_license: bool,
    properties: list[dict[str, str]],
) -> dict[str, object]:
    value: dict[str, object] = {
        "type": component_type,
        "bom-ref": f"urn:sha256:{digest}",
        "name": name,
        "version": version,
        "hashes": [{"alg": "SHA-256", "content": digest}],
        "properties": sorted(properties, key=lambda item: item["name"]),
    }
    if purl is not None:
        value["purl"] = purl
    if apache_license:
        value["licenses"] = [{"expression": "Apache-2.0"}]
    return value


def _sbom(
    *,
    subject_type: str,
    subject_name: str,
    version: str,
    subject_digest: str,
    wheel_name: str,
    wheel_digest: str,
    include_wheel: bool,
) -> dict[str, object]:
    wheel_component = _component(
        component_type="library",
        name="standardsforge",
        version=version,
        digest=wheel_digest,
        purl=f"pkg:pypi/standardsforge@{version}",
        apache_license=True,
        properties=[
            {"name": "standardsforge:dependency-profile", "value": "core"},
            {"name": "standardsforge:optional-profiles-not-installed", "value": "compiler,contract,mcp"},
            {"name": "standardsforge:required-runtime-dependency-count", "value": "0"},
        ],
    )
    root = (
        wheel_component
        if subject_type == "library"
        else _component(
            component_type="application",
            name=subject_name,
            version=version,
            digest=subject_digest,
            purl=None,
            apache_license=False,
            properties=[
                {"name": "standardsforge:dependency-profile", "value": "core"},
                {"name": "standardsforge:embedded-wheel", "value": wheel_name},
                {"name": "standardsforge:qualification", "value": "synthetic-contract-only"},
            ],
        )
    )
    root_ref = str(root["bom-ref"])
    wheel_ref = str(wheel_component["bom-ref"])
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": f"urn:uuid:{uuid.uuid5(SBOM_NAMESPACE, subject_digest)}",
        "version": 1,
        "metadata": {"timestamp": FIXED_TIMESTAMP, "component": root},
        "components": [wheel_component] if include_wheel else [],
        "dependencies": (
            [{"ref": root_ref, "dependsOn": [wheel_ref]}, {"ref": wheel_ref, "dependsOn": []}]
            if include_wheel
            else [{"ref": root_ref, "dependsOn": []}]
        ),
    }


def _descriptor(name: str, digest: str, media_type: str | None = None) -> dict[str, object]:
    if not name or "\\" in name or ":" in name or Path(name).name != name:
        raise ValueError("Release evidence descriptors require safe relative names.")
    value: dict[str, object] = {"name": name, "digest": {"sha256": digest}}
    if media_type is not None:
        value["mediaType"] = media_type
    return value


def _statement(
    *,
    build_type: str,
    profile_name: str,
    version: str,
    subject: dict[str, object],
    dependencies: list[dict[str, object]],
    byproducts: list[dict[str, object]],
    builder: dict[str, str],
    source_control: dict[str, object],
) -> dict[str, object]:
    dependencies = sorted(dependencies, key=lambda item: str(item["name"]))
    byproducts = sorted(byproducts, key=lambda item: str(item["name"]))
    build_definition = {
        "buildType": build_type,
        "externalParameters": {
            "profile": profile_name,
            "version": version,
            "sourceDateEpoch": SOURCE_DATE_EPOCH,
            "cleanBuildCount": 2,
        },
        "internalParameters": {
            "networkDependencyResolution": False,
            "sourceTreeMode": "inventoried-copy",
            "pythonHashSeed": "0",
        },
        "resolvedDependencies": dependencies,
    }
    invocation_digest = _sha256_bytes(_canonical_bytes({"subject": subject, "buildDefinition": build_definition}))
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [subject],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": build_definition,
            "runDetails": {
                "builder": {
                    "id": "https://standardsforge.dev/builders/self-reported-local/v1",
                    "version": builder,
                },
                "metadata": {"invocationId": f"urn:sha256:{invocation_digest}"},
                "byproducts": byproducts,
            },
            "standardsforgeAuthentication": {
                "mode": "none",
                "signed": False,
                "identityVerified": False,
                "claim": "offline_digest_consistency_only",
            },
            "standardsforgeSourceControl": source_control,
        },
    }


def _starter_manifest_identity(starter: Path) -> tuple[dict[str, Any], str]:
    manifest = validate_starter_archive(starter)
    with zipfile.ZipFile(starter, "r") as archive:
        names = [name for name in archive.namelist() if name.endswith("/bundle-manifest.json")]
        if len(names) != 1:
            raise ValueError("The starter must contain exactly one bundle manifest.")
        manifest_bytes = archive.read(names[0])
    if json.loads(manifest_bytes) != manifest:
        raise ValueError("The starter manifest identity is inconsistent.")
    return manifest, _sha256_bytes(manifest_bytes)


def _write_atomic(path: Path, value: object) -> None:
    path.write_bytes(_pretty_bytes(value))


def generate_release_evidence(
    wheel: Path,
    wheel_provenance: Path,
    starter: Path,
    output: Path,
    *,
    repository: str,
    repository_uri: str | None = None,
    require_clean_vcs: bool = False,
) -> dict[str, Any]:
    wheel = wheel.resolve()
    wheel_provenance = wheel_provenance.resolve()
    starter = starter.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("Release evidence output already exists.")
    if "/" not in repository or repository.startswith(("/", ".")):
        raise ValueError("Verification repository must use the owner/repository form.")

    version, _ = _wheel_metadata(wheel)
    _validate_release_wheel(wheel, version)
    provenance, provenance_digest = _load_wheel_provenance(wheel_provenance, wheel, version)
    _validate_exact_wheel_provenance(provenance)
    starter_manifest, starter_manifest_digest = _starter_manifest_identity(starter)
    if (
        starter_manifest["version"] != version
        or starter_manifest["build"]["wheel_sha256"] != _sha256(wheel)
        or starter_manifest["build"]["wheel_provenance_sha256"] != provenance_digest
    ):
        raise ValueError("The starter does not bind the supplied wheel and provenance.")

    source_files = provenance["source_files"]
    inventory_digest = _inventory_sha256(source_files)
    dependency_lock = ROOT / "uv.lock"
    build_tool_lock = ROOT / "build-toolchain.lock.json"
    source_control = _source_control(repository_uri, require_clean_vcs)
    wheel_digest = _sha256(wheel)
    starter_digest = _sha256(starter)
    wheel_sbom = _sbom(
        subject_type="library",
        subject_name="standardsforge",
        version=version,
        subject_digest=wheel_digest,
        wheel_name=wheel.name,
        wheel_digest=wheel_digest,
        include_wheel=False,
    )
    starter_sbom = _sbom(
        subject_type="application",
        subject_name="standardsforge-synthetic-starter",
        version=version,
        subject_digest=starter_digest,
        wheel_name=wheel.name,
        wheel_digest=wheel_digest,
        include_wheel=True,
    )
    _validate_schema(wheel_sbom, "cyclonedx-release-sbom.schema.json")
    _validate_schema(starter_sbom, "cyclonedx-release-sbom.schema.json")

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=parent))
    published = False
    try:
        wheel_sbom_path = temporary / "wheel.cdx.json"
        starter_sbom_path = temporary / "starter.cdx.json"
        _write_atomic(wheel_sbom_path, wheel_sbom)
        _write_atomic(starter_sbom_path, starter_sbom)
        builder = {
            "python": provenance["builder"]["python"],
            "pip": provenance["builder"]["pip"],
            "setuptools": "84.0.0",
        }
        wheel_statement = _statement(
            build_type="https://standardsforge.dev/buildtypes/wheel/v1",
            profile_name="core-wheel",
            version=version,
            subject=_descriptor(wheel.name, wheel_digest, "application/vnd.pypa.wheel"),
            dependencies=[
                _descriptor("source-inventory.json", inventory_digest, "application/json"),
                _descriptor(dependency_lock.name, _sha256(dependency_lock), "application/toml"),
                _descriptor(build_tool_lock.name, _sha256(build_tool_lock), "application/json"),
                _descriptor(
                    provenance["build_tool"]["artifact"]["filename"],
                    provenance["build_tool"]["artifact"]["sha256"],
                    "application/vnd.pypa.wheel",
                ),
            ],
            byproducts=[
                _descriptor(wheel_provenance.name, provenance_digest, "application/json"),
                _descriptor(wheel_sbom_path.name, _sha256(wheel_sbom_path), "application/vnd.cyclonedx+json"),
            ],
            builder=builder,
            source_control=source_control,
        )
        starter_statement = _statement(
            build_type="https://standardsforge.dev/buildtypes/starter/v1",
            profile_name="synthetic-starter",
            version=version,
            subject=_descriptor(starter.name, starter_digest, "application/zip"),
            dependencies=[
                _descriptor(wheel.name, wheel_digest, "application/vnd.pypa.wheel"),
                _descriptor(wheel_provenance.name, provenance_digest, "application/json"),
                _descriptor("bundle-manifest.json", starter_manifest_digest, "application/json"),
            ],
            byproducts=[
                _descriptor(starter_sbom_path.name, _sha256(starter_sbom_path), "application/vnd.cyclonedx+json"),
                _descriptor("bundle-manifest.json", starter_manifest_digest, "application/json"),
            ],
            builder=builder,
            source_control=source_control,
        )
        _validate_schema(wheel_statement, "release-build-statement.schema.json")
        _validate_schema(starter_statement, "release-build-statement.schema.json")
        _write_atomic(temporary / "wheel.intoto.json", wheel_statement)
        _write_atomic(temporary / "starter.intoto.json", starter_statement)
        evidence_files = [_file_record(temporary / name) for name in EVIDENCE_FILENAMES]
        index = {
            "schema_version": "0.1.0",
            "artifact_type": "standardsforge_release_evidence",
            "source": {
                "inventory_sha256": inventory_digest,
                "dependency_lock": _file_record(dependency_lock),
                "build_tool_lock": _file_record(build_tool_lock),
                "vcs": source_control,
            },
            "subjects": sorted(
                [_file_record(wheel), _file_record(starter)], key=lambda item: str(item["path"])
            ),
            "evidence_files": evidence_files,
            "verification_policy": {
                "repository": repository,
                "workflow": ".github/workflows/ci.yml",
                "branch": "refs/heads/main",
                "predicate_type": "https://cyclonedx.org/bom",
                "issuer": "https://token.actions.githubusercontent.com",
            },
            "authentication": {
                "local_evidence": "unsigned",
                "signature_status": "not_present",
                "authenticity_verified": False,
            },
        }
        _validate_schema(index, "release-evidence.schema.json")
        _write_atomic(temporary / "release-evidence.json", index)

        verification = validate_release_evidence(
            temporary, wheel, wheel_provenance, starter
        )

        os.mkdir(output)
        try:
            for name in EVIDENCE_FILENAMES:
                (temporary / name).replace(output / name)
            (temporary / "release-evidence.json").replace(output / "release-evidence.json")
            published = True
        finally:
            if not published:
                shutil.rmtree(output, ignore_errors=True)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    result = validate_release_evidence(output, wheel, wheel_provenance, starter)
    if result != verification:
        raise ValueError("Published release evidence differs from its validated staging set.")
    result["output"] = str(output)
    return result


def _assert_file_record(record: dict[str, object], path: Path) -> None:
    if record != _file_record(path, str(record.get("path", ""))):
        raise ValueError(f"Release evidence digest mismatch: {path.name}")


def _validate_sbom_cross_links(
    value: dict[str, Any], *, subject_digest: str, wheel_digest: str, starter: bool
) -> None:
    _validate_schema(value, "cyclonedx-release-sbom.schema.json")
    root = value["metadata"]["component"]
    if root["hashes"] != [{"alg": "SHA-256", "content": subject_digest}]:
        raise ValueError("SBOM root subject digest is inconsistent.")
    refs = [item["ref"] for item in value["dependencies"]]
    if len(refs) != len(set(refs)):
        raise ValueError("SBOM dependency references are duplicated.")
    known = {root["bom-ref"], *(item["bom-ref"] for item in value["components"])}
    if set(refs) != known or any(set(item["dependsOn"]) - known for item in value["dependencies"]):
        raise ValueError("SBOM dependency graph contains missing or dangling references.")
    if starter:
        if len(value["components"]) != 1 or value["components"][0]["hashes"][0]["content"] != wheel_digest:
            raise ValueError("Starter SBOM does not bind the exact wheel.")
    elif value["components"] or value["dependencies"] != [{"ref": root["bom-ref"], "dependsOn": []}]:
        raise ValueError("Core wheel SBOM must declare zero required runtime dependencies.")


def validate_release_evidence(
    evidence: Path,
    wheel: Path,
    wheel_provenance: Path,
    starter: Path,
    *,
    require_authenticity: bool = False,
    require_exact_commit: bool = False,
) -> dict[str, Any]:
    evidence = evidence.resolve()
    wheel = wheel.resolve()
    wheel_provenance = wheel_provenance.resolve()
    starter = starter.resolve()
    if not evidence.is_dir() or evidence.is_symlink():
        raise ValueError("Release evidence directory is missing or unsafe.")
    children = list(evidence.iterdir())
    if {item.name for item in children} != FINAL_FILENAMES or any(
        not item.is_file() or item.is_symlink() for item in children
    ):
        raise ValueError("Release evidence must contain the exact closed regular-file set.")

    index = _load_json(evidence / "release-evidence.json")
    _validate_schema(index, "release-evidence.schema.json")
    for record in index["evidence_files"]:
        _assert_file_record(record, evidence / record["path"])
    if [item["path"] for item in index["evidence_files"]] != list(EVIDENCE_FILENAMES):
        raise ValueError("Release evidence inventory is not canonical.")
    expected_subjects = sorted(
        [_file_record(wheel), _file_record(starter)], key=lambda item: str(item["path"])
    )
    if index["subjects"] != expected_subjects:
        raise ValueError("Release evidence subjects do not match the supplied artifacts.")

    version, _ = _wheel_metadata(wheel)
    provenance, provenance_digest = _load_wheel_provenance(wheel_provenance, wheel, version)
    _validate_exact_wheel_provenance(provenance)
    starter_manifest, starter_manifest_digest = _starter_manifest_identity(starter)
    wheel_digest = _sha256(wheel)
    starter_digest = _sha256(starter)
    if (
        starter_manifest["build"]["wheel_sha256"] != wheel_digest
        or starter_manifest["build"]["wheel_provenance_sha256"] != provenance_digest
    ):
        raise ValueError("Starter, wheel, and provenance cross-links are inconsistent.")
    if index["source"]["inventory_sha256"] != _inventory_sha256(provenance["source_files"]):
        raise ValueError("Release evidence source inventory digest is inconsistent.")
    _assert_file_record(index["source"]["dependency_lock"], ROOT / "uv.lock")
    _assert_file_record(index["source"]["build_tool_lock"], ROOT / "build-toolchain.lock.json")

    wheel_sbom = _load_json(evidence / "wheel.cdx.json")
    starter_sbom = _load_json(evidence / "starter.cdx.json")
    _validate_sbom_cross_links(wheel_sbom, subject_digest=wheel_digest, wheel_digest=wheel_digest, starter=False)
    _validate_sbom_cross_links(starter_sbom, subject_digest=starter_digest, wheel_digest=wheel_digest, starter=True)
    wheel_statement = _load_json(evidence / "wheel.intoto.json")
    starter_statement = _load_json(evidence / "starter.intoto.json")
    for statement in (wheel_statement, starter_statement):
        _validate_schema(statement, "release-build-statement.schema.json")
        if statement["predicate"]["standardsforgeSourceControl"] != index["source"]["vcs"]:
            raise ValueError("Build statement source-control identity is inconsistent.")
        if statement["predicate"]["standardsforgeAuthentication"]["signed"]:
            raise ValueError("Unsigned local evidence cannot claim a signature.")
    if wheel_statement["subject"] != [_descriptor(wheel.name, wheel_digest, "application/vnd.pypa.wheel")]:
        raise ValueError("Wheel build statement subject is inconsistent.")
    if starter_statement["subject"] != [_descriptor(starter.name, starter_digest, "application/zip")]:
        raise ValueError("Starter build statement subject is inconsistent.")
    wheel_dependencies = wheel_statement["predicate"]["buildDefinition"]["resolvedDependencies"]
    if not any(
        item["name"] == "source-inventory.json"
        and item["digest"]["sha256"] == index["source"]["inventory_sha256"]
        for item in wheel_dependencies
    ):
        raise ValueError("Wheel statement omits the exact source inventory.")
    wheel_byproducts = wheel_statement["predicate"]["runDetails"]["byproducts"]
    starter_dependencies = starter_statement["predicate"]["buildDefinition"]["resolvedDependencies"]
    starter_byproducts = starter_statement["predicate"]["runDetails"]["byproducts"]
    expected_links = (
        (wheel_byproducts, "wheel.cdx.json", _sha256(evidence / "wheel.cdx.json")),
        (wheel_byproducts, wheel_provenance.name, provenance_digest),
        (starter_dependencies, wheel.name, wheel_digest),
        (starter_dependencies, wheel_provenance.name, provenance_digest),
        (starter_dependencies, "bundle-manifest.json", starter_manifest_digest),
        (starter_byproducts, "starter.cdx.json", _sha256(evidence / "starter.cdx.json")),
    )
    for items, name, digest in expected_links:
        matches = [item for item in items if item["name"] == name]
        if len(matches) != 1 or matches[0]["digest"]["sha256"] != digest:
            raise ValueError(f"Build statement cross-link is inconsistent: {name}")

    vcs = index["source"]["vcs"]
    commit_verified = False
    if vcs["binding"] == "exact_commit":
        if vcs["worktreeState"] != "clean" or vcs["kind"] != "git":
            raise ValueError("Exact commit binding requires clean Git source state.")
        observed = _source_control(vcs.get("repositoryUri"), True)
        commit_verified = observed.get("commit") == vcs.get("commit")
        if not commit_verified:
            raise ValueError("The exact source commit could not be reproduced locally.")
    elif require_exact_commit:
        raise ValueError("Verification policy requires an exact clean source commit binding.")
    if require_authenticity:
        raise ValueError("The local release evidence is unsigned and cannot satisfy authenticity policy.")
    return {
        "ok": True,
        "integrity_verified": True,
        "source_inventory_verified": True,
        "commit_binding_verified": commit_verified,
        "signature_status": "not_present",
        "authenticity_verified": False,
        "network_used": False,
        "wheel_sha256": wheel_digest,
        "starter_sha256": starter_digest,
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or verify deterministic unsigned release evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate")
    verify = subparsers.add_parser("verify")
    for command in (generate, verify):
        command.add_argument("--wheel-dir", type=Path)
        command.add_argument("--wheel", type=Path)
        command.add_argument("--wheel-provenance", type=Path)
        command.add_argument("--starter", required=True, type=Path)
    generate.add_argument("--output", required=True, type=Path)
    generate.add_argument("--repository", required=True)
    generate.add_argument("--repository-uri")
    generate.add_argument("--require-clean-vcs", action="store_true")
    verify.add_argument("evidence", type=Path)
    verify.add_argument("--require-authenticity", action="store_true")
    verify.add_argument("--require-exact-commit", action="store_true")
    args = parser.parse_args(arguments)
    if args.wheel_dir is not None:
        if args.wheel is not None or args.wheel_provenance is not None:
            parser.error("--wheel-dir cannot be combined with --wheel or --wheel-provenance")
        wheel, wheel_provenance = discover_wheel_inputs(args.wheel_dir)
    else:
        if args.wheel is None or args.wheel_provenance is None:
            parser.error("provide --wheel-dir or both --wheel and --wheel-provenance")
        wheel, wheel_provenance = args.wheel, args.wheel_provenance
    if args.command == "generate":
        result = generate_release_evidence(
            wheel,
            wheel_provenance,
            args.starter,
            args.output,
            repository=args.repository,
            repository_uri=args.repository_uri,
            require_clean_vcs=args.require_clean_vcs,
        )
    else:
        result = validate_release_evidence(
            args.evidence,
            wheel,
            wheel_provenance,
            args.starter,
            require_authenticity=args.require_authenticity,
            require_exact_commit=args.require_exact_commit,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
