from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import venv
from pathlib import Path, PurePosixPath
from typing import Any


sys.dont_write_bytecode = True

MANIFEST_NAME = "bundle-manifest.json"
RECEIPT_RELATIVE = ".standardsforge/prepared-distribution.json"
PARTIAL_RELATIVE = ".standardsforge/prepared-setup-incomplete.json"
VENV_MARKER = ".standardsforge-prepared-venv.json"
RUNTIME_ROOTS = {".standardsforge", ".venv"}
HEX64 = re.compile(r"[0-9a-f]{64}")


class PreparedSetupError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PreparedSetupError(message)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparedSetupError(f"{name} is missing or is not valid UTF-8 JSON.") from exc
    _require(isinstance(value, dict), f"{name} must contain one JSON object.")
    return value


def _safe_relative(value: Any, name: str) -> str:
    _require(isinstance(value, str) and value, f"{name} must be a non-empty relative path.")
    _require("\\" not in value and not value.startswith("/") and ":" not in value, f"{name} is unsafe.")
    parsed = PurePosixPath(value)
    _require(parsed.as_posix() == value, f"{name} is not canonical POSIX text.")
    _require(all(part not in {"", ".", ".."} for part in parsed.parts), f"{name} is unsafe.")
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
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
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
        raise PreparedSetupError(f"Bundle path escapes its root: {relative}") from exc
    _require(candidate.is_file(), f"Bundle file is missing: {relative}")
    return candidate


def _require_runtime_path(root: Path, target: Path, *, directory: bool, label: str) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise PreparedSetupError(f"{label} escapes the prepared root.") from exc
    current = root
    for part in relative.parts:
        current = current / part
        _require(not _is_link_like(current), f"{label} contains a symbolic link or junction.")
    _require(target.is_dir() if directory else target.is_file(), f"{label} is missing or has the wrong type.")


def _require_no_links_tree(root: Path, label: str) -> None:
    _require(root.is_dir() and not _is_link_like(root), f"{label} is missing or unsafe.")
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in [*directory_names, *file_names]:
            _require(not _is_link_like(current_path / name), f"{label} contains a symbolic link or junction.")


def _runtime_profile() -> str:
    machine = platform.machine().casefold()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "windows_x86_64"
    if sys.platform.startswith("linux") and machine in {"amd64", "x86_64"}:
        return "linux_x86_64"
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos_arm64"
    if sys.platform == "darwin" and machine == "x86_64":
        return "macos_x86_64"
    raise PreparedSetupError(f"Unsupported prepared-core runtime: {sys.platform}/{platform.machine()}")


def _validate_manifest_identity(manifest: dict[str, Any]) -> None:
    _require(
        set(manifest) == {"schema_version", "product", "version", "build", "state", "files"},
        "The prepared-distribution manifest has missing or unknown fields.",
    )
    _require(manifest["schema_version"] == "1.3", "Unsupported prepared-distribution manifest version.")
    _require(manifest["product"] == "StandardsForge prepared distribution", "Unexpected prepared product.")
    _require(isinstance(manifest["version"], str) and manifest["version"], "Prepared version is missing.")
    build = manifest["build"]
    _require(isinstance(build, dict), "Prepared build identity must be an object.")
    expected = {
        "archive_source_date_epoch": 1767225600,
        "archive_timestamp": "2026-01-01T00:00:00Z",
        "wheel_build_backend": "setuptools==84.0.0",
        "wheel_generator": "setuptools (84.0.0)",
        "mcp_requirement": "mcp==2.2.0",
        "core_runtime_python": "CPython >=3.11",
        "mcp_runtime_python": "CPython 3.12",
        "mcp_runtime_platform": "win_amd64",
    }
    for key, value in expected.items():
        _require(build.get(key) == value, f"Unexpected prepared build field: {key}")
    platforms = build.get("core_runtime_platforms")
    _require(
        platforms == ["windows_x86_64", "linux_x86_64", "macos_arm64", "macos_x86_64"],
        "Prepared core runtime profiles are invalid.",
    )
    _require(_runtime_profile() in platforms, "This runtime is not supported by the prepared core.")
    for key in ("wheel_sha256", "wheel_provenance_sha256", "mcp_wheelhouse_sha256", "mcp_requirements_sha256"):
        _require(isinstance(build.get(key), str) and HEX64.fullmatch(build[key]) is not None, f"Invalid {key}.")
    _require(type(build.get("mcp_wheel_count")) is int and build["mcp_wheel_count"] > 0, "Invalid MCP wheel count.")
    state = manifest["state"]
    _require(isinstance(state, dict) and state.get("principal_id") == "local-user", "Prepared state identity is invalid.")
    _require(type(state.get("corpus_package_count")) is int and state["corpus_package_count"] > 0, "Prepared corpus count is invalid.")


