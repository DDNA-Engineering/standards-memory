"""Launch the prepared model connection without setup or caller-selected state."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

# -I excludes script directories; import only the adjacent distribution helper.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepared_runtime import PreparedSetupError, _clean_environment, _venv_python, mcp_server_options, validate_ready, validate_receipt


def main() -> int:
    if len(sys.argv) != 1:
        print("The prepared MCP launcher does not accept state, principal or server overrides.", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent
    try:
        manifest, digest = validate_ready(root)
        if validate_receipt(root, manifest, digest)["mcp_status"] != "ready":
            raise PreparedSetupError("Run setup.py --mcp (Windows, Python 3.11-3.13) or setup.py --mcp-online before connecting a model.")
    except (PreparedSetupError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "prepared_mcp_not_ready", "message": str(exc)}}), file=sys.stderr)
        return 1
    state = root / ".standardsforge"
    return subprocess.run(
        [str(_venv_python(root / ".venv")), "-I", "-m", "standardsforge.mcp_server",
         "--db", str(state / "memory.db"), "--store", str(state / "objects"),
         "--principal", "local-user", "--result-mode", "structured_only", *mcp_server_options(root, manifest)],
        cwd=root, env=_clean_environment(), shell=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
