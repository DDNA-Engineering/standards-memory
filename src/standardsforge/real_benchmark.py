"""Bounded, source-pinned real-document regressions, separate from synthetic CI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .coverage_ledger import digest
from .errors import StandardsForgeError, require
from .service import StandardsForgeService


def validate_suite(document: dict[str, Any]) -> dict[str, Any]:
    require(isinstance(document, dict) and set(document) == {"suite", "review"}, "invalid_real_suite", "Suite envelope fields are closed.")
    suite, review = document["suite"], document["review"]
    require(isinstance(suite, dict) and set(suite) == {"suite_id", "qualification", "package_digest", "edition_id", "cases"}, "invalid_real_suite", "Suite fields are closed.")
    require(suite["qualification"] == "bounded_real_document_regression", "invalid_real_suite", "A bounded regression cannot assert corpus-wide quality.")
    require(isinstance(review, dict) and set(review) == {"kind", "identity", "reviewed_at", "suite_sha256"}
            and review["kind"] in {"agent", "human"} and review["suite_sha256"] == digest(suite)
            and all(isinstance(review[k], str) and review[k].strip() for k in review), "invalid_real_suite", "Exact reviewed suite binding is required.")
    StandardsForgeService._validate_package_digest(suite["package_digest"])
    require(isinstance(suite["cases"], list) and 1 <= len(suite["cases"]) <= 1000, "invalid_real_suite", "Require 1 to 1000 explicit cases.")
    seen = set()
    for case in suite["cases"]:
        require(isinstance(case, dict) and set(case) == {"case_id", "operation", "request", "expected"}, "invalid_real_suite", "Case fields are closed.")
        require(isinstance(case["case_id"], str) and case["case_id"] and case["case_id"] not in seen, "invalid_real_suite", "Case IDs must be unique.")
        seen.add(case["case_id"])
        allowed = {"get_clause": {"record_id"}, "search": {"query", "query_mode", "limit"}, "enumerate_obligations": {"scope_prefix", "limit"}}
        require(case["operation"] in allowed and isinstance(case["request"], dict) and set(case["request"]) == allowed[case["operation"]], "invalid_real_suite", "Only bounded query requests are accepted.")
        expected = case["expected"]
        required = {"record_ids", "forbidden_record_ids", "citations", "critical_facts", "complete_for_requested_scope"}
        require(isinstance(expected, dict) and required <= set(expected) <= required | {"semantic_assertions"}, "invalid_real_suite", "Expectation fields are closed.")
        for key in ("record_ids", "forbidden_record_ids", "critical_facts"):
            require(isinstance(expected[key], list) and all(isinstance(v, str) and v for v in expected[key]) and len(expected[key]) == len(set(expected[key])), "invalid_real_suite", "Expectation lists must contain unique strings.")
        require(expected["complete_for_requested_scope"] is None or type(expected["complete_for_requested_scope"]) is bool, "invalid_real_suite", "Completeness must be explicit.")
        require(isinstance(expected["citations"], list), "invalid_real_suite", "Citations must be an array.")
        for citation in expected["citations"]:
            require(isinstance(citation, dict) and set(citation) == {"record_id", "page", "source_sha256", "quote_sha256"}
                    and citation["record_id"] in expected["record_ids"] and type(citation["page"]) is int and citation["page"] > 0, "invalid_real_suite", "Expected citations must bind expected records.")
            for key in ("source_sha256", "quote_sha256"):
                StandardsForgeService._validate_package_digest(citation[key])
        if case["operation"] == "get_clause":
            require(expected["record_ids"] and set(expected["record_ids"]) == {c["record_id"] for c in expected["citations"]}, "invalid_real_suite", "Every expected evidence record needs a source citation.")
        assertions = expected.get("semantic_assertions", [])
        require(isinstance(assertions, list), "invalid_real_suite", "Semantic assertions must be an array.")
        for assertion in assertions:
            require(isinstance(assertion, dict) and set(assertion) == {"record_id", "content_role", "statement", "qualifiers"}
                    and assertion["record_id"] in expected["record_ids"] and case["operation"] != "search",
                    "invalid_real_suite", "Semantic assertions must name expected detailed evidence.")
            require(isinstance(assertion["content_role"], str) and assertion["content_role"]
                    and isinstance(assertion["qualifiers"], list), "invalid_real_suite", "Invalid semantic expectation.")
            statement = assertion["statement"]
            if statement is not None:
                require(isinstance(statement, dict) and set(statement) == {"subject", "action", "modality", "polarity", "exact_text", "span_indices"}
                        and all(isinstance(statement[k], str) and statement[k].strip() for k in ("subject", "action", "exact_text"))
                        and statement["modality"] in {"shall", "must", "should", "may", "will", "other"}
                        and statement["polarity"] in {"affirmative", "negative"}, "invalid_real_suite", "A semantic expectation must bind the complete statement.")
                _validate_span_indices(statement["span_indices"])
            for qualifier in assertion["qualifiers"]:
                require(isinstance(qualifier, dict) and set(qualifier) == {"kind", "exact_text", "span_indices"}
                        and qualifier["kind"] in {"condition", "exception", "source_applicability", "test_condition", "acceptance_criterion", "tailoring_instruction"}
                        and isinstance(qualifier["exact_text"], str) and qualifier["exact_text"].strip(),
                        "invalid_real_suite", "A qualifier expectation must bind its type, text, and spans.")
                _validate_span_indices(qualifier["span_indices"])
    return suite


def _validate_span_indices(indices: Any) -> None:
    require(isinstance(indices, list) and indices and all(type(i) is int and i >= 0 for i in indices)
            and len(indices) == len(set(indices)), "invalid_real_suite", "Semantic evidence needs distinct nonnegative span indices.")


def evaluate_case(packet: dict[str, Any], case: dict[str, Any], suite: dict[str, Any]) -> dict[str, Any]:
    operation = case["operation"]
    if operation == "get_clause":
        records = packet["evidence"]
    elif operation == "search":
        records = packet["results"]
    else:
        records = [r for obligation in packet["obligations"] for r in obligation["evidence"]]
    by_id = {r["record_id"]: r for r in records}
    expected = case["expected"]
    errors = []
    missing = sorted(set(expected["record_ids"]) - set(by_id))
    forbidden = sorted(set(expected["forbidden_record_ids"]) & set(by_id))
    if missing:
        errors.append({"code": "missing_expected_records", "record_ids": missing})
    if forbidden:
        errors.append({"code": "forbidden_records", "record_ids": forbidden})
    identities = records if operation == "search" else [packet["package"]]
    if any(r["package_digest"] != suite["package_digest"] or r["edition_id"] != suite["edition_id"] for r in identities):
        errors.append({"code": "wrong_package_or_edition"})
    for citation in expected["citations"]:
        record = by_id.get(citation["record_id"])
        actual = record.get("citation", record.get("source", {})) if record else {}
        if actual.get("page") != citation["page"] or actual.get("source_sha256", actual.get("sha256")) != citation["source_sha256"] or actual.get("quote_sha256") != citation["quote_sha256"]:
            errors.append({"code": "citation_mismatch", "record_id": citation["record_id"]})
        if record and operation != "search" and hashlib.sha256(record["text"].encode("utf-8")).hexdigest() != citation["quote_sha256"]:
            errors.append({"code": "quote_mismatch", "record_id": citation["record_id"]})
    texts = "\n".join(r.get("text", "") for r in records)
    for fact in expected["critical_facts"]:
        if fact not in texts:
            errors.append({"code": "missing_critical_fact", "fact": fact})
    for assertion in expected.get("semantic_assertions", []):
        record = by_id.get(assertion["record_id"], {})
        semantics = (record.get("structure") or {}).get("semantics") or {}
        if (semantics.get("content_role") != assertion["content_role"] or semantics.get("statement") != assertion["statement"]
                or semantics.get("qualifiers") != assertion["qualifiers"]):
            errors.append({"code": "semantic_mismatch", "record_id": assertion["record_id"]})
    complete = expected["complete_for_requested_scope"]
    if complete is not None and packet.get("completeness", {}).get("complete_for_requested_scope") is not complete:
        errors.append({"code": "incorrect_completeness"})
    return {"passed": not errors, "errors": errors, "expected_records": len(expected["record_ids"]), "found_expected_records": len(expected["record_ids"]) - len(missing)}


def run_real_benchmark(service: StandardsForgeService, principal: str, document: dict[str, Any]) -> dict[str, Any]:
    suite = validate_suite(document)
    require(service.store.read_only, "invalid_real_suite", "Real qualification must use a read-only store.")
    package = service.store.authorized_package(principal, suite["package_digest"])
    require(package["edition_id"] == suite["edition_id"], "invalid_real_suite", "Suite edition differs from the pinned package.")
    require(json.loads(package["rights_json"])["content_class"] != "synthetic", "invalid_real_suite", "Synthetic packs cannot qualify a real-document regression.")
    results = []
    for case in suite["cases"]:
        try:
            packet = getattr(service, case["operation"])(package_digest=suite["package_digest"], principal_id=principal, **case["request"])
            verdict = evaluate_case(packet, case, suite)
        except StandardsForgeError as exc:
            packet = {"error": exc.as_dict()}
            verdict = {"passed": False, "errors": [{"code": exc.code}], "expected_records": len(case["expected"]["record_ids"]), "found_expected_records": 0}
        results.append({"case_id": case["case_id"], **verdict, "response": packet, "response_sha256": digest(packet)})
    failures = sum(not result["passed"] for result in results)
    module_root = Path(__file__).resolve().parent
    runtime_source_digest = digest({p.relative_to(module_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(module_root.rglob("*.py"))})
    body = {"suite_sha256": digest(document), "qualification": suite["qualification"], "review": document["review"],
            "runtime_source_sha256": runtime_source_digest,
            "package_digest": suite["package_digest"], "edition_id": suite["edition_id"], "case_results": results,
            "metrics": {"cases": len(results), "failed_cases": failures, "expected_records": sum(r["expected_records"] for r in results), "found_expected_records": sum(r["found_expected_records"] for r in results)},
            "gate": {"maximum_failed_cases": 0, "passed": failures == 0},
            "limitations": ["Selected source-text regressions do not measure corpus-wide recall or PDF visual fidelity.", "Reviewer provenance is a claim, not authenticated human approval.", "Tokenizer efficiency and engineer time are not measured."]}
    artifact = {"schema_version": "0.1.0", "run": body, "run_sha256": digest(body)}
    validate_run(artifact, document)
    return artifact


def validate_run(artifact: dict[str, Any], document: dict[str, Any]) -> None:
    suite = validate_suite(document)
    run = artifact["run"]
    require(artifact["run_sha256"] == digest(run) and run["suite_sha256"] == digest(document), "invalid_real_run", "Run content binding failed.")
    require(all(run.get(key) == suite[key] for key in ("qualification", "package_digest", "edition_id")) and run.get("review") == document["review"], "invalid_real_run", "Run identity or review differs from its suite.")
    StandardsForgeService._validate_package_digest(run.get("runtime_source_sha256"))
    require([r["case_id"] for r in run["case_results"]] == [c["case_id"] for c in suite["cases"]], "invalid_real_run", "Run must retain every case in order.")
    for result, case in zip(run["case_results"], suite["cases"]):
        packet = result["response"]
        require(result["response_sha256"] == digest(packet), "invalid_real_run", "Raw response digest mismatch.")
        verdict = (evaluate_case(packet, case, suite) if "error" not in packet else
                   {"passed": False, "errors": [{"code": packet["error"]["code"]}], "expected_records": len(case["expected"]["record_ids"]), "found_expected_records": 0})
        require(all(result[k] == value for k, value in verdict.items()), "invalid_real_run", "Run verdict does not match retained response.")
    results = run["case_results"]
    metrics = {"cases": len(results), "failed_cases": sum(not r["passed"] for r in results),
               "expected_records": sum(r["expected_records"] for r in results), "found_expected_records": sum(r["found_expected_records"] for r in results)}
    require(run["metrics"] == metrics and run["gate"] == {"maximum_failed_cases": 0, "passed": metrics["failed_cases"] == 0}, "invalid_real_run", "Gate or metric arithmetic mismatch.")