def _disk_inventory(root: Path) -> set[str]:
    observed: set[str] = set()
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_root = current_path.relative_to(root)
        if relative_root == Path("."):
            directory_names[:] = sorted(name for name in directory_names if name not in RUNTIME_ROOTS)
        for name in list(directory_names):
            target = current_path / name
            _require(not _is_link_like(target), f"Bundle directory is a symbolic link or junction: {target.relative_to(root).as_posix()}")
        for name in sorted(file_names):
            target = current_path / name
            relative = target.relative_to(root).as_posix()
            if relative == MANIFEST_NAME:
                continue
            _require(not _is_link_like(target), f"Bundle file is a symbolic link or junction: {relative}")
            _require(target.is_file(), f"Bundle inventory member is not a regular file: {relative}")
            observed.add(relative)
    return observed


def validate_bundle(root: Path) -> tuple[dict[str, Any], str]:
    root = root.resolve(strict=True)
    manifest_path = root / MANIFEST_NAME
    _require(manifest_path.is_file() and not _is_link_like(manifest_path), "The prepared manifest is missing or unsafe.")
    manifest_bytes = manifest_path.read_bytes()
    manifest = _load_json(manifest_path, "prepared-distribution manifest")
    _validate_manifest_identity(manifest)

    files = manifest["files"]
    _require(isinstance(files, list) and files, "The prepared file inventory is empty.")
    expected: set[str] = set()
    by_path: dict[str, dict[str, Any]] = {}
    for item in files:
        _require(isinstance(item, dict) and set(item) == {"path", "bytes", "sha256"}, "A prepared inventory row is malformed.")
        relative = _safe_relative(item["path"], "inventory path")
        _require(relative not in expected and relative.split("/", 1)[0] not in RUNTIME_ROOTS, "The prepared inventory contains a duplicate or runtime path.")
        _require(type(item["bytes"]) is int and item["bytes"] >= 0, "An inventory byte count is invalid.")
        _require(isinstance(item["sha256"], str) and HEX64.fullmatch(item["sha256"]) is not None, "An inventory digest is invalid.")
        target = _safe_disk_path(root, relative)
        _require(target.stat().st_size == item["bytes"] and _sha256(target) == item["sha256"], f"Prepared inventory validation failed: {relative}")
        expected.add(relative)
        by_path[relative] = item
    _require(_disk_inventory(root) == expected, "The prepared directory contains missing or unlisted files.")

    wheel_items = [item for path, item in by_path.items() if path.startswith("wheel/")]
    _require(len(wheel_items) == 1 and wheel_items[0]["sha256"] == manifest["build"]["wheel_sha256"], "Prepared wheel identity is inconsistent.")
    wheel_provenance = _load_json(_safe_disk_path(root, "provenance/wheel-build.json"), "wheel provenance")
    _require(_sha256(root / "provenance/wheel-build.json") == manifest["build"]["wheel_provenance_sha256"], "Wheel provenance digest is inconsistent.")
    _require(
        wheel_provenance.get("wheel", {}).get("sha256") == manifest["build"]["wheel_sha256"]
        and wheel_provenance.get("wheel", {}).get("filename") == PurePosixPath(wheel_items[0]["path"]).name
        and wheel_provenance.get("version") == manifest["version"],
        "Wheel provenance does not identify the prepared wheel and version.",
    )
    scope = _load_json(_safe_disk_path(root, "provenance/source-baseline.json"), "source baseline")
    acquisition = _safe_disk_path(root, "provenance/acquisition-manifest.json")
    _require(
        scope.get("acquisition", {}).get("manifest_path") == "provenance/acquisition-manifest.json"
        and scope.get("acquisition", {}).get("manifest_sha256") == _sha256(acquisition),
        "The acquisition snapshot does not match the source baseline.",
    )
    requirements = _safe_disk_path(root, "provenance/mcp-wheelhouse-win-amd64-cp312.txt")
    _require(_sha256(requirements) == manifest["build"]["mcp_requirements_sha256"], "MCP requirements digest is inconsistent.")
    wheelhouse = sorted(
        (item for path, item in by_path.items() if path.startswith("wheelhouse/") and path.endswith(".whl")),
        key=lambda item: PurePosixPath(item["path"]).name,
    )
    rows = "".join(f'{item["sha256"]} {item["bytes"]} {PurePosixPath(item["path"]).name}\n' for item in wheelhouse).encode("utf-8")
    _require(
        len(wheelhouse) == manifest["build"]["mcp_wheel_count"]
        and _sha256_bytes(rows) == manifest["build"]["mcp_wheelhouse_sha256"],
        "MCP wheelhouse identity is inconsistent.",
    )
    return manifest, _sha256_bytes(manifest_bytes)


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL"):
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PIP_NO_INDEX"] = "1"
    return environment


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _run(command: list[str], root: Path, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=root,
        env=_clean_environment(),
        shell=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() if capture and result.stderr else ""
        raise PreparedSetupError(f"Prepared command failed ({result.returncode}): {detail}")
    return result


def _cli(python: Path, root: Path, arguments: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    state = root / ".standardsforge"
    return _run(
        [str(python), "-I", "-m", "standardsforge", "--db", str(state / "memory.db"), "--store", str(state / "objects"), *arguments],
        root,
        capture=capture,
    )


def _parse_cli_success(result: subprocess.CompletedProcess[str], operation: str) -> dict[str, Any]:
    try:
        envelope = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise PreparedSetupError(f"Prepared {operation} did not return JSON.") from exc
    _require(
        isinstance(envelope, dict)
        and envelope.get("ok") is True
        and isinstance(envelope.get("result"), dict),
        f"Prepared {operation} did not return a successful result envelope.",
    )
    return envelope["result"]


def validate_receipt(root: Path, manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
    state = root / ".standardsforge"
    receipt_path = root / RECEIPT_RELATIVE
    _require(state.is_dir() and not _is_link_like(state), "Prepared state is missing or is a symbolic link or junction.")
    _require(receipt_path.is_file() and not _is_link_like(receipt_path), "Prepared setup receipt is missing or unsafe.")
    receipt = _load_json(receipt_path, "prepared setup receipt")
    expected = {
        "bundle_manifest_sha256": manifest_sha256,
        "principal_id": "local-user",
        "status": "ready",
        "version": manifest["version"],
        "wheel_sha256": manifest["build"]["wheel_sha256"],
    }
    _require(
        set(receipt) == {*expected, "mcp_status"}
        and all(receipt.get(key) == value for key, value in expected.items())
        and receipt.get("mcp_status") in {"not_installed", "ready"},
        "The prepared setup receipt does not match this bundle.",
    )
    return receipt


def validate_ready(root: Path) -> tuple[dict[str, Any], str]:
    root = root.resolve(strict=True)
    manifest_path = root / MANIFEST_NAME
    _require(manifest_path.is_file() and not _is_link_like(manifest_path), "The prepared manifest is missing or unsafe.")
    manifest_bytes = manifest_path.read_bytes()
    manifest = _load_json(manifest_path, "prepared-distribution manifest")
    _validate_manifest_identity(manifest)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    validate_receipt(root, manifest, manifest_sha256)
    venv_root = root / ".venv"
    marker_path = venv_root / VENV_MARKER
    _require_runtime_path(root, venv_root, directory=True, label="Prepared .venv")
    _require_runtime_path(root, marker_path, directory=False, label="Prepared virtual-environment marker")
    marker = _load_json(marker_path, "prepared virtual-environment marker")
    _require(marker == {"bundle_manifest_sha256": manifest_sha256}, "The prepared virtual environment does not match this bundle.")
    python = _venv_python(root / ".venv")
    _require_runtime_path(root, python, directory=False, label="Prepared Python executable")
    _require_runtime_path(root, root / ".standardsforge" / "memory.db", directory=False, label="Prepared database")
    _require_runtime_path(root, root / ".standardsforge" / "objects", directory=True, label="Prepared object store")
    return manifest, manifest_sha256


def setup_prepared(root: Path, *, quiet: bool = False) -> dict[str, Any]:
    _require(sys.implementation.name == "cpython" and sys.version_info >= (3, 11), "CPython 3.11 or newer is required.")
    manifest, manifest_sha256 = validate_bundle(root)
    root = root.resolve(strict=True)
    state = root / ".standardsforge"
    venv_root = root / ".venv"
    receipt_path = root / RECEIPT_RELATIVE
    partial_path = root / PARTIAL_RELATIVE
    existing_ready = receipt_path.is_file()
    existing_receipt: dict[str, Any] | None = None
    recovering_partial = False
    if state.exists() and not existing_ready:
        partial = _load_json(partial_path, "partial setup marker") if partial_path.is_file() else None
        _require(partial == {"bundle_manifest_sha256": manifest_sha256}, "Existing prepared state is not owned by a recoverable setup.")
        _require_no_links_tree(state, "Prepared partial state")
        shutil.rmtree(state)
        recovering_partial = True
    elif existing_ready:
        existing_receipt = validate_receipt(root, manifest, manifest_sha256)

    marker_path = venv_root / VENV_MARKER
    if venv_root.exists():
        if not marker_path.is_file() and recovering_partial:
            _require_no_links_tree(venv_root, "Prepared partial .venv")
            shutil.rmtree(venv_root)
        else:
            marker = _load_json(marker_path, "prepared virtual-environment marker")
            _require(marker == {"bundle_manifest_sha256": manifest_sha256}, "Existing .venv is not owned by this prepared bundle.")
            _require_no_links_tree(venv_root, "Prepared .venv")
    if not venv_root.exists():
        if not existing_ready:
            state.mkdir()
            _write_json_atomic(partial_path, {"bundle_manifest_sha256": manifest_sha256})
        venv.EnvBuilder(with_pip=True, symlinks=False).create(venv_root)
        _write_json_atomic(marker_path, {"bundle_manifest_sha256": manifest_sha256})
    python = _venv_python(venv_root)
    _require(python.is_file() and not _is_link_like(python), "Prepared Python environment is incomplete or unsafe.")
    wheel = next(root.joinpath(*PurePosixPath(item["path"]).parts) for item in manifest["files"] if item["path"].startswith("wheel/"))
    _run([str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--no-deps", "--force-reinstall", str(wheel)], root)

    if not existing_ready:
        if not state.exists():
            state.mkdir()
            _write_json_atomic(partial_path, {"bundle_manifest_sha256": manifest_sha256})
        policy = root / "policies/prepared-local.json"
        _cli(python, root, ["install-corpus", str(root / "corpus/corpus.json"), "--policy", str(policy)])
        _cli(python, root, ["install", str(root / "packs/mil-std-810h-derived-outline.zip"), "--policy", str(policy)])

    policy = root / "policies/prepared-local.json"
    doctor = _cli(python, root, ["doctor", "--policy", str(policy), "--principal", "local-user", "--full-integrity"], capture=True)
    doctor_result = _parse_cli_success(doctor, "doctor")
    _require(doctor_result.get("ready") is True and doctor_result.get("integrity", {}).get("complete") is True, "Prepared full-integrity doctor did not establish readiness.")
    search = _cli(python, root, ["search", "environmental testing", "--principal", "local-user", "--query-mode", "natural_language", "--limit", "1"], capture=True)
    search_result = _parse_cli_success(search, "search")
    _require(isinstance(search_result.get("results"), list) and search_result["results"], "Prepared search returned no evidence.")

    receipt = {
        "bundle_manifest_sha256": manifest_sha256,
        "principal_id": "local-user",
        "status": "ready",
        "mcp_status": existing_receipt["mcp_status"] if existing_receipt is not None else "not_installed",
        "version": manifest["version"],
        "wheel_sha256": manifest["build"]["wheel_sha256"],
    }
    _write_json_atomic(receipt_path, receipt)
    partial_path.unlink(missing_ok=True)
    result = {"ok": True, "status": "already_ready" if existing_ready else "ready", "version": manifest["version"], "runtime_profile": _runtime_profile(), "network_dependency_resolution": "disabled"}
    if not quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
    return result
