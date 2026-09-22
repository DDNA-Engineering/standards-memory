from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema.validators import validator_for


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from build_prepared_distribution import (  # noqa: E402
    FIXED_ZIP_TIME,
    _load_wheel_provenance,
    _validate_release_wheel,
)
from standardsforge.pack import validate_pack_directory  # noqa: E402
from standardsforge.policy import authorize_install, load_policy  # noqa: E402
from validate_installed_wheel import _source_inventory, _wheel_source_paths  # noqa: E402


SOURCE_DATE_EPOCH = 1767225600
PROFILE = "synthetic_contract_starter"
PRODUCT = "StandardsForge synthetic starter"
QUALIFICATION = "fictional_examples_for_onboarding_and_integration_only"
PRINCIPAL = "local-user"
VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
PACK_INPUTS = (
    (ROOT / "examples" / "packs" / "fictional-adapter-v1", "packs/fictional-adapter-v1"),
    (ROOT / "examples" / "packs" / "fictional-adapter-v2", "packs/fictional-adapter-v2"),
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Expected UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected one JSON object: {path}")
    return value


def _canonical_path(value: str) -> str:
    if not value or "\\" in value or value.startswith("/") or ":" in value:
        raise ValueError(f"Unsafe starter path: {value}")
    path = PurePosixPath(value)
    if path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Non-canonical starter path: {value}")
    return value


def _payload(source: Path, destination: str) -> tuple[Path, str]:
    destination = _canonical_path(destination)
    if not source.is_file() or source.is_symlink():
        raise ValueError(f"Starter input is missing or unsafe: {source}")
    return source, destination


def _write_member(archive: zipfile.ZipFile, source: Path, destination: str) -> None:
    info = zipfile.ZipInfo(destination, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.extra = b""
    info.comment = b""
    with source.open("rb") as input_stream, archive.open(info, "w", force_zip64=True) as output_stream:
        shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)


def _write_bytes(archive: zipfile.ZipFile, value: bytes, destination: str) -> None:
    info = zipfile.ZipInfo(destination, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.extra = b""
    info.comment = b""
    archive.writestr(info, value)


def _validate_policy_and_packs() -> tuple[list[dict[str, Any]], list[tuple[Path, str]]]:
    policy_path = ROOT / "examples" / "policies" / "local-synthetic.json"
    policy = load_policy(policy_path)
    packs = [validate_pack_directory(path) for path, _ in PACK_INPUTS]
    if policy.principal_id != PRINCIPAL or not policy.allow_admin_install or not policy.allow_serve:
        raise ValueError("The starter policy must permit install and serving for local-user.")
    if policy.allowed_pack_ids != frozenset(pack.manifest["pack_id"] for pack in packs):
        raise ValueError("The starter policy must exactly authorize the two starter packs.")
    if policy.allowed_content_classes != frozenset({"synthetic"}):
        raise ValueError("The starter policy must authorize only synthetic content.")
    for pack in packs:
        authorize_install(policy, pack)
    if len({pack.package_digest for pack in packs}) != 2 or len({pack.manifest["edition_id"] for pack in packs}) != 2:
        raise ValueError("Starter pack digests and editions must be unique.")

    declarations: list[dict[str, Any]] = []
    payloads: list[tuple[Path, str]] = []
    for pack, (source_root, destination_root) in zip(packs, PACK_INPUTS):
        declarations.append(
            {
                "path": destination_root,
                "pack_id": pack.manifest["pack_id"],
                "package_digest": pack.package_digest,
                "document_family_id": pack.manifest["document_family_id"],
                "edition_id": pack.manifest["edition_id"],
                "representation": pack.manifest.get("representation", "curated_records"),
                "content_class": pack.rights["content_class"],
            }
        )
        for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
            relative = source.relative_to(source_root).as_posix()
            payloads.append(_payload(source, f"{destination_root}/{relative}"))
    declarations.sort(key=lambda item: item["package_digest"])
    return declarations, payloads


def _validate_exact_wheel_provenance(provenance: dict[str, Any]) -> None:
    expected = _source_inventory()
    if provenance["source_files"] != expected:
        raise ValueError("Wheel provenance is not the exact current source inventory.")
    if provenance["wheel_source_paths"] != _wheel_source_paths(expected):
        raise ValueError("Wheel provenance misclassifies wheel source inputs.")
    if provenance["release_metadata_paths"] != ["uv.lock"]:
        raise ValueError("Wheel provenance misclassifies release metadata inputs.")
    lock = ROOT / "build-toolchain.lock.json"
    if provenance["build_tool"]["lock_sha256"] != _sha256(lock):
        raise ValueError("Wheel provenance build-tool lock does not match the current lock.")
    if provenance["authentication"] != "none":
        raise ValueError("Local wheel provenance must not claim authentication.")


def discover_wheel_inputs(directory: Path) -> tuple[Path, Path]:
    directory = directory.resolve()
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Starter wheel directory is missing or unsafe.")
    wheels = sorted(directory.glob("standardsforge-*.whl"))
    provenances = sorted(directory.glob("standardsforge-*.whl.provenance.json"))
    if len(wheels) != 1 or len(provenances) != 1:
        raise ValueError("Starter wheel directory must contain exactly one wheel and one provenance file.")
    expected_provenance = directory / f"{wheels[0].name}.provenance.json"
    if provenances[0] != expected_provenance or wheels[0].is_symlink() or provenances[0].is_symlink():
        raise ValueError("Starter wheel and provenance filenames do not form one exact safe pair.")
    return wheels[0], provenances[0]


def _manifest(
    version: str,
    wheel: Path,
    wheel_provenance: Path,
    packages: list[dict[str, Any]],
    payloads: list[tuple[Path, str]],
) -> dict[str, Any]:
    first_digest = next(
        item["package_digest"] for item in packages if item["pack_id"] == "example.vehicle-adapter.1.0"
    )
    policy_path = ROOT / "examples" / "policies" / "local-synthetic.json"
    return {
        "schema_version": "0.1.0",
        "product": PRODUCT,
        "version": version,
        "profile": PROFILE,
        "qualification": QUALIFICATION,
        "build": {
            "archive_source_date_epoch": SOURCE_DATE_EPOCH,
            "fixed_zip_datetime": "2026-01-01T00:00:00Z",
            "archive_method": "zip_stored",
            "wheel_path": f"wheel/{wheel.name}",
            "wheel_bytes": wheel.stat().st_size,
            "wheel_sha256": _sha256(wheel),
            "wheel_provenance_path": "provenance/wheel-build.json",
            "wheel_provenance_sha256": _sha256(wheel_provenance),
            "reproducible_clean_wheel_builds": 2,
        },
        "install": {
            "minimum_python": "3.11",
            "principal_id": PRINCIPAL,
            "policy_path": "policies/local-synthetic.json",
            "policy_sha256": _sha256(policy_path),
            "state_directory": ".standardsforge",
            "venv_directory": ".venv",
            "receipt_path": ".standardsforge/starter-receipt.json",
            "setup_path": "setup.py",
            "launcher_path": "run.py",
            "network_dependency_resolution": "disabled",
            "smokes": {
                "doctor": "full_integrity",
                "discovery": {
                    "query": "axial load",
                    "query_mode": "all_terms",
                    "package_digest": first_digest,
                    "expected_record_ids": ["clause-4.2.1"],
                },
                "exact_context": {
                    "record_id": "clause-4.2.1",
                    "required_context_record_ids": ["note-4.2.1-1"],
                },
            },
        },
        "packages": packages,
        "claims": {
            "real_document_quality": False,
            "project_applicability": False,
            "compliance": False,
            "approval": False,
            "prepared_public_corpus_replacement": False,
        },
        "files": [
            {"path": destination, "bytes": source.stat().st_size, "sha256": _sha256(source)}
            for source, destination in sorted(payloads, key=lambda item: item[1])
        ],
    }


def _build_once(path: Path, prefix: str, manifest: dict[str, Any], payloads: list[tuple[Path, str]]) -> None:
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.comment = b""
        _write_bytes(archive, manifest_bytes, prefix + "bundle-manifest.json")
        for source, destination in sorted(payloads, key=lambda item: item[1]):
            _write_member(archive, source, prefix + destination)


def validate_starter_archive(archive_path: Path) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            if archive.comment:
                raise ValueError("Starter archive comments are forbidden.")
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if not infos or len(names) != len(set(names)) or len({name.casefold() for name in names}) != len(names):
                raise ValueError("Starter archive members are empty, duplicate, or case-colliding.")
            prefixes = {name.split("/", 1)[0] for name in names}
            if len(prefixes) != 1:
                raise ValueError("Starter archive must have exactly one root directory.")
            prefix = next(iter(prefixes)) + "/"
            if not prefix.startswith("standardsforge-starter-"):
                raise ValueError("Starter archive root is invalid.")
            for info in infos:
                _canonical_path(info.filename)
                if (
                    info.date_time != FIXED_ZIP_TIME
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.create_system != 3
                    or (info.external_attr >> 16) != 0o100644
                    or info.extra
                    or info.comment
                    or info.flag_bits & 0x1
                ):
                    raise ValueError("Starter archive member metadata is not canonical.")
            manifest_name = prefix + "bundle-manifest.json"
            try:
                manifest = json.loads(archive.read(manifest_name))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Starter manifest is missing or invalid.") from exc
            schema = _load_json(ROOT / "contracts" / "starter-bundle.schema.json")
            validator_class = validator_for(schema)
            validator_class.check_schema(schema)
            validator_class(schema).validate(manifest)
            if prefix != f"standardsforge-starter-{manifest['version']}/":
                raise ValueError("Starter archive root does not match its version.")
            expected = {manifest_name}
            for item in manifest["files"]:
                relative = _canonical_path(item["path"])
                name = prefix + relative
                if name in expected:
                    raise ValueError("Starter inventory path is duplicated.")
                expected.add(name)
                try:
                    value = archive.read(name)
                except KeyError as exc:
                    raise ValueError(f"Starter archive is missing {relative}.") from exc
                if len(value) != item["bytes"] or _sha256_bytes(value) != item["sha256"]:
                    raise ValueError(f"Starter inventory validation failed: {relative}")
            if set(names) != expected:
                raise ValueError("Starter archive contains unlisted or missing files.")

            with tempfile.TemporaryDirectory(prefix="standardsforge-starter-reopen-") as temporary:
                extracted = Path(temporary) / prefix.removesuffix("/")
                extracted.mkdir()
                for item in manifest["files"]:
                    target = extracted.joinpath(*PurePosixPath(item["path"]).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(prefix + item["path"]))
                (extracted / "bundle-manifest.json").write_bytes(archive.read(manifest_name))
                for declaration in manifest["packages"]:
                    pack = validate_pack_directory(extracted / declaration["path"])
                    if (
                        pack.package_digest != declaration["package_digest"]
                        or pack.manifest["pack_id"] != declaration["pack_id"]
                        or pack.manifest["edition_id"] != declaration["edition_id"]
                        or pack.manifest.get("representation", "curated_records") != declaration["representation"]
                        or pack.rights["content_class"] != declaration["content_class"]
                    ):
                        raise ValueError("Bundled starter pack identity is inconsistent.")
                policy = load_policy(extracted / manifest["install"]["policy_path"])
                if policy.principal_id != manifest["install"]["principal_id"]:
                    raise ValueError("Bundled starter policy principal is inconsistent.")
                for declaration in manifest["packages"]:
                    authorize_install(policy, validate_pack_directory(extracted / declaration["path"]))
                wheel = extracted / manifest["build"]["wheel_path"]
                provenance_path = extracted / manifest["build"]["wheel_provenance_path"]
                _validate_release_wheel(wheel, manifest["version"])
                provenance, provenance_digest = _load_wheel_provenance(
                    provenance_path, wheel, manifest["version"]
                )
                _validate_exact_wheel_provenance(provenance)
                if provenance_digest != manifest["build"]["wheel_provenance_sha256"]:
                    raise ValueError("Bundled wheel provenance digest is inconsistent.")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("Starter archive could not be opened.") from exc
    return manifest


def build_starter_distribution(
    wheel: Path,
    wheel_provenance: Path,
    output: Path,
) -> dict[str, Any]:
    wheel = wheel.resolve()
    wheel_provenance = wheel_provenance.resolve()
    output = output.resolve()
    checksum = output.with_suffix(output.suffix + ".sha256")
    if output.exists() or checksum.exists():
        raise ValueError("Starter output or checksum already exists.")
    provenance = _load_json(wheel_provenance)
    version = provenance.get("version")
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("Wheel provenance has an unsafe or invalid version.")
    _validate_release_wheel(wheel, version)
    loaded_provenance, _ = _load_wheel_provenance(wheel_provenance, wheel, version)
    _validate_exact_wheel_provenance(loaded_provenance)

    packages, pack_payloads = _validate_policy_and_packs()
    static_root = ROOT / "scripts" / "starter_distribution"
    static_payloads = [
        _payload(static_root / "README.md", "README.md"),
        _payload(static_root / "CONTENT-NOTICE.md", "CONTENT-NOTICE.md"),
        _payload(static_root / "setup.py", "setup.py"),
        _payload(static_root / "run.py", "run.py"),
        _payload(ROOT / "LICENSE", "LICENSE"),
        _payload(ROOT / "contracts" / "starter-bundle.schema.json", "contracts/starter-bundle.schema.json"),
        _payload(ROOT / "contracts" / "starter-receipt.schema.json", "contracts/starter-receipt.schema.json"),
        _payload(ROOT / "examples" / "policies" / "local-synthetic.json", "policies/local-synthetic.json"),
        _payload(wheel, f"wheel/{wheel.name}"),
        _payload(wheel_provenance, "provenance/wheel-build.json"),
    ]
    payloads = [*static_payloads, *pack_payloads]
    destinations = [destination for _, destination in payloads]
    if len(destinations) != len(set(destinations)) or len(destinations) != len({value.casefold() for value in destinations}):
        raise ValueError("Starter payload paths are duplicate or case-colliding.")
    manifest = _manifest(version, wheel, wheel_provenance, packages, payloads)
    schema = _load_json(ROOT / "contracts" / "starter-bundle.schema.json")
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    validator_class(schema).validate(manifest)
    prefix = f"standardsforge-starter-{version}/"

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="standardsforge-starter-build-") as temporary:
        first = Path(temporary) / "first.zip"
        second = Path(temporary) / "second.zip"
        _build_once(first, prefix, manifest, payloads)
        _build_once(second, prefix, manifest, list(reversed(payloads)))
        validate_starter_archive(first)
        validate_starter_archive(second)
        if first.read_bytes() != second.read_bytes():
            raise ValueError("Two starter builds produced different bytes.")
        descriptor, partial_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".partial", dir=output.parent)
        os.close(descriptor)
        partial = Path(partial_name)
        try:
            shutil.copyfile(first, partial)
            os.replace(partial, output)
        finally:
            partial.unlink(missing_ok=True)

    archive_sha256 = _sha256(output)
    descriptor, checksum_partial_name = tempfile.mkstemp(prefix=f".{checksum.name}.", suffix=".partial", dir=checksum.parent)
    os.close(descriptor)
    checksum_partial = Path(checksum_partial_name)
    try:
        checksum_partial.write_text(f"{archive_sha256}  {output.name}\n", encoding="ascii", newline="\n")
        os.replace(checksum_partial, checksum)
    finally:
        checksum_partial.unlink(missing_ok=True)
    return {
        "ok": True,
        "profile": PROFILE,
        "version": version,
        "archive": str(output),
        "archive_bytes": output.stat().st_size,
        "archive_sha256": archive_sha256,
        "checksum": str(checksum),
        "wheel_sha256": manifest["build"]["wheel_sha256"],
        "package_digests": sorted(item["package_digest"] for item in packages),
        "reproducible_builds": 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the deterministic StandardsForge synthetic starter distribution.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wheel", type=Path)
    source.add_argument("--wheel-dir", type=Path)
    parser.add_argument("--wheel-provenance", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.wheel_dir is not None:
            if args.wheel_provenance is not None:
                raise ValueError("--wheel-provenance cannot be combined with --wheel-dir.")
            wheel, provenance = discover_wheel_inputs(args.wheel_dir)
        else:
            if args.wheel_provenance is None:
                raise ValueError("--wheel-provenance is required with --wheel.")
            wheel, provenance = args.wheel, args.wheel_provenance
        result = build_starter_distribution(wheel, provenance, args.output)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "starter_build_failed", "message": str(exc)}}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
