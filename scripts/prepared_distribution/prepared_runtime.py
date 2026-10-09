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
DISCARDED_VENV = ".discarded-venv"
RUNTIME_ROOTS = {".standardsforge", ".venv"}
# Files that operating-system shells create on their own when a folder is opened
# (macOS Finder, Windows Explorer). They are never read by setup or the runtime.
OS_METADATA_NAMES = {".ds_store", "thumbs.db", "ehthumbs.db", "desktop.ini", "icon\r"}
HEX64 = re.compile(r"[0-9a-f]{64}")
# Windows x64 CPython versions with a bundled, hash-locked offline MCP closure.
OFFLINE_MCP_PYTHONS = ("3.11", "3.12", "3.13")
TOKENIZER_PATH = "tokenizer/o200k_base.json"


def mcp_requirements_path(python_version: str) -> str:
    return f"provenance/mcp-wheelhouse-win-amd64-cp{python_version.replace('.', '')}.txt"


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


def _remove_posix_venv_lib64_alias(root: Path) -> None:
    if not sys.platform.startswith("linux"):
        return
    _require(root.is_dir() and not _is_link_like(root), "Prepared .venv is missing or unsafe.")
    alias = root / "lib64"
    if not alias.is_symlink():
        return
    _require(os.readlink(alias) == "lib", "Prepared .venv contains an unexpected symbolic link or junction.")
    library = root / "lib"
    _require(library.is_dir() and not _is_link_like(library), "Prepared .venv library is missing or unsafe.")
    alias.unlink()


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
    _require(manifest["schema_version"] == "1.4", "Unsupported prepared-distribution manifest version.")
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
        "mcp_runtime_platform": "win_amd64",
        "mcp_runtime_pythons": list(OFFLINE_MCP_PYTHONS),
    }
    for key, value in expected.items():
        _require(build.get(key) == value, f"Unexpected prepared build field: {key}")
    platforms = build.get("core_runtime_platforms")
    _require(
        platforms == ["windows_x86_64", "linux_x86_64", "macos_arm64", "macos_x86_64"],
        "Prepared core runtime profiles are invalid.",
    )
    _require(_runtime_profile() in platforms, "This runtime is not supported by the prepared core.")
    for key in ("wheel_sha256", "wheel_provenance_sha256", "mcp_wheelhouse_sha256"):
        _require(isinstance(build.get(key), str) and HEX64.fullmatch(build[key]) is not None, f"Invalid {key}.")
    locks = build.get("mcp_requirements_sha256")
    _require(
        isinstance(locks, dict) and set(locks) == set(OFFLINE_MCP_PYTHONS)
        and all(isinstance(value, str) and HEX64.fullmatch(value) is not None for value in locks.values()),
        "Invalid mcp_requirements_sha256.",
    )
    tokenizer = build.get("tokenizer")
    _require(
        isinstance(tokenizer, dict)
        and set(tokenizer) == {"encoding", "path", "sha256", "bytes", "implementation"}
        and tokenizer["encoding"] == "o200k_base" and tokenizer["path"] == TOKENIZER_PATH
        and isinstance(tokenizer["sha256"], str) and HEX64.fullmatch(tokenizer["sha256"]) is not None
        and type(tokenizer["bytes"]) is int and tokenizer["bytes"] > 0
        and tokenizer["implementation"] == "tiktoken==0.14.0",
        "Prepared tokenizer identity is invalid.",
    )
    _require(type(build.get("mcp_wheel_count")) is int and build["mcp_wheel_count"] > 0, "Invalid MCP wheel count.")
    state = manifest["state"]
    _require(isinstance(state, dict) and state.get("principal_id") == "local-user", "Prepared state identity is invalid.")
    _require(type(state.get("corpus_package_count")) is int and state["corpus_package_count"] > 0, "Prepared corpus count is invalid.")
    extras = state.get("qualified_packs", [])
    _require(isinstance(extras, list), "Qualified packs must be a list.")
    seen = set()
    for item in extras:
        _require(isinstance(item, dict) and set(item) == {"path", "pack_id", "package_digest", "suite_path", "run_path"}, "Qualified pack fields are invalid.")
        _require(isinstance(item["pack_id"], str) and item["pack_id"] and isinstance(item["package_digest"], str)
                 and HEX64.fullmatch(item["package_digest"]) is not None, "Qualified pack identity is invalid.")
        _require(item["package_digest"] not in seen, "Duplicate qualified pack.")
        seen.add(item["package_digest"])
        kind = "reviewed" if isinstance(item["path"], str) and item["path"].startswith("packs/reviewed/") else "recovery"
        for key, prefix, suffix in (("path", f"packs/{kind}/", ".zip"), ("suite_path", f"qualification/{kind}/", "-suite.json"), ("run_path", f"qualification/{kind}/", "-run.json")):
            value = item[key]
            _require(isinstance(value, str) and value.startswith(prefix) and value.endswith(suffix)
                     and re.fullmatch(r"[a-z0-9-]+", value[len(prefix):-len(suffix)]) is not None, "Qualified pack path is invalid.")
            _require(sum(f["path"] == value for f in manifest["files"]) == 1, "Qualified pack input must be inventoried exactly once.")
    if extras:
        _require(state.get("included_package_count") == state["corpus_package_count"] + 1 + len(extras), "Qualified pack count is inconsistent.")
    bindings = state.get("reference_bindings")
    if bindings is not None:
        _require(
            isinstance(bindings, dict) and set(bindings) == {"path", "sha256"}
            and bindings["path"] == "references/reference-bindings.json"
            and isinstance(bindings["sha256"], str) and HEX64.fullmatch(bindings["sha256"]) is not None
            and sum(f["path"] == bindings["path"] and f["sha256"] == bindings["sha256"] for f in manifest["files"]) == 1,
            "Reviewed reference bindings are not inventoried exactly once with their pinned digest.",
        )


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


