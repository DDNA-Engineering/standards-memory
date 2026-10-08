from __future__ import annotations
import argparse
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from standardsforge.coverage_ledger import write_artifact
from standardsforge.real_benchmark import run_real_benchmark
from standardsforge.service import StandardsForgeService

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run explicit source-bound real-document regressions offline.")
    parser.add_argument("suite", type=Path)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.suite.read_text(encoding="utf-8"))
    with patch.object(socket, "socket", side_effect=RuntimeError("Network is forbidden during real-document qualification")):
        result = run_real_benchmark(StandardsForgeService.open_read_only(args.db, args.store), args.principal, document)
    write_artifact(args.output, result)
    print(json.dumps(result["run"]["metrics"]))
    raise SystemExit(0 if result["run"]["gate"]["passed"] else 1)
