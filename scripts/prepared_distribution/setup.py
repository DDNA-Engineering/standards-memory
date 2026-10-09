from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepared_runtime import PreparedSetupError, setup_prepared


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install the included standards library and optionally connect a model.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--mcp", action="store_const", const="offline", dest="mcp_mode", help="Include offline MCP (Windows x64 CPython 3.11, 3.12 or 3.13).")
    modes.add_argument("--mcp-online", action="store_const", const="online", dest="mcp_mode", help="Explicitly download MCP dependencies; standards and core code use the bundled files.")
    parser.add_argument("--connect", action="append", choices=("claude-desktop", "cursor", "codex"), default=[],
                        help="Also add StandardsForge to this model host's configuration (backed up first). Repeatable.")
    parser.add_argument("--host-config", type=Path,
                        help="Configuration file to change instead of the host's default location (one --connect only).")
    args = parser.parse_args()
    try:
        setup_prepared(Path(__file__).resolve().parent, mcp_mode=args.mcp_mode, connect=args.connect, host_config=args.host_config)
    except (PreparedSetupError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "prepared_setup_failed", "message": str(exc)}}), file=sys.stderr)
        raise SystemExit(1)
    except UnicodeError as exc:
        message = f"Prepared setup could not decode command output as UTF-8 ({exc}). Run setup again; if it repeats, report this message."
        print(json.dumps({"ok": False, "error": {"code": "prepared_setup_failed", "message": message}}), file=sys.stderr)
        raise SystemExit(1)