def _is_os_metadata(relative: str) -> bool:
    name = PurePosixPath(relative).name
    return name.casefold() in OS_METADATA_NAMES or name.startswith("._")


def _describe(paths: set[str], limit: int = 5) -> str:
    ordered = sorted(paths)
    shown = ", ".join(ordered[:limit])
    return shown + (f" and {len(ordered) - limit} more" if len(ordered) > limit else "")


def _require_closed_inventory(observed: set[str], expected: set[str]) -> None:
    # OS metadata files are tolerated only when the inventory does not list that path;
    # links and non-regular files were already rejected while walking.
    unlisted = {path for path in observed - expected if not _is_os_metadata(path)}
    missing = expected - observed
    problems = []
    if missing:
        problems.append(f"missing: {_describe(missing)}")
    if unlisted:
        problems.append(f"not part of this release: {_describe(unlisted)}")
    _require(
        not problems,
        "The prepared directory contains missing or unlisted files (" + "; ".join(problems) + "). "
        "Remove files you added to the library folder, or extract the release ZIP again into a new folder.",
    )


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
    _require_closed_inventory(_disk_inventory(root), expected)

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
    locked: set[str] = set()
    for python_version, expected_digest in manifest["build"]["mcp_requirements_sha256"].items():
        requirements = _safe_disk_path(root, mcp_requirements_path(python_version))
        _require(_sha256(requirements) == expected_digest, f"MCP requirements digest is inconsistent for Python {python_version}.")
        for line in requirements.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"[A-Za-z0-9_.-]+==[^\s]+ --hash=sha256:([0-9a-f]{64})", line)
            _require(match is not None, f"MCP requirements for Python {python_version} contain a malformed entry.")
            locked.add(match.group(1))
    _require(locked == {item["sha256"] for item in wheelhouse}, "MCP wheelhouse does not exactly match its per-Python locks.")
    tokenizer = manifest["build"]["tokenizer"]
    tokenizer_item = by_path.get(TOKENIZER_PATH)
    _require(
        tokenizer_item is not None and tokenizer_item["sha256"] == tokenizer["sha256"] and tokenizer_item["bytes"] == tokenizer["bytes"],
        "Prepared tokenizer artifact is inconsistent.",
    )
    return manifest, _sha256_bytes(manifest_bytes)


def required_install_bytes(manifest: dict[str, Any]) -> int:
    """Free space a first setup needs beside the extracted files.

    Measured for a7 on Linux: the installed index and object store took 1.68 times the
    bytes of the bundled packs, and the environment with model dependencies 72 MB.
    Twice the pack bytes plus 250 MB leaves margin for SQLite journals and pip caches.
    """
    pack_bytes = sum(item["bytes"] for item in manifest["files"] if item["path"].startswith(("corpus/", "packs/")))
    return 2 * pack_bytes + 250 * 1000 * 1000


