from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema.validators import validator_for


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_starter_distribution import validate_starter_archive  # noqa: E402


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PIP_NO_INDEX"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return environment


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=_environment(),
        check=False,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        shell=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"Starter subprocess exited {result.returncode}: {' '.join(command[:4])}\n{result.stderr.strip()}"
        )
    return result


def _immutable_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).parts[0] not in {".venv", ".standardsforge"}
    }


def _json_result(result: subprocess.CompletedProcess[str], name: str) -> dict[str, Any]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} did not return JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} did not return an object.")
    return value


def exercise_starter_archive(archive_path: Path) -> dict[str, Any]:
    manifest = validate_starter_archive(archive_path)
    with tempfile.TemporaryDirectory(prefix="StandardsForge starter acceptance space ") as temporary:
        extraction_root = Path(temporary)
        with zipfile.ZipFile(archive_path, "r") as archive:
            prefix = f"standardsforge-starter-{manifest['version']}/"
            distribution_root = extraction_root / prefix.removesuffix("/")
            distribution_root.mkdir()
            for info in archive.infolist():
                relative = info.filename.removeprefix(prefix)
                if not relative:
                    continue
                target = distribution_root.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info.filename))

        before = _immutable_snapshot(distribution_root)
        first = _json_result(
            _run([sys.executable, "-I", str(distribution_root / "setup.py")], distribution_root),
            "first setup",
        )
        if first.get("status") != "ready":
            raise ValueError("First starter setup did not report ready.")
        second = _json_result(
            _run([sys.executable, "-I", str(distribution_root / "setup.py")], distribution_root),
            "second setup",
        )
        if second.get("status") != "already_ready":
            raise ValueError("Second starter setup did not revalidate existing ready state.")

        policy = distribution_root / manifest["install"]["policy_path"]
        doctor = _json_result(
            _run(
                [
                    sys.executable,
                    "-I",
                    str(distribution_root / "run.py"),
                    "doctor",
                    "--policy",
                    str(policy),
                    "--principal",
                    manifest["install"]["principal_id"],
                    "--full-integrity",
                ],
                distribution_root,
            ),
            "launcher doctor",
        )
        if doctor.get("ok") is not True or doctor.get("result", {}).get("ready") is not True:
            raise ValueError("Starter launcher doctor did not report ready.")

        discovery_spec = manifest["install"]["smokes"]["discovery"]
        search = _json_result(
            _run(
                [
                    sys.executable,
                    "-I",
                    str(distribution_root / "run.py"),
                    "search",
                    discovery_spec["query"],
                    "--query-mode",
                    discovery_spec["query_mode"],
                    "--package-digest",
                    discovery_spec["package_digest"],
                    "--principal",
                    manifest["install"]["principal_id"],
                ],
                distribution_root,
            ),
            "launcher search",
        )
        results = search.get("result", {}).get("results", [])
        if not results or discovery_spec["expected_record_ids"][0] not in {item.get("record_id") for item in results}:
            raise ValueError("Starter launcher search lost its expected result.")

        context_spec = manifest["install"]["smokes"]["exact_context"]
        clause = _json_result(
            _run(
                [
                    sys.executable,
                    "-I",
                    str(distribution_root / "run.py"),
                    "get-clause",
                    discovery_spec["package_digest"],
                    "--record-id",
                    context_spec["record_id"],
                    "--principal",
                    manifest["install"]["principal_id"],
                ],
                distribution_root,
            ),
            "launcher get-clause",
        )
        evidence_ids = {
            item.get("record_id") for item in clause.get("result", {}).get("evidence", [])
        }
        if not set(context_spec["required_context_record_ids"]) <= evidence_ids:
            raise ValueError("Starter launcher retrieval lost required context.")

        receipt_path = distribution_root / manifest["install"]["receipt_path"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        schema = json.loads(
            (distribution_root / "contracts" / "starter-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        validator_class(schema).validate(receipt)
        if _immutable_snapshot(distribution_root) != before:
            raise ValueError("Starter setup changed immutable bundle files.")

        venv_python = distribution_root / manifest["install"]["venv_directory"] / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        mcp_probe = subprocess.run(
            [str(venv_python), "-I", "-c", "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('mcp') is None else 1)"],
            cwd=distribution_root,
            env=_environment(),
            shell=False,
        )
        if mcp_probe.returncode != 0:
            raise ValueError("Starter unexpectedly installed the optional MCP dependency.")

    return {
        "ok": True,
        "profile": manifest["profile"],
        "version": manifest["version"],
        "first_setup": "ready",
        "second_setup": "already_ready",
        "doctor": "ready",
        "discovery": "passed",
        "exact_context": "passed",
        "receipt": "schema_valid",
        "immutable_bundle": "unchanged",
        "mcp_extra": "absent",
        "path_with_spaces": True,
        "pythonpath_removed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reopen and exercise a StandardsForge synthetic starter distribution.")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        result = exercise_starter_archive(args.archive)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "starter_acceptance_failed", "message": str(exc)}}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
