from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from prepared_runtime import PreparedSetupError, setup_prepared


if __name__ == "__main__":
    try:
        setup_prepared(Path(__file__).resolve().parent)
    except PreparedSetupError as exc:
        print(json.dumps({"ok": False, "error": {"code": "prepared_setup_failed", "message": str(exc)}}), file=sys.stderr)
        raise SystemExit(1)