def _require_free_space(root: Path, manifest: dict[str, Any]) -> None:
    required = required_install_bytes(manifest)
    available = shutil.disk_usage(root).free
    _require(
        available >= required,
        f"Setup needs about {required / 1e9:.1f} GB of free disk space for the library index, but only "
        f"{available / 1e9:.1f} GB is available on the drive holding {root}. Free up space, or extract the "
        "release into a folder on a drive with more space, then run setup again.",
    )


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


def _run(command: list[str], root: Path, *, capture: bool = False, dependency_network: bool = False) -> subprocess.CompletedProcess[str]:
    environment = _clean_environment()
    if dependency_network:
        environment["PIP_NO_INDEX"] = "0"
    # Capture bytes and decode explicitly: the CLI writes UTF-8 regardless of the
    # locale, so a Windows ANSI code page must not be used to decode its output.
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        shell=False,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    stdout: str | None = None
    stderr: str | None = None
    if capture:
        # stderr is diagnostic only; never let an undecodable traceback hide the failure.
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
    if result.returncode != 0:
        detail = stderr.strip() if stderr else ""
        raise PreparedSetupError(f"Prepared command failed ({result.returncode}): {detail}")
    if capture:
        try:
            stdout = (result.stdout or b"").decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise PreparedSetupError("Prepared command output is not valid UTF-8; setup cannot interpret it.") from exc
    return subprocess.CompletedProcess(result.args, result.returncode, stdout, stderr)


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


def _check_mcp_profile(mode: str | None) -> None:
    _require(mode in {None, "offline", "online"}, "Unknown MCP installation mode.")
    if mode == "offline":
        _require(
            sys.platform == "win32" and _python_version() in OFFLINE_MCP_PYTHONS
            and platform.machine().casefold() in {"amd64", "x86_64"},
            "Offline MCP requires 64-bit CPython 3.11, 3.12 or 3.13 on Windows. "
            "Use --mcp-online for an explicit networked dependency install on other supported runtimes.",
        )


def _python_version() -> str:
    return f"{sys.version_info[0]}.{sys.version_info[1]}"


