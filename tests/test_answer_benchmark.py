from __future__ import annotations

import copy
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_reference_bindings as fixtures
from standardsforge.answer_benchmark import run_answer_benchmark, validate_adjudication
from standardsforge.answer_review_ui import export_answer_review
from standardsforge.coverage_ledger import digest
from standardsforge.errors import StandardsForgeError


def envelope(key, body):
    return {"schema_version": "0.1.0", key: body, key + "_sha256": digest(body)}


class AnswerBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReferenceBindingsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service = self.fixture.service
        selector = self.fixture.binding["source"]
        self.suite = envelope("suite", {"suite_id": "fixture", "author_identity": "fixture-author", "frozen_at": "2026-10-08",
            "qualification": "bounded_source_grounded_answer_quality", "cases": [{"case_id": "q1", "question": "What source conditions govern the load?",
            "evidence": [selector], "criteria": [{"criterion_id": "c1", "requirement": "Retain conditioning temperature and duration.", "evidence_indices": [0]}]}]})
        self.submission = envelope("submission", {"suite_sha256": self.suite["suite_sha256"], "respondent_identity": "fixture-model",
            "method": "Synthetic contract fixture; no actual human review.", "submitted_at": "2026-10-08", "answers": [{"case_id": "q1",
            "text": "Apply the load after at least two hours at 23 °C ± 2 °C.", "citations": [selector]}]})
        self.review = envelope("adjudication", {"suite_sha256": self.suite["suite_sha256"], "submission_sha256": self.submission["submission_sha256"],
            "reviewer": {"identity": "fixture-reviewer", "kind": "agent", "reviewed_at": "2026-10-08", "method": "Synthetic reviewer fixture.", "independence_claim": "separate_reviewer"},
            "case_reviews": [{"case_id": "q1", "answer_verdict": "supported", "rationale": "Synthetic assertion for runner behavior only.",
                "criteria": [{"criterion_id": "c1", "verdict": "pass", "rationale": "The answer preserves the specified temperature and duration."}]}]})

    def run_benchmark(self):
        return run_answer_benchmark(self.service, "local-user", self.suite, self.submission, self.review)

    def test_offline_raw_evidence_metrics_and_qualification_boundaries(self):
        before = self.fixture.db.read_bytes()
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            report = self.run_benchmark()
        self.assertEqual(before, self.fixture.db.read_bytes())
        self.assertTrue(report["run"]["gate"]["passed"])
        self.assertEqual(1, report["run"]["metrics"]["passed_cases"])
        self.assertEqual(self.submission, report["run"]["submission"])
        self.assertEqual(2, len(report["run"]["results"][0]["evidence"][0]["evidence"]))
        self.assertFalse(report["run"]["qualification"]["reviewer_identity_authenticated"])
        self.assertFalse(report["run"]["qualification"]["corpus_wide_quality_established"])
        import validate_contracts as contracts
        schemas = contracts.load_schemas(); registry = contracts.check_schema_documents(schemas)
        contracts.validate_with_schema(schemas, registry, "answer-benchmark-run.schema.json", report)

    def test_missing_judgment_stale_answer_or_faked_independence_rejected(self):
        for mutation in (lambda d: d["case_reviews"][0]["criteria"].clear(),
                         lambda d: d["case_reviews"].clear(),
                         lambda d: d["reviewer"].update(identity=" FIXTURE-MODEL "),
                         lambda d: d["reviewer"].update(identity="fixture-author"),
                         lambda d: d.update(submission_sha256="0" * 64)):
            body = copy.deepcopy(self.review["adjudication"]); mutation(body)
            with self.assertRaises(StandardsForgeError):
                validate_adjudication(self.suite, self.submission, envelope("adjudication", body))
        self.submission["submission"]["answers"][0]["text"] += " changed"
        with self.assertRaises(StandardsForgeError): self.run_benchmark()

    def test_whole_answer_unsupported_and_unassessed_criteria_fail_gate(self):
        body = copy.deepcopy(self.review["adjudication"])
        body["case_reviews"][0]["answer_verdict"] = "contradicted"
        self.review = envelope("adjudication", body)
        self.assertFalse(self.run_benchmark()["run"]["gate"]["passed"])
        body["case_reviews"][0]["answer_verdict"] = "supported"
        body["case_reviews"][0]["criteria"][0]["verdict"] = "unable_to_assess"
        self.review = envelope("adjudication", body)
        self.assertEqual(1, self.run_benchmark()["run"]["metrics"]["unassessed_criteria"])
        self.assertFalse(self.run_benchmark()["run"]["gate"]["passed"])

    def test_source_access_revocation_and_missing_citations_cannot_pass(self):
        body = copy.deepcopy(self.submission["submission"]); body["answers"][0]["citations"] = []
        self.submission = envelope("submission", body)
        body = copy.deepcopy(self.review["adjudication"]); body["submission_sha256"] = self.submission["submission_sha256"]
        self.review = envelope("adjudication", body)
        result = self.run_benchmark()
        self.assertFalse(result["run"]["gate"]["passed"])
        self.fixture.admin.revoke(self.fixture.pins[0], "local-user")
        with self.assertRaises(StandardsForgeError): self.run_benchmark()

    def test_review_export_starts_unreviewed_escapes_content_and_refuses_overwrite(self):
        body = copy.deepcopy(self.submission["submission"])
        body["answers"][0]["text"] = '</script><script>alert("untrusted")</script>'
        submission = envelope("submission", body)
        path = self.fixture.root / "review.html"
        result = export_answer_review(self.service, "local-user", self.suite, submission, path)
        self.assertEqual("awaiting_human_review", result["review_status"])
        text = path.read_text(encoding="utf-8")
        self.assertNotIn(body["answers"][0]["text"], text)
        self.assertIn('value="">Unreviewed', text)
        self.assertIn("connect-src &#x27;none&#x27;", text)
        self.assertIn("23 °C ± 2 °C", text)
        with self.assertRaises(StandardsForgeError):
            export_answer_review(self.service, "local-user", self.suite, submission, path)
