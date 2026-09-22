from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.benchmark import BenchmarkContractError, run_benchmark  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a content-bound offline StandardsForge benchmark suite.")
    parser.add_argument("suite", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args()
    try:
        artifact = run_benchmark(args.suite, root=ROOT, policy_path=args.policy, output_path=args.output)
    except BenchmarkContractError as exc:
        print(json.dumps({"ok": False, "error": "benchmark_contract_error", "message": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    summary = artifact["run"]["summary"]
    print(json.dumps({"ok": summary["overall_passed"], "run_id": artifact["run"]["run_id"], "suite_sha256": artifact["run"]["suite"]["suite_sha256"], **summary}, sort_keys=True))
    return 0 if summary["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
