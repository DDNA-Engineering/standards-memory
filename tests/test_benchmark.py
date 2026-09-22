from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.benchmark import (  # noqa: E402
    BenchmarkContractError,
    canonical_json,
    run_benchmark,
    validate_run_artifact,
    validate_suite_document,
)


SUITE_PATH = ROOT / "benchmarks/synthetic-contract-v1.json"


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class BenchmarkQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
        cls.artifact = run_benchmark(SUITE_PATH, root=ROOT)

    def test_content_bound_suite_runs_offline_and_preserves_raw_cases(self) -> None:
        run = self.artifact["run"]
        self.assertTrue(run["summary"]["overall_passed"])
        self.assertEqual(8, run["summary"]["case_count"])
        self.assertEqual(
            [case["case_id"] for case in self.suite["suite"]["cases"]],
            [result["case_id"] for result in run["case_results"]],
        )
        self.assertTrue(all(result["cold"]["response"] for result in run["case_results"]))
        self.assertTrue(all(result["warm"]["response"] for result in run["case_results"]))
        self.assertEqual("synthetic_contract_qualification", run["qualification_class"])
        for dimension in self.suite["suite"]["unmeasured_dimensions"]:
            self.assertEqual("not_measured", run["metrics"][dimension]["status"])
        validate_run_artifact(self.artifact, self.suite, ROOT)

    def test_suite_digest_drift_is_rejected(self) -> None:
        changed = copy.deepcopy(self.suite)
        changed["suite"]["cases"][0]["question"] += " Changed without review."
        with self.assertRaisesRegex(BenchmarkContractError, "review digest"):
            validate_suite_document(changed, ROOT)

    def test_synthetic_suite_cannot_be_relabelled_as_real_quality(self) -> None:
        changed = copy.deepcopy(self.suite)
        changed["suite"]["qualification_class"] = "reviewed_real_document_quality"
        changed["review"]["reviewed_content_sha256"] = digest(changed["suite"])
        with self.assertRaisesRegex(BenchmarkContractError, "fails schema"):
            validate_suite_document(changed, ROOT)

    def test_missing_critical_fact_fails_without_omitting_the_case(self) -> None:
        changed = copy.deepcopy(self.suite)
        target = next(case for case in changed["suite"]["cases"] if case["case_id"] == "context-v1-required-note")
        target["expectations"]["critical_facts"][0]["exact_text"] = "81 N for 60 seconds"
        changed["review"]["reviewed_content_sha256"] = digest(changed["suite"])
        with tempfile.TemporaryDirectory(prefix="standardsforge-benchmark-test-") as temporary:
            suite_path = Path(temporary) / "changed-suite.json"
            suite_path.write_text(json.dumps(changed), encoding="utf-8")
            artifact = run_benchmark(suite_path, root=ROOT)
        results = artifact["run"]["case_results"]
        self.assertEqual(len(changed["suite"]["cases"]), len(results))
        failed = next(result for result in results if result["case_id"] == "context-v1-required-note")
        self.assertFalse(failed["passed"])
        self.assertIn("lost_critical_facts", failed["failures"])
        self.assertFalse(artifact["run"]["summary"]["overall_passed"])
        validate_run_artifact(artifact, changed, ROOT)

    def test_run_summary_cannot_claim_success_over_failed_cases(self) -> None:
        changed = copy.deepcopy(self.artifact)
        changed["run"]["summary"] = {
            "overall_passed": False,
            "case_count": len(changed["run"]["case_results"]),
            "passed_count": len(changed["run"]["case_results"]) - 1,
            "failed_count": 1,
        }
        changed["run_content_sha256"] = digest(changed["run"])
        with self.assertRaisesRegex(BenchmarkContractError, "summary arithmetic"):
            validate_run_artifact(changed, self.suite, ROOT)

    def test_sample_digest_and_case_set_are_recomputed(self) -> None:
        changed = copy.deepcopy(self.artifact)
        changed["run"]["case_results"][0]["cold"]["response_bytes"] += 1
        changed["run_content_sha256"] = digest(changed["run"])
        with self.assertRaisesRegex(BenchmarkContractError, "response digest or byte count"):
            validate_run_artifact(changed, self.suite, ROOT)

        changed = copy.deepcopy(self.artifact)
        changed["run"]["case_results"].pop()
        changed["run_content_sha256"] = digest(changed["run"])
        with self.assertRaisesRegex(BenchmarkContractError, "each suite case exactly once"):
            validate_run_artifact(changed, self.suite, ROOT)

    def test_rehashed_wrong_edition_response_cannot_reuse_stored_assertions(self) -> None:
        changed = copy.deepcopy(self.artifact)
        result = next(item for item in changed["run"]["case_results"] if item["case_id"] == "search-v1-exact-phrase")
        for state in ("cold", "warm"):
            sample = result[state]
            sample["response"]["results"][0]["package_digest"] = "ad93262351fbf1138f841e7f964fca95ffe7c5139778996ec851bdd91df33ad3"
            body = canonical_json(sample["response"])
            sample["response_bytes"] = len(body)
            sample["response_sha256"] = hashlib.sha256(body).hexdigest()
        changed["run_content_sha256"] = digest(changed["run"])
        with self.assertRaisesRegex(BenchmarkContractError, "stored evaluation"):
            validate_run_artifact(changed, self.suite, ROOT)

    def test_rehashed_altered_evidence_text_is_a_citation_mismatch(self) -> None:
        changed = copy.deepcopy(self.artifact)
        result = next(item for item in changed["run"]["case_results"] if item["case_id"] == "context-v1-required-note")
        for state in ("cold", "warm"):
            sample = result[state]
            sample["response"]["evidence"][0]["text"] = sample["response"]["evidence"][0]["text"].replace("adapter", "device")
            body = canonical_json(sample["response"])
            sample["response_bytes"] = len(body)
            sample["response_sha256"] = hashlib.sha256(body).hexdigest()
        changed["run_content_sha256"] = digest(changed["run"])
        with self.assertRaisesRegex(BenchmarkContractError, "stored evaluation"):
            validate_run_artifact(changed, self.suite, ROOT)

    def test_zero_metric_denominator_is_rejected(self) -> None:
        changed = copy.deepcopy(self.artifact)
        changed["run"]["metrics"]["case_pass_rate"]["denominator"] = 0
        changed["run_content_sha256"] = digest(changed["run"])
        with self.assertRaisesRegex(BenchmarkContractError, "fails schema"):
            validate_run_artifact(changed, self.suite, ROOT)


if __name__ == "__main__":
    unittest.main()
