from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from prepared_runtime import PreparedSetupError, _clean_environment, _venv_python, validate_bundle, validate_ready


def main() -> int:
    root = Path(__file__).resolve().parent
    try:
        validate_ready(root)
    except PreparedSetupError:
        try:
            validate_bundle(root)
        except PreparedSetupError as exc:
            print(json.dumps({"ok": False, "error": {"code": "prepared_bundle_invalid", "message": str(exc)}}), file=sys.stderr)
            return 1
        setup = subprocess.run([sys.executable, str(root / "setup.py")], cwd=root, env=_clean_environment(), shell=False)
        if setup.returncode != 0:
            return setup.returncode
        try:
            validate_ready(root)
        except PreparedSetupError as exc:
            print(json.dumps({"ok": False, "error": {"code": "prepared_not_ready", "message": str(exc)}}), file=sys.stderr)
            return 1
    state = root / ".standardsforge"
    command = [str(_venv_python(root / ".venv")), "-I", "-m", "standardsforge", "--db", str(state / "memory.db"), "--store", str(state / "objects"), *sys.argv[1:]]
    return subprocess.run(command, cwd=root, env=_clean_environment(), shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
