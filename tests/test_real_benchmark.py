from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from standardsforge.coverage_ledger import digest
from standardsforge.errors import StandardsForgeError
from standardsforge.real_benchmark import evaluate_case, validate_suite, validate_run


class RealBenchmarkTests(unittest.TestCase):
    def test_semantic_suite_requires_complete_typed_expectations(self):
        document = json.loads((ROOT / "benchmarks/real/mil-std-1661-semantics.json").read_text(encoding="utf-8"))
        validate_suite(document)
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(json.loads((ROOT / "contracts/real-benchmark-suite.schema.json").read_text(encoding="utf-8")))
        validator.validate(document)
        for field, value in [("subject", None), ("span_indices", []), ("span_indices", [True]), ("span_indices", [0, 0])]:
            with self.subTest(field=field, value=value):
                invalid = copy.deepcopy(document)
                invalid["suite"]["cases"][0]["expected"]["semantic_assertions"][0]["statement"][field] = value
                invalid["review"]["suite_sha256"] = digest(invalid["suite"])
                with self.assertRaises(StandardsForgeError):
                    validate_suite(invalid)
                self.assertTrue(list(validator.iter_errors(invalid)))
        invalid = copy.deepcopy(document)
        assertion = invalid["suite"]["cases"][0]["expected"]["semantic_assertions"][0]
        statement = assertion.pop("statement")
        assertion.update(modality=statement["modality"], polarity=statement["polarity"])
        invalid["review"]["suite_sha256"] = digest(invalid["suite"])
        with self.assertRaises(StandardsForgeError):
            validate_suite(invalid)
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_semantic_gate_detects_changed_statement_and_qualifier_meaning(self):
        suite = {"package_digest": "a" * 64, "edition_id": "edition"}
        statement = {"subject": "Operator", "action": "release", "modality": "shall", "polarity": "negative",
                     "exact_text": "Operator shall not release except when permitted", "span_indices": [0]}
        qualifier = {"kind": "exception", "exact_text": "except when permitted", "span_indices": [0]}
        assertion = {"record_id": "requirement", "content_role": "requirement_candidate", "statement": statement,
                     "qualifiers": [qualifier]}
        case = {"operation": "get_clause", "expected": {"record_ids": ["requirement"], "forbidden_record_ids": [],
            "citations": [], "critical_facts": [], "complete_for_requested_scope": False, "semantic_assertions": [assertion]}}
        semantics = copy.deepcopy({"content_role": "requirement_candidate", "statement": statement, "qualifiers": [qualifier]})
        packet = {"package": suite, "evidence": [{"record_id": "requirement", "text": "source", "structure": {"semantics": semantics}}],
                  "completeness": {"complete_for_requested_scope": False}}
        self.assertTrue(evaluate_case(packet, case, suite)["passed"])
        for field, value in [("subject", "Other actor"), ("action", "approve"), ("modality", "may"),
                             ("polarity", "affirmative"), ("exact_text", "Other statement"), ("span_indices", [1])]:
            with self.subTest(statement_field=field):
                changed = copy.deepcopy(packet)
                changed["evidence"][0]["structure"]["semantics"]["statement"][field] = value
                self.assertFalse(evaluate_case(changed, case, suite)["passed"])
        for qualifiers in ([], [{**qualifier, "kind": "condition"}], [{**qualifier, "span_indices": [1]}],
                           [{**qualifier, "exact_text": "except always"}], [qualifier, {**qualifier, "kind": "condition"}]):
            with self.subTest(qualifiers=qualifiers):
                changed = copy.deepcopy(packet)
                changed["evidence"][0]["structure"]["semantics"]["qualifiers"] = qualifiers
                self.assertFalse(evaluate_case(changed, case, suite)["passed"])

    def test_review_binding_and_negative_outcomes(self):
        document = json.loads((ROOT / "benchmarks/real/mil-std-810h-outline-v3.json").read_text())
        suite = validate_suite(document)
        case = next(c for c in suite["cases"] if c["operation"] == "get_clause")
        packet = {"package": {"package_digest": suite["package_digest"], "edition_id": suite["edition_id"]}, "evidence": [], "completeness": {"complete_for_requested_scope": True}}
        verdict = evaluate_case(packet, case, suite)
        self.assertFalse(verdict["passed"])
        codes = {e["code"] for e in verdict["errors"]}
        self.assertTrue({"missing_expected_records", "citation_mismatch", "missing_critical_fact", "incorrect_completeness"} <= codes)
        packet["package"]["edition_id"] = "wrong-edition"
        self.assertIn("wrong_package_or_edition", {e["code"] for e in evaluate_case(packet, case, suite)["errors"]})
        stale = copy.deepcopy(document)
        stale["suite"]["cases"].pop()
        with self.assertRaises(StandardsForgeError):
            validate_suite(stale)
        forged = copy.deepcopy(document)
        forged["suite"]["qualification"] = "corpus_wide_semantics"
        forged["review"]["suite_sha256"] = digest(forged["suite"])
        with self.assertRaises(StandardsForgeError):
            validate_suite(forged)

    def test_run_cannot_omit_cases_or_forge_passing_gate(self):
        document = json.loads((ROOT / "benchmarks/real/mil-std-810h-outline-v3.json").read_text())
        suite = document["suite"]
        packet = {"error": {"code": "not_found"}}
        results = [{"case_id": c["case_id"], "response": packet, "response_sha256": digest(packet), "passed": False,
                    "errors": [{"code": "not_found"}], "expected_records": len(c["expected"]["record_ids"]), "found_expected_records": 0} for c in suite["cases"]]
        run = {"suite_sha256": digest(document), "review": document["review"], "runtime_source_sha256": "0" * 64,
               **{k: suite[k] for k in ("qualification", "package_digest", "edition_id")}, "case_results": results,
               "metrics": {"cases": len(results), "failed_cases": len(results), "expected_records": sum(r["expected_records"] for r in results), "found_expected_records": 0},
               "gate": {"maximum_failed_cases": 0, "passed": False}}
        validate_run({"run": run, "run_sha256": digest(run)}, document)
        run["gate"]["passed"] = True
        with self.assertRaisesRegex(StandardsForgeError, "metric arithmetic"):
            validate_run({"run": run, "run_sha256": digest(run)}, document)
        run["case_results"].pop()
        with self.assertRaisesRegex(StandardsForgeError, "retain every case"):
            validate_run({"run": run, "run_sha256": digest(run)}, document)
