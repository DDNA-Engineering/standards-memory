from __future__ import annotations

import argparse
import email.parser
import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

from build_prepared_distribution import _validate_mcp_wheelhouse, _validate_tokenizer


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def validate_runtime(
    wheel_dir: Path, wheelhouse: Path, requirements: Path, tokenizer_artifact: Path | None = None
) -> dict[str, object]:
    wheels = sorted(wheel_dir.resolve().glob("standardsforge-*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected one verified StandardsForge wheel.")
    with zipfile.ZipFile(wheels[0], "r") as archive:
        metadata_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError("The StandardsForge wheel has invalid package metadata.")
        wheel_metadata = email.parser.BytesParser().parsebytes(
            archive.read(metadata_names[0])
        )
    standardsforge_version = wheel_metadata.get("Version", "")
    if not standardsforge_version:
        raise ValueError("The StandardsForge wheel has no version.")
    # The runtime under test is this interpreter's own Windows MCP lock.
    python_version = f"{sys.version_info[0]}.{sys.version_info[1]}"
    payloads, wheelhouse_sha256, requirements_sha256 = _validate_mcp_wheelhouse(
        wheelhouse, {python_version: requirements}
    )
    tokenizer_options: list[str] = []
    if tokenizer_artifact is not None:
        tokenizer = _validate_tokenizer(tokenizer_artifact, ROOT / "scripts" / "prepared_distribution" / "tokenizer-lock.json")
        tokenizer_options = ["--tokenizer-artifact", str(tokenizer_artifact.resolve()), "--tokenizer-sha256", tokenizer["sha256"]]
    with tempfile.TemporaryDirectory(prefix="standardsforge prepared mcp ") as temporary:
        runtime = Path(temporary)
        environment = runtime / "runtime"
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        ambient = runtime / "ambient-pythonpath"
        ambient.mkdir()
        (ambient / "standardsforge.py").write_text(
            "raise RuntimeError('ambient StandardsForge module was imported')\n",
            encoding="utf-8",
        )
        (ambient / "mcp.py").write_text(
            "raise RuntimeError('ambient MCP module was imported')\n", encoding="utf-8"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ambient)
        env["PIP_NO_INDEX"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        _run(
            [
                str(python),
                "-I",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--find-links",
                str(wheelhouse.resolve()),
                "--require-hashes",
                "--no-deps",
                "--force-reinstall",
                "--requirement",
                str(requirements.resolve()),
            ],
            cwd=runtime,
            env=env,
        )
        _run(
            [
                str(python),
                "-I",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--no-deps",
                "--force-reinstall",
                str(wheels[0].resolve()),
            ],
            cwd=runtime,
            env=env,
        )
        _run([str(python), "-I", "-m", "pip", "check"], cwd=runtime, env=env)
        _run(
            [
                str(python),
                "-I",
                str(
                    ROOT
                    / "scripts"
                    / "prepared_distribution"
                    / "verify_mcp_environment.py"
                ),
                "--requirements",
                str(requirements.resolve()),
                "--standardsforge-version",
                standardsforge_version,
            ],
            cwd=runtime,
            env=env,
        )
        database = runtime / "state" / "memory.db"
        store = runtime / "state" / "objects"
        _run(
            [
                str(python),
                "-I",
                "-m",
                "standardsforge",
                "--db",
                str(database),
                "--store",
                str(store),
                "install",
                str(ROOT / "examples" / "packs" / "fictional-adapter-v1"),
                "--policy",
                str(ROOT / "examples" / "policies" / "local-synthetic.json"),
            ],
            cwd=runtime,
            env=env,
        )
        _run(
            [
                str(python),
                "-I",
                str(ROOT / "scripts" / "prepared_distribution" / "smoke_mcp.py"),
                "--db",
                str(database),
                "--store",
                str(store),
                "--principal",
                "local-user",
                "--query",
                "axial load",
                *tokenizer_options,
            ],
            cwd=runtime,
            env=env,
        )
    return {
        "ok": True,
        "wheel": wheels[0].name,
        "mcp_wheel_count": len(payloads),
        "mcp_wheelhouse_sha256": wheelhouse_sha256,
        "mcp_requirements_sha256": requirements_sha256,
        "token_budget_selection": "verified" if tokenizer_options else "not_requested",
        "network_resolution": "disabled",
        "ambient_pythonpath_ignored": True,
        "cwd_independent": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument("--tokenizer-artifact", type=Path, help="Locked o200k_base artifact; also proves token-budget selection")
    args = parser.parse_args()
    print(
        json.dumps(
            validate_runtime(args.wheel_dir, args.wheelhouse, args.requirements, args.tokenizer_artifact),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