def mcp_server_options(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Trusted startup options for the bundled tokenizer and reviewed references."""
    tokenizer = manifest["build"]["tokenizer"]
    options = ["--tokenizer-artifact", str(root.joinpath(*PurePosixPath(tokenizer["path"]).parts)),
               "--tokenizer-sha256", tokenizer["sha256"]]
    bindings = manifest["state"].get("reference_bindings")
    if bindings is not None:
        options += ["--reference-bindings", str(root.joinpath(*PurePosixPath(bindings["path"]).parts)),
                    "--reference-bindings-sha256", bindings["sha256"]]
    return options


def _mcp_command(root: Path) -> list[str]:
    return [str(_venv_python(root / ".venv")), "-I", str(root / "run_mcp.py")]


def _write_host_configuration(root: Path) -> dict[str, str]:
    command, *arguments = _mcp_command(root)
    state = root / ".standardsforge"
    json_path = state / "mcp-config.json"
    toml_path = state / "codex-mcp.toml"
    _write_json_atomic(json_path, {"mcpServers": {"standardsforge": {"command": command, "args": arguments}}})
    # JSON string escaping is also valid for these TOML basic strings.
    toml_path.write_text(
        "[mcp_servers.standardsforge]\n"
        f"command = {json.dumps(command, ensure_ascii=False)}\n"
        f"args = {json.dumps(arguments, ensure_ascii=False)}\n",
        encoding="utf-8", newline="\n",
    )
    return {"claude_desktop_or_cursor": str(json_path), "codex": str(toml_path)}


def _prepare_mcp(root: Path, python: Path, wheel: Path, manifest: dict[str, Any], mode: str | None) -> None:
    if mode == "offline":
        # Select the lock for the environment's interpreter, which an earlier setup may
        # have created with a different supported Python than the one running now.
        probe = _run([str(python), "-I", "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"], root, capture=True)
        environment_version = (probe.stdout or "").strip()
        _require(
            environment_version in OFFLINE_MCP_PYTHONS,
            f"The prepared environment uses Python {environment_version or 'unknown'}, which has no offline MCP lock. "
            f"Delete {root / '.venv'} and run setup again with Python 3.11, 3.12 or 3.13.",
        )
        requirements = root.joinpath(*PurePosixPath(mcp_requirements_path(environment_version)).parts)
        _run([str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-index",
              "--find-links", str(root / "wheelhouse"), "--require-hashes", "--no-deps",
              "--requirement", str(requirements)], root)
        _run([str(python), "-I", str(root / "verify_mcp_environment.py"), "--requirements", str(requirements),
              "--standardsforge-version", manifest["version"]], root)
    elif mode == "online":
        # Only this explicitly selected administrative path may resolve dependencies online.
        # The core code still comes from the verified bundled wheel, never another release.
        _run([str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check", f"{wheel}[mcp,tokens]"], root, dependency_network=True)
    _run([str(python), "-I", "-m", "pip", "check"], root)
    _run([str(python), "-I", str(root / "smoke_mcp.py"), "--db", str(root / ".standardsforge/memory.db"),
          "--store", str(root / ".standardsforge/objects"), "--principal", "local-user",
          "--query", "environmental testing", *mcp_server_options(root, manifest)], root)


def _is_disposable_state(state: Path) -> bool:
    """True for a state directory interrupted before its ownership marker landed."""
    if _is_link_like(state) or not state.is_dir():
        return False
    try:
        names = {child.name for child in state.iterdir()}
    except OSError:
        return False
    return names <= {f".{Path(PARTIAL_RELATIVE).name}.tmp"}


def _running_from(environment_root: Path) -> bool:
    try:
        return Path(sys.prefix).resolve() == environment_root.resolve()
    except OSError:
        return False


def _discard_owned_venv(venv_root: Path, state: Path) -> None:
    """Move an owned .venv into owned state atomically, then delete it.

    The rename either happens entirely or not at all, so the virtual
    environment never loses its ownership marker while it is still named
    ``.venv``. Deleting the moved tree afterwards can fail or be interrupted;
    the remains live inside state that still carries the partial-setup
    marker, so the next run can finish the cleanup.
    """
    discarded = state / DISCARDED_VENV
    if discarded.exists() or _is_link_like(discarded):
        _require_no_links_tree(discarded, "Discarded prepared .venv")
        _remove_owned_tree(discarded, venv_root)
    try:
        os.rename(venv_root, discarded)
    except OSError as exc:
        raise PreparedSetupError(
            f"Setup could not replace the incomplete virtual environment {venv_root} ({exc}). "
            "Close any program that is using it, such as a model host running the StandardsForge MCP server, "
            f"then run setup again. If this keeps failing, delete the directory {venv_root} and run setup again."
        ) from exc
    _remove_owned_tree(discarded, venv_root)


def _remove_owned_tree(path: Path, reported: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise PreparedSetupError(
            f"Setup could not delete the incomplete prepared files in {path} ({exc}). "
            f"Close any program that is using {reported}, then run setup again; setup will finish the cleanup."
        ) from exc


def _clear_partial_state(state: Path, partial_path: Path) -> None:
    """Empty owned partial state, keeping its ownership marker until last."""
    for child in sorted(state.iterdir()):
        if child == partial_path:
            continue
        if child.is_dir() and not _is_link_like(child):
            _remove_owned_tree(child, child)
        else:
            try:
                child.unlink()
            except OSError as exc:
                raise PreparedSetupError(
                    f"Setup could not delete {child} ({exc}). Close any program that is using it, then run setup again."
                ) from exc


def setup_prepared(root: Path, *, quiet: bool = False, mcp_mode: str | None = None,
                   connect: list[str] | None = None, host_config: Path | None = None) -> dict[str, Any]:
    _require(sys.implementation.name == "cpython" and sys.version_info >= (3, 11), "CPython 3.11 or newer is required.")
    _check_mcp_profile(mcp_mode)
    connect = list(dict.fromkeys(connect or []))
    _require(host_config is None or len(connect) == 1, "--host-config needs exactly one --connect host.")
    _require(
        not connect or mcp_mode is not None or (root / RECEIPT_RELATIVE).is_file(),
        "--connect needs the model connection: add --mcp (Windows) or --mcp-online.",
    )
    if not quiet:
        print("Checking the prepared library. First setup indexes the included packs and can take several minutes.", flush=True)
    try:
        manifest, manifest_sha256 = validate_bundle(root)
    except PreparedSetupError:
        # Preserve the bundle ownership needed for a retry, but never retain readiness
        # when the closed inventory no longer validates. Do not follow external state.
        state = root / ".standardsforge"
        receipt_path = root / RECEIPT_RELATIVE
        if state.is_dir() and not _is_link_like(state) and receipt_path.is_file() and not _is_link_like(receipt_path):
            receipt = _load_json(receipt_path, "prepared setup receipt")
            previous_digest = receipt.get("bundle_manifest_sha256")
            if isinstance(previous_digest, str) and HEX64.fullmatch(previous_digest):
                _write_json_atomic(root / PARTIAL_RELATIVE, {"bundle_manifest_sha256": previous_digest})
                receipt_path.unlink()
        raise
    root = root.resolve(strict=True)
    state = root / ".standardsforge"
    venv_root = root / ".venv"
    receipt_path = root / RECEIPT_RELATIVE
    partial_path = root / PARTIAL_RELATIVE
    existing_ready = receipt_path.is_file()
    existing_receipt: dict[str, Any] | None = None
    recovering_partial = False
    if (state.exists() or _is_link_like(state)) and not existing_ready and not _is_disposable_state(state):
        partial = _load_json(partial_path, "partial setup marker") if partial_path.is_file() and not _is_link_like(partial_path) else None
        _require(
            partial == {"bundle_manifest_sha256": manifest_sha256},
            f"Existing prepared state {state} is not owned by a recoverable setup of this bundle, so setup will not change it. "
            f"If it was left by an earlier StandardsForge setup, delete the directory {state} and run setup again.",
        )
        _require_no_links_tree(state, "Prepared partial state")
        recovering_partial = True
    elif existing_ready:
        existing_receipt = validate_receipt(root, manifest, manifest_sha256)

    # Decide ownership of every existing runtime path before anything is deleted.
    marker_path = venv_root / VENV_MARKER
    discard_venv = False
    if venv_root.exists() or _is_link_like(venv_root):
        _require(not _is_link_like(venv_root), f"Existing {venv_root} is a symbolic link or junction; setup will not use or change it.")
        if marker_path.is_file() and not _is_link_like(marker_path):
            marker = _load_json(marker_path, "prepared virtual-environment marker")
            _require(
                marker == {"bundle_manifest_sha256": manifest_sha256},
                f"Existing {venv_root} is not owned by this prepared bundle, so setup will not change it. "
                f"If it was created by another StandardsForge bundle, delete the directory {venv_root} and run setup again.",
            )
        else:
            # Without its marker a .venv is ours only while the partial-setup
            # marker proves that this bundle's interrupted setup created it.
            _require(
                recovering_partial,
                f"Existing {venv_root} has no StandardsForge ownership marker, so setup will not use, change, or delete it. "
                f"If it was left by an interrupted StandardsForge setup, delete the directory {venv_root} and run setup again; "
                "otherwise move it out of the prepared library folder.",
            )
        discard_venv = recovering_partial
        if discard_venv:
            _require(
                not _running_from(venv_root),
                f"Setup is running from {venv_root}, which it must replace. Run setup with the system Python instead "
                "(for example `py -3.12 setup.py --mcp` on Windows or `python3 setup.py` elsewhere).",
            )
        _remove_posix_venv_lib64_alias(venv_root)
        _require_no_links_tree(venv_root, "Prepared .venv")
    if recovering_partial:
        if discard_venv:
            _discard_owned_venv(venv_root, state)
        _clear_partial_state(state, partial_path)
    if not existing_ready:
        # Indexing a large library can take minutes; fail before it starts, not halfway.
        _require_free_space(root, manifest)
    if existing_ready:
        # A failed revalidation must not leave an old ready receipt usable by launchers.
        _write_json_atomic(partial_path, {"bundle_manifest_sha256": manifest_sha256})
        receipt_path.unlink()
    if not venv_root.exists():
        if not existing_ready:
            state.mkdir(exist_ok=True)
            _write_json_atomic(partial_path, {"bundle_manifest_sha256": manifest_sha256})
        venv_root.mkdir()
        _write_json_atomic(marker_path, {"bundle_manifest_sha256": manifest_sha256})
        venv.EnvBuilder(with_pip=True, symlinks=False).create(venv_root)
        _remove_posix_venv_lib64_alias(venv_root)
        _require_no_links_tree(venv_root, "Prepared .venv")
    python = _venv_python(venv_root)
    _require(python.is_file() and not _is_link_like(python), "Prepared Python environment is incomplete or unsafe.")
    wheel = next(root.joinpath(*PurePosixPath(item["path"]).parts) for item in manifest["files"] if item["path"].startswith("wheel/"))
    _run([str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--no-deps", "--force-reinstall", str(wheel)], root)

    if not existing_ready:
        if not partial_path.is_file():
            state.mkdir(exist_ok=True)
            _write_json_atomic(partial_path, {"bundle_manifest_sha256": manifest_sha256})
        policy = root / "policies/prepared-local.json"
        _cli(python, root, ["install-corpus", str(root / "corpus/corpus.json"), "--policy", str(policy)])
        _cli(python, root, ["install", str(root / "packs/mil-std-810h-derived-outline.zip"), "--policy", str(policy)])
        for item in manifest["state"].get("qualified_packs", []):
            _cli(python, root, ["install", str(root / item["path"]), "--policy", str(policy)])

    policy = root / "policies/prepared-local.json"
    doctor = _cli(python, root, ["doctor", "--policy", str(policy), "--principal", "local-user", "--full-integrity"], capture=True)
    doctor_result = _parse_cli_success(doctor, "doctor")
    _require(doctor_result.get("ready") is True and doctor_result.get("integrity", {}).get("complete") is True, "Prepared full-integrity doctor did not establish readiness.")
    suites = [(root / "qualification/real-suite.json", root / "qualification/real-benchmark.json")]
    suites.extend((root / item["suite_path"], root / item["run_path"]) for item in manifest["state"].get("qualified_packs", []))
    for suite_path, run_path in suites:
        if not suite_path.is_file():
            continue  # Historical bundles predate real-document qualification.
        qualification = _parse_cli_success(_cli(python, root, ["qualify-real", str(suite_path), "--principal", "local-user"], capture=True), "qualify-real")
        recorded = _load_json(run_path, "real-document regression evidence")["run"]
        _require(qualification.get("gate", {}).get("passed") is True
                 and qualification.get("suite_sha256") == recorded["suite_sha256"]
                 and qualification.get("runtime_source_sha256") == recorded["runtime_source_sha256"],
                 "Installed real-document regressions did not match the qualified runtime and suite.")
    search = _cli(python, root, ["search", "environmental testing", "--principal", "local-user", "--query-mode", "natural_language", "--limit", "1"], capture=True)
    search_result = _parse_cli_success(search, "search")
    _require(isinstance(search_result.get("results"), list) and search_result["results"], "Prepared search returned no evidence.")

    mcp_ready = mcp_mode is not None or (existing_receipt is not None and existing_receipt["mcp_status"] == "ready")
    if mcp_ready:
        if not quiet:
            print("Checking the model connection through a real local MCP query.", flush=True)
        _prepare_mcp(root, python, wheel, manifest, mcp_mode)
    configuration = _write_host_configuration(root) if mcp_ready else None
    receipt = {
        "bundle_manifest_sha256": manifest_sha256,
        "principal_id": "local-user",
        "status": "ready",
        "mcp_status": "ready" if mcp_ready else "not_installed",
        "version": manifest["version"],
        "wheel_sha256": manifest["build"]["wheel_sha256"],
    }
    _write_json_atomic(receipt_path, receipt)
    partial_path.unlink(missing_ok=True)
    _require(mcp_ready or not connect, "--connect needs the model connection: add --mcp (Windows) or --mcp-online.")
    connections = _connect_hosts(root, connect, host_config) if connect else []
    result = {"ok": True, "status": "already_ready" if existing_ready else "ready", "version": manifest["version"], "runtime_profile": _runtime_profile(), "network_dependency_resolution": "explicit_mcp_dependencies" if mcp_mode == "online" else "disabled"}
    if configuration is not None:
        result["host_configuration"] = configuration
    if connections:
        result["host_connections"] = connections
    if not quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
        if connections:
            for connection in connections:
                print(f"Connected {connection['host']} ({connection['status']}): {connection['config_path']}. {connection['restart']}")
        elif configuration is not None:
            print("Model connection ready. Copy the generated configuration into your host, then restart its MCP connection, "
                  "or run setup again with --connect claude-desktop, --connect cursor or --connect codex to add it for you.")
    return result


def _connect_hosts(root: Path, hosts: list[str], host_config: Path | None) -> list[dict[str, Any]]:
    from host_connect import HostConnectError, connect_host

    command, *arguments = _mcp_command(root)
    results = []
    for host in hosts:
        try:
            results.append(connect_host(host, command, arguments, config_path=host_config))
        except (HostConnectError, OSError) as exc:
            raise PreparedSetupError(
                f"The library and model connection are ready, but {host} was not configured: {exc} "
                "You can copy the generated configuration from .standardsforge instead."
            ) from exc
    return results
