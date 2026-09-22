from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
SETUP_SPEC = importlib.util.spec_from_file_location(
    "_standardsforge_starter_setup", ROOT / "setup.py"
)
if SETUP_SPEC is None or SETUP_SPEC.loader is None:
    raise RuntimeError("Starter setup module could not be loaded.")
starter_setup = importlib.util.module_from_spec(SETUP_SPEC)
SETUP_SPEC.loader.exec_module(starter_setup)


def main() -> int:
    root = ROOT
    try:
        manifest, manifest_sha256 = starter_setup.validate_bundle(root)
        starter_setup.validate_receipt(root, manifest, manifest_sha256)
    except starter_setup.StarterSetupError:
        setup_result = subprocess.run(
            [sys.executable, str(root / "setup.py")],
            cwd=root,
            env=starter_setup._clean_environment(),
            shell=False,
        )
        if setup_result.returncode != 0:
            return setup_result.returncode
        try:
            manifest, manifest_sha256 = starter_setup.validate_bundle(root)
            starter_setup.validate_receipt(root, manifest, manifest_sha256)
        except starter_setup.StarterSetupError as exc:
            print(json.dumps({"ok": False, "error": {"code": "starter_not_ready", "message": str(exc)}}), file=sys.stderr)
            return 1

    venv_root = root / manifest["install"]["venv_directory"]
    python = starter_setup._venv_python(venv_root)
    state = root / manifest["install"]["state_directory"]
    command = [
        str(python),
        "-I",
        "-m",
        "standardsforge",
        "--db",
        str(state / "memory.db"),
        "--store",
        str(state / "objects"),
        *sys.argv[1:],
    ]
    return subprocess.run(command, cwd=root, env=starter_setup._clean_environment(), shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
