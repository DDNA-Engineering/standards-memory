from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


sys.dont_write_bytecode = True

MINIMUM_PYTHON = (3, 11)
MANIFEST_NAME = "bundle-manifest.json"
RECEIPT_RELATIVE = ".standardsforge/starter-receipt.json"
PARTIAL_RELATIVE = ".standardsforge/starter-setup-incomplete.json"
VENV_MARKER = ".standardsforge-starter-venv.json"
RUNTIME_ROOTS = {".standardsforge", ".venv"}
HEX64 = re.compile(r"[0-9a-f]{64}")


class StarterSetupError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StarterSetupError(message)


def _exact_keys(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{name} must be an object.")
    _require(set(value) == keys, f"{name} has missing or unknown fields.")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_bytes(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StarterSetupError(f"{name} is not valid UTF-8 JSON.") from exc
    _require(isinstance(value, dict), f"{name} must contain one JSON object.")
    return value


def _load_json(path: Path, name: str) -> dict[str, Any]:
    try:
        return _load_json_bytes(path.read_bytes(), name)
    except OSError as exc:
        raise StarterSetupError(f"{name} could not be read.") from exc


def _safe_relative(value: Any, name: str) -> str:
    _require(isinstance(value, str) and value, f"{name} must be a non-empty relative path.")
    _require("\\" not in value and not value.startswith("/") and ":" not in value, f"{name} is unsafe.")
    path = PurePosixPath(value)
    _require(path.as_posix() == value, f"{name} is not canonical POSIX text.")
    _require(all(part not in {"", ".", ".."} for part in path.parts), f"{name} is unsafe.")
    return value


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    checker = getattr(path, "is_junction", None)
    if checker is not None and checker():
        return True
    if os.name == "nt":
        try:
            attributes = os.lstat(path).st_file_attributes
        except (AttributeError, OSError):
            return False
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        directory = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
        return bool(attributes & reparse and attributes & directory)
    return False


def _safe_disk_path(root: Path, relative: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        _require(not _is_link_like(current), f"Bundle path is a symbolic link or junction: {relative}")
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise StarterSetupError(f"Bundle path escapes its root: {relative}") from exc
    return candidate


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    _exact_keys(
        manifest,
        {"schema_version", "product", "version", "profile", "qualification", "build", "install", "packages", "claims", "files"},
        "bundle manifest",
    )
    _require(manifest["schema_version"] == "0.1.0", "Unsupported bundle manifest version.")
    _require(manifest["product"] == "StandardsForge synthetic starter", "Unexpected bundle product.")
    _require(manifest["profile"] == "synthetic_contract_starter", "Unexpected bundle profile.")
    _require(manifest["qualification"] == "fictional_examples_for_onboarding_and_integration_only", "The bundle claim boundary is invalid.")
    _require(isinstance(manifest["version"], str) and manifest["version"], "Bundle version is required.")

    build = _exact_keys(
        manifest["build"],
        {"archive_source_date_epoch", "fixed_zip_datetime", "archive_method", "wheel_path", "wheel_bytes", "wheel_sha256", "wheel_provenance_path", "wheel_provenance_sha256", "reproducible_clean_wheel_builds"},
        "bundle build",
    )
    _require(build["archive_source_date_epoch"] == 1767225600, "Unexpected bundle source epoch.")
    _require(build["fixed_zip_datetime"] == "2026-01-01T00:00:00Z", "Unexpected bundle archive timestamp.")
    _require(build["archive_method"] == "zip_stored", "Unexpected bundle archive method.")
    _require(build["reproducible_clean_wheel_builds"] == 2, "The bundled wheel was not qualified by two builds.")
    _safe_relative(build["wheel_path"], "wheel_path")
    _safe_relative(build["wheel_provenance_path"], "wheel_provenance_path")
    _require(type(build["wheel_bytes"]) is int and build["wheel_bytes"] > 0, "Invalid wheel byte count.")
    _require(isinstance(build["wheel_sha256"], str) and HEX64.fullmatch(build["wheel_sha256"]) is not None, "Invalid wheel digest.")
    _require(isinstance(build["wheel_provenance_sha256"], str) and HEX64.fullmatch(build["wheel_provenance_sha256"]) is not None, "Invalid wheel provenance digest.")

    install = _exact_keys(
        manifest["install"],
        {"minimum_python", "principal_id", "policy_path", "policy_sha256", "state_directory", "venv_directory", "receipt_path", "setup_path", "launcher_path", "network_dependency_resolution", "smokes"},
        "bundle install",
    )
    expected_install = {
        "minimum_python": "3.11",
        "principal_id": "local-user",
        "policy_path": "policies/local-synthetic.json",
        "state_directory": ".standardsforge",
        "venv_directory": ".venv",
        "receipt_path": RECEIPT_RELATIVE,
        "setup_path": "setup.py",
        "launcher_path": "run.py",
        "network_dependency_resolution": "disabled",
    }
    for key, expected in expected_install.items():
        _require(install[key] == expected, f"Unexpected install field: {key}")
    _require(isinstance(install["policy_sha256"], str) and HEX64.fullmatch(install["policy_sha256"]) is not None, "Invalid policy digest.")
    _safe_relative(install["policy_path"], "policy_path")

    smokes = _exact_keys(install["smokes"], {"doctor", "discovery", "exact_context"}, "install smokes")
    _require(smokes["doctor"] == "full_integrity", "Doctor smoke must use full integrity.")
    discovery = _exact_keys(smokes["discovery"], {"query", "query_mode", "package_digest", "expected_record_ids"}, "discovery smoke")
    _require(discovery["query"] == "axial load" and discovery["query_mode"] == "all_terms", "Unexpected discovery smoke.")
    _require(isinstance(discovery["package_digest"], str) and HEX64.fullmatch(discovery["package_digest"]) is not None, "Invalid discovery package digest.")
    _require(isinstance(discovery["expected_record_ids"], list) and discovery["expected_record_ids"] and all(isinstance(value, str) and value for value in discovery["expected_record_ids"]), "Invalid discovery record expectations.")
    exact_context = _exact_keys(smokes["exact_context"], {"record_id", "required_context_record_ids"}, "exact-context smoke")
    _require(isinstance(exact_context["record_id"], str) and exact_context["record_id"], "Exact-context record is required.")
    _require(isinstance(exact_context["required_context_record_ids"], list) and exact_context["required_context_record_ids"] and all(isinstance(value, str) and value for value in exact_context["required_context_record_ids"]), "Exact-context dependencies are required.")

    packages = manifest["packages"]
    _require(isinstance(packages, list) and len(packages) == 2, "The starter must contain exactly two packs.")
    pack_ids: set[str] = set()
    digests: set[str] = set()
    editions: set[str] = set()
    for package in packages:
        package = _exact_keys(package, {"path", "pack_id", "package_digest", "document_family_id", "edition_id", "representation", "content_class"}, "package declaration")
        _safe_relative(package["path"], "package path")
        _require(package["representation"] == "curated_records" and package["content_class"] == "synthetic", "Starter packs must be synthetic curated records.")
        _require(isinstance(package["package_digest"], str) and HEX64.fullmatch(package["package_digest"]) is not None, "Invalid package digest.")
        _require(package["pack_id"] not in pack_ids and package["package_digest"] not in digests and package["edition_id"] not in editions, "Package identities must be unique.")
        pack_ids.add(package["pack_id"])
        digests.add(package["package_digest"])
        editions.add(package["edition_id"])
    _require(discovery["package_digest"] in digests, "Discovery smoke package is not bundled.")

    claims = _exact_keys(manifest["claims"], {"real_document_quality", "project_applicability", "compliance", "approval", "prepared_public_corpus_replacement"}, "bundle claims")
    _require(all(value is False for value in claims.values()), "The synthetic starter cannot assert engineering or corpus claims.")
    _require(isinstance(manifest["files"], list) and len(manifest["files"]) >= 10, "Bundle file inventory is incomplete.")


def _validate_policy(root: Path, manifest: dict[str, Any]) -> None:
    install = manifest["install"]
    policy_path = _safe_disk_path(root, install["policy_path"])
    _require(_sha256(policy_path) == install["policy_sha256"], "The policy does not match the manifest.")
    policy = _exact_keys(
        _load_json(policy_path, "starter policy"),
        {"policy_version", "policy_id", "principal_id", "allow_admin_install", "allow_serve", "allowed_pack_ids", "allowed_content_classes"},
        "starter policy",
    )
    expected_pack_ids = {item["pack_id"] for item in manifest["packages"]}
    _require(policy["policy_version"] == "0.1.0" and policy["policy_id"] == "local-synthetic-development", "Unexpected starter policy identity.")
    _require(policy["principal_id"] == install["principal_id"], "Starter policy principal mismatch.")
    _require(policy["allow_admin_install"] is True and policy["allow_serve"] is True, "Starter policy must permit install and serving.")
    _require(isinstance(policy["allowed_pack_ids"], list) and len(policy["allowed_pack_ids"]) == len(set(policy["allowed_pack_ids"])) and set(policy["allowed_pack_ids"]) == expected_pack_ids, "Starter policy pack scope mismatch.")
    _require(policy["allowed_content_classes"] == ["synthetic"], "Starter policy content class mismatch.")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _validate_pack(root: Path, declaration: dict[str, Any]) -> None:
    pack_root = _safe_disk_path(root, declaration["path"])
    _require(pack_root.is_dir(), "A declared starter pack is not a directory.")
    inventory = _exact_keys(_load_json(pack_root / "inventory.json", "pack inventory"), {"schema_version", "algorithm", "files"}, "pack inventory")
    _require(inventory["schema_version"] == "0.1.0" and inventory["algorithm"] == "sha256", "Unsupported pack inventory.")
    _require(isinstance(inventory["files"], list) and inventory["files"], "Pack inventory is empty.")
    observed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in inventory["files"]:
        entry = _exact_keys(entry, {"path", "sha256", "bytes"}, "pack inventory entry")
        relative = _safe_relative(entry["path"], "pack inventory path")
        _require(relative != "inventory.json" and relative not in seen, "Pack inventory path is duplicate or self-referential.")
        path = _safe_disk_path(pack_root, relative)
        _require(path.is_file() and type(entry["bytes"]) is int and entry["bytes"] >= 0, "Pack inventory entry is invalid.")
        _require(path.stat().st_size == entry["bytes"] and _sha256(path) == entry["sha256"], "Pack inventory bytes do not match.")
        seen.add(relative)
        observed.append({"path": relative, "sha256": entry["sha256"], "bytes": entry["bytes"]})
    actual = {
        path.relative_to(pack_root).as_posix()
        for path in pack_root.rglob("*")
        if path.is_file() and path.name != "inventory.json"
    }
    _require(actual == seen, "Pack directory and inventory do not close.")
    observed.sort(key=lambda item: item["path"])
    _require(_sha256_bytes(_canonical_json(observed)) == declaration["package_digest"], "Pack content digest does not match the manifest.")
    pack_manifest = _load_json(pack_root / "manifest.json", "pack manifest")
    rights = _load_json(pack_root / "rights.json", "pack rights")
    _require(pack_manifest.get("pack_id") == declaration["pack_id"], "Pack ID does not match the manifest.")
    _require(pack_manifest.get("document_family_id") == declaration["document_family_id"], "Pack family does not match the manifest.")
    _require(pack_manifest.get("edition_id") == declaration["edition_id"], "Pack edition does not match the manifest.")
    _require(pack_manifest.get("representation", "curated_records") == declaration["representation"], "Pack representation does not match the manifest.")
    _require(rights.get("content_class") == declaration["content_class"], "Pack content class does not match the manifest.")


def _validate_wheel(root: Path, manifest: dict[str, Any]) -> None:
    build = manifest["build"]
    wheel = _safe_disk_path(root, build["wheel_path"])
    provenance_path = _safe_disk_path(root, build["wheel_provenance_path"])
    _require(wheel.is_file() and wheel.stat().st_size == build["wheel_bytes"] and _sha256(wheel) == build["wheel_sha256"], "Bundled wheel identity mismatch.")
    _require(_sha256(provenance_path) == build["wheel_provenance_sha256"], "Bundled wheel provenance mismatch.")
    provenance = _load_json(provenance_path, "wheel provenance")
    wheel_identity = provenance.get("wheel")
    _require(isinstance(wheel_identity, dict), "Wheel provenance has no wheel identity.")
    _require(provenance.get("version") == manifest["version"], "Wheel provenance version mismatch.")
    _require(provenance.get("build_backend") == "setuptools==84.0.0" and provenance.get("wheel_generator") == "setuptools (84.0.0)", "Wheel provenance toolchain mismatch.")
    _require(wheel_identity.get("filename") == wheel.name and wheel_identity.get("bytes") == wheel.stat().st_size and wheel_identity.get("sha256") == build["wheel_sha256"] and wheel_identity.get("clean_build_count") == 2, "Wheel provenance does not bind the bundled wheel.")
    try:
        with zipfile.ZipFile(wheel, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            _require(bool(infos) and len(names) == len(set(names)), "Wheel members are empty or duplicate.")
            for info in infos:
                _safe_relative(info.filename, "wheel member")
                _require(info.date_time == (2026, 1, 1, 0, 0, 0), "Wheel timestamp is not reproducible.")
                _require((info.external_attr >> 16) & 0o170000 != 0o120000, "Wheel contains a symbolic link.")
            metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
            metadata = archive.read(metadata_name).decode("utf-8")
    except (OSError, zipfile.BadZipFile, StopIteration, UnicodeDecodeError) as exc:
        raise StarterSetupError("Bundled wheel metadata is invalid.") from exc
    _require(f"Version: {manifest['version']}" in metadata.splitlines(), "Bundled wheel version mismatch.")


def _walk_immutable_files(root: Path) -> set[str]:
    actual: set[str] = set()
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root)
        if relative_directory == Path("."):
            names[:] = [name for name in names if name not in RUNTIME_ROOTS]
        for name in list(names):
            path = directory_path / name
            _require(not _is_link_like(path), f"Bundle directory is a symbolic link or junction: {path.relative_to(root).as_posix()}")
        for name in files:
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            _require(not _is_link_like(path), f"Bundle file is a symbolic link or junction: {relative}")
            if relative != MANIFEST_NAME:
                actual.add(relative)
    return actual


def _require_no_links_tree(root: Path) -> None:
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        _require(not _is_link_like(directory_path), "Setup-owned partial state contains a symbolic link or junction.")
        for name in [*names, *files]:
            _require(not _is_link_like(directory_path / name), "Setup-owned partial state contains a symbolic link or junction.")


def validate_bundle(root: Path) -> tuple[dict[str, Any], str]:
    _require(sys.version_info >= MINIMUM_PYTHON, "Python 3.11 or newer is required.")
    root = root.resolve(strict=True)
    _require(root.is_dir() and not _is_link_like(root), "Bundle root must be a real directory.")
    manifest_path = root / MANIFEST_NAME
    _require(manifest_path.is_file() and not _is_link_like(manifest_path), "Bundle manifest is missing or unsafe.")
    manifest_bytes = manifest_path.read_bytes()
    manifest = _load_json_bytes(manifest_bytes, "bundle manifest")
    _validate_manifest_shape(manifest)

    expected: set[str] = set()
    casefolded: set[str] = set()
    for item in manifest["files"]:
        item = _exact_keys(item, {"path", "bytes", "sha256"}, "bundle inventory entry")
        relative = _safe_relative(item["path"], "bundle inventory path")
        _require(relative not in expected and relative.casefold() not in casefolded, "Bundle inventory paths are duplicate or case-colliding.")
        _require(type(item["bytes"]) is int and item["bytes"] >= 0, "Bundle file byte count is invalid.")
        _require(isinstance(item["sha256"], str) and HEX64.fullmatch(item["sha256"]) is not None, "Bundle file digest is invalid.")
        path = _safe_disk_path(root, relative)
        _require(path.is_file() and path.stat().st_size == item["bytes"] and _sha256(path) == item["sha256"], f"Bundle file failed inventory validation: {relative}")
        expected.add(relative)
        casefolded.add(relative.casefold())
    _require(_walk_immutable_files(root) == expected, "Bundle contains an unlisted or missing immutable file.")
    _validate_policy(root, manifest)
    for declaration in manifest["packages"]:
        _validate_pack(root, declaration)
    _validate_wheel(root, manifest)
    return manifest, _sha256_bytes(manifest_bytes)


def _venv_python(venv_root: Path) -> Path:
    return venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PIP_NO_INDEX"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return environment


def _run(command: list[str], *, cwd: Path, expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=_clean_environment(),
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        shell=False,
    )
    if result.returncode not in expected:
        raise StarterSetupError(
            f"Starter command failed with exit {result.returncode}: {' '.join(command[:4])}\n{result.stderr.strip()}"
        )
    return result


def _run_cli(python: Path, root: Path, manifest: dict[str, Any], arguments: list[str], expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
    state = root / manifest["install"]["state_directory"]
    return _run(
        [str(python), "-I", "-m", "standardsforge", "--db", str(state / "memory.db"), "--store", str(state / "objects"), *arguments],
        cwd=root,
        expected=expected,
    )


def _json_result(result: subprocess.CompletedProcess[str], name: str) -> dict[str, Any]:
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise StarterSetupError(f"{name} did not return JSON.") from exc
    _require(isinstance(envelope, dict) and envelope.get("ok") is True and isinstance(envelope.get("result"), dict), f"{name} did not return a successful envelope.")
    return envelope["result"]


def _receipt_value(manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "receipt_type": "synthetic_starter_install",
        "status": "ready",
        "bundle_manifest_sha256": manifest_sha256,
        "wheel_sha256": manifest["build"]["wheel_sha256"],
        "wheel_provenance_sha256": manifest["build"]["wheel_provenance_sha256"],
        "policy_sha256": manifest["install"]["policy_sha256"],
        "package_digests": sorted(item["package_digest"] for item in manifest["packages"]),
        "principal_id": manifest["install"]["principal_id"],
        "database": ".standardsforge/memory.db",
        "object_store": ".standardsforge/objects",
        "integrity_mode": "full_integrity",
        "smokes": {"doctor": "passed", "discovery": "passed", "exact_context": "passed"},
    }


def validate_receipt(root: Path, manifest: dict[str, Any], manifest_sha256: str) -> None:
    receipt_path = root.joinpath(*PurePosixPath(RECEIPT_RELATIVE).parts)
    _require(receipt_path.is_file() and not _is_link_like(receipt_path), "Starter receipt is missing or unsafe.")
    receipt = _load_json(receipt_path, "starter receipt")
    expected = _receipt_value(manifest, manifest_sha256)
    _require(receipt == expected, "Starter receipt does not match the current bundle and installed-state contract.")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _prepare_venv(root: Path, manifest: dict[str, Any], manifest_sha256: str) -> Path:
    venv_root = root / manifest["install"]["venv_directory"]
    _require(not _is_link_like(venv_root), "Starter environment cannot be a symbolic link or junction.")
    marker = venv_root / VENV_MARKER
    if venv_root.exists():
        _require_no_links_tree(venv_root)
        _require(marker.is_file() and not _is_link_like(marker) and _load_json(marker, "starter environment marker") == {"bundle_manifest_sha256": manifest_sha256}, "Existing .venv is not owned by this starter bundle.")
    else:
        venv_root.mkdir()
        _write_json_atomic(marker, {"bundle_manifest_sha256": manifest_sha256})
    python = _venv_python(venv_root)
    if not python.is_file():
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(venv_root)
    _require(python.is_file() and not _is_link_like(python), "Starter Python environment is incomplete or unsafe.")
    wheel = _safe_disk_path(root, manifest["build"]["wheel_path"])
    _run(
        [str(python), "-I", "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", str(wheel)],
        cwd=root,
    )
    return python


def _run_smokes(python: Path, root: Path, manifest: dict[str, Any]) -> None:
    install = manifest["install"]
    policy = root.joinpath(*PurePosixPath(install["policy_path"]).parts)
    doctor = _run_cli(
        python,
        root,
        manifest,
        ["doctor", "--policy", str(policy), "--principal", install["principal_id"], "--full-integrity"],
    )
    doctor_result = _json_result(doctor, "doctor")
    _require(doctor_result.get("ready") is True and doctor_result.get("integrity", {}).get("complete") is True, "Full-integrity doctor did not establish readiness.")

    discovery_spec = install["smokes"]["discovery"]
    discovery = _json_result(
        _run_cli(
            python,
            root,
            manifest,
            [
                "search",
                discovery_spec["query"],
                "--principal",
                install["principal_id"],
                "--query-mode",
                discovery_spec["query_mode"],
                "--package-digest",
                discovery_spec["package_digest"],
            ],
        ),
        "discovery smoke",
    )
    results = discovery.get("results")
    _require(isinstance(results, list) and results, "Discovery smoke returned no evidence.")
    returned_ids = {item.get("record_id") for item in results if isinstance(item, dict)}
    _require(set(discovery_spec["expected_record_ids"]) <= returned_ids, "Discovery smoke lost an expected record.")
    _require(all(item.get("package_digest") == discovery_spec["package_digest"] for item in results), "Discovery smoke crossed the package pin.")

    context_spec = install["smokes"]["exact_context"]
    context = _json_result(
        _run_cli(
            python,
            root,
            manifest,
            [
                "get-clause",
                discovery_spec["package_digest"],
                "--record-id",
                context_spec["record_id"],
                "--principal",
                install["principal_id"],
            ],
        ),
        "exact-context smoke",
    )
    evidence = context.get("evidence")
    _require(isinstance(evidence, list) and evidence and evidence[0].get("record_id") == context_spec["record_id"], "Exact-context smoke returned the wrong root evidence.")
    evidence_ids = {item.get("record_id") for item in evidence if isinstance(item, dict)}
    _require(set(context_spec["required_context_record_ids"]) <= evidence_ids, "Exact-context smoke lost required governing context.")


def setup_starter(root: Path, *, quiet: bool = False) -> dict[str, Any]:
    manifest, manifest_sha256 = validate_bundle(root)
    root = root.resolve(strict=True)
    state = root / manifest["install"]["state_directory"]
    _require(not _is_link_like(state), "Starter state cannot be a symbolic link or junction.")
    receipt_path = root.joinpath(*PurePosixPath(RECEIPT_RELATIVE).parts)
    partial_path = root.joinpath(*PurePosixPath(PARTIAL_RELATIVE).parts)
    existing_ready = receipt_path.is_file()
    if state.exists():
        if existing_ready:
            validate_receipt(root, manifest, manifest_sha256)
        elif partial_path.is_file():
            partial = _load_json(partial_path, "partial setup marker")
            _require(partial == {"bundle_manifest_sha256": manifest_sha256}, "Partial state belongs to another bundle.")
            _require_no_links_tree(state)
            shutil.rmtree(state)
        else:
            raise StarterSetupError("Existing .standardsforge state is not owned by a complete or recoverable starter setup.")

    python = _prepare_venv(root, manifest, manifest_sha256)
    for package in manifest["packages"]:
        _run(
            [
                str(python),
                "-I",
                "-c",
                "from standardsforge.pack import validate_pack_directory; import sys; validate_pack_directory(sys.argv[1])",
                str(root.joinpath(*PurePosixPath(package["path"]).parts)),
            ],
            cwd=root,
        )

    if not existing_ready:
        state.mkdir()
        _write_json_atomic(partial_path, {"bundle_manifest_sha256": manifest_sha256})
        policy_path = root.joinpath(*PurePosixPath(manifest["install"]["policy_path"]).parts)
        for package in manifest["packages"]:
            installed = _json_result(
                _run_cli(
                    python,
                    root,
                    manifest,
                    ["install", str(root.joinpath(*PurePosixPath(package["path"]).parts)), "--policy", str(policy_path)],
                ),
                "pack installation",
            )
            _require(installed.get("package_digest") == package["package_digest"], "Installed package digest does not match the starter manifest.")

    _run_smokes(python, root, manifest)
    if not existing_ready:
        _write_json_atomic(receipt_path, _receipt_value(manifest, manifest_sha256))
        partial_path.unlink(missing_ok=True)
    else:
        validate_receipt(root, manifest, manifest_sha256)
    result = {
        "ok": True,
        "status": "already_ready" if existing_ready else "ready",
        "profile": manifest["profile"],
        "version": manifest["version"],
        "package_digests": sorted(item["package_digest"] for item in manifest["packages"]),
        "network_dependency_resolution": "disabled",
    }
    if not quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
    return result


def main() -> int:
    try:
        setup_starter(Path(__file__).resolve().parent)
    except StarterSetupError as exc:
        print(json.dumps({"ok": False, "error": {"code": "starter_setup_failed", "message": str(exc)}}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
