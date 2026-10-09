from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepared_runtime import PreparedSetupError, _clean_environment, _venv_python, mcp_server_options, validate_bundle, validate_ready, validate_receipt


def main() -> int:
    root = Path(__file__).resolve().parent
    try:
        manifest, digest = validate_ready(root)
    except PreparedSetupError as ready_error:
        try:
            validate_bundle(root)
        except PreparedSetupError as exc:
            print(json.dumps({"ok": False, "error": {"code": "prepared_bundle_invalid", "message": str(exc)}}), file=sys.stderr)
            return 1
        print(json.dumps({"ok": False, "error": {"code": "prepared_not_ready", "message": f"{ready_error} Run setup.py explicitly before querying."}}), file=sys.stderr)
        return 1
    state = root / ".standardsforge"
    # The tokenizer needs the optional dependencies installed with the model connection;
    # a core-only installation keeps byte budgets and still follows reviewed references.
    options = mcp_server_options(root, manifest)
    if validate_receipt(root, manifest, digest)["mcp_status"] != "ready":
        options = options[4:]
    command = [str(_venv_python(root / ".venv")), "-I", "-m", "standardsforge", "--db", str(state / "memory.db"), "--store", str(state / "objects"), *options, *sys.argv[1:]]
    return subprocess.run(command, cwd=root, env=_clean_environment(), shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
