"""Offline answer adjudication with frozen rubrics and source-pinned evidence.

The runner checks bindings and arithmetic. Semantic judgments belong to the
named reviewer; distinct identity strings do not authenticate independence.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .coverage_ledger import digest
from .errors import require
from .reference_bindings import _selector, _evidence


def _object(value: Any, fields: set[str]) -> None:
    require(isinstance(value, dict) and set(value) == fields, "invalid_answer_benchmark", "Answer benchmark fields are closed.")


def _text(value: Any, maximum: int = 32768) -> None:
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum,
            "invalid_answer_benchmark", "Expected bounded nonempty answer benchmark text.")


def _ids(items: Any, key: str, maximum: int = 1000) -> set[str]:
    require(isinstance(items, list) and 1 <= len(items) <= maximum
            and all(isinstance(item, dict) and key in item for item in items),
            "invalid_answer_benchmark", "Expected a nonempty bounded case or criterion array.")
    for item in items:
        _text(item[key], 256)
        require(re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", item[key]) is not None,
                "invalid_answer_benchmark", "Case and criterion IDs must be portable identifiers.")
    values = {item[key] for item in items}
    require(len(values) == len(items), "invalid_answer_benchmark", "Repeated case or criterion identity.")
    return values


def validate_suite(document: Any) -> dict[str, Any]:
    _object(document, {"schema_version", "suite", "suite_sha256"})
    suite = document["suite"]
    _object(suite, {"suite_id", "author_identity", "frozen_at", "qualification", "cases"})
    require(document["schema_version"] == "0.1.0" and document["suite_sha256"] == digest(suite),
            "invalid_answer_benchmark", "Frozen suite content binding failed.")
    require(suite["qualification"] == "bounded_source_grounded_answer_quality", "invalid_answer_benchmark",
            "Selected questions cannot establish corpus-wide answer quality.")
    for key in ("suite_id", "author_identity", "frozen_at"):
        _text(suite[key], 256)
    _ids(suite["cases"], "case_id")
    for case in suite["cases"]:
        _object(case, {"case_id", "question", "evidence", "criteria"})
        _text(case["question"])
        require(isinstance(case["evidence"], list) and 1 <= len(case["evidence"]) <= 32,
                "invalid_answer_benchmark", "Every question needs explicit source-pinned evidence.")
        for selector in case["evidence"]:
            _selector(selector)
        require(len({digest(s) for s in case["evidence"]}) == len(case["evidence"]),
                "invalid_answer_benchmark", "Repeated question evidence selector.")
        _ids(case["criteria"], "criterion_id", 100)
        for criterion in case["criteria"]:
            _object(criterion, {"criterion_id", "requirement", "evidence_indices"})
            _text(criterion["requirement"])
            indices = criterion["evidence_indices"]
            require(isinstance(indices, list) and indices and all(type(i) is int and 0 <= i < len(case["evidence"]) for i in indices)
                    and len(set(indices)) == len(indices), "invalid_answer_benchmark", "Rubric evidence indices must name the selected sources.")
    return suite


def validate_submission(suite_document: Any, submission: Any) -> dict[str, Any]:
    suite = validate_suite(suite_document)
    _object(submission, {"schema_version", "submission", "submission_sha256"})
    body = submission["submission"]
    _object(body, {"suite_sha256", "respondent_identity", "method", "submitted_at", "answers"})
    require(submission["schema_version"] == "0.1.0" and submission["submission_sha256"] == digest(body)
            and body["suite_sha256"] == suite_document["suite_sha256"], "invalid_answer_benchmark",
            "Answer submission is stale or does not match the frozen suite.")
    for key in ("respondent_identity", "method", "submitted_at"):
        _text(body[key])
    require(_ids(body["answers"], "case_id") == {c["case_id"] for c in suite["cases"]},
            "invalid_answer_benchmark", "Every frozen question must have exactly one answer.")
    cases = {c["case_id"]: c for c in suite["cases"]}
    for answer in body["answers"]:
        _object(answer, {"case_id", "text", "citations"})
        _text(answer["text"])
        require(isinstance(answer["citations"], list) and len(answer["citations"]) <= 32,
                "invalid_answer_benchmark", "Citations must be a bounded list.")
        for selector in answer["citations"]:
            _selector(selector)
            require(selector in cases[answer["case_id"]]["evidence"], "invalid_answer_benchmark",
                    "Answer citations must name exact evidence in the frozen question.")
        require(len({digest(s) for s in answer["citations"]}) == len(answer["citations"]),
                "invalid_answer_benchmark", "Repeated answer citation.")
    return body


def validate_adjudication(suite_document: Any, submission: Any, adjudication: Any) -> dict[str, Any]:
    answers = validate_submission(suite_document, submission)
    _object(adjudication, {"schema_version", "adjudication", "adjudication_sha256"})
    body = adjudication["adjudication"]
    _object(body, {"suite_sha256", "submission_sha256", "reviewer", "case_reviews"})
    require(adjudication["schema_version"] == "0.1.0" and adjudication["adjudication_sha256"] == digest(body)
            and body["suite_sha256"] == suite_document["suite_sha256"] and body["submission_sha256"] == submission["submission_sha256"],
            "invalid_answer_benchmark", "Adjudication must bind the exact frozen questions and answer bytes.")
    reviewer = body["reviewer"]
    _object(reviewer, {"identity", "kind", "reviewed_at", "method", "independence_claim"})
    for key in ("identity", "reviewed_at", "method"):
        _text(reviewer[key])
    require(reviewer["kind"] in {"agent", "human"} and reviewer["independence_claim"] in {"self_review", "separate_reviewer"},
            "invalid_answer_benchmark", "Review kind and independence claim must be explicit.")
    identity = reviewer["identity"].strip().casefold()
    if reviewer["independence_claim"] == "separate_reviewer":
        require(identity not in {suite_document["suite"]["author_identity"].strip().casefold(), answers["respondent_identity"].strip().casefold()},
                "invalid_answer_benchmark", "A suite author or answer respondent cannot claim separate adjudication.")
    cases = {c["case_id"]: c for c in suite_document["suite"]["cases"]}
    require(_ids(body["case_reviews"], "case_id") == set(cases), "invalid_answer_benchmark", "Every answer needs exactly one adjudication.")
    for review in body["case_reviews"]:
        _object(review, {"case_id", "answer_verdict", "rationale", "criteria"})
        require(review["answer_verdict"] in {"supported", "contradicted", "insufficient_evidence", "unable_to_assess"},
                "invalid_answer_benchmark", "Each entire answer needs an explicit evidence-support judgment.")
        _text(review["rationale"])
        require(_ids(review["criteria"], "criterion_id", 100) == {c["criterion_id"] for c in cases[review["case_id"]]["criteria"]},
                "invalid_answer_benchmark", "Every frozen criterion must be judged exactly once.")
        for criterion in review["criteria"]:
            _object(criterion, {"criterion_id", "verdict", "rationale"})
            require(criterion["verdict"] in {"pass", "fail", "unable_to_assess"}, "invalid_answer_benchmark", "Invalid criterion judgment.")
            _text(criterion["rationale"])
    return body


def run_answer_benchmark(service: Any, principal: str, suite_document: Any, submission: Any, adjudication: Any) -> dict[str, Any]:
    review = validate_adjudication(suite_document, submission, adjudication)
    require(service.store.read_only, "invalid_answer_benchmark", "Answer qualification requires an existing read-only store.")
    state = service.store.cache_state(principal)
    packets, packages = {}, set()
    for case in suite_document["suite"]["cases"]:
        packets[case["case_id"]] = []
        for selector in case["evidence"]:
            packets[case["case_id"]].append(_evidence(service, selector, principal))
            packages.add(selector["package_digest"])
    answers = {a["case_id"]: a for a in submission["submission"]["answers"]}
    results = []
    for case_review in review["case_reviews"]:
        # Passing a wording rubric is insufficient if the full answer contains an
        # unsupported assertion, an unjudged criterion, or no source citation.
        cited = {digest(s) for s in answers[case_review["case_id"]]["citations"]}
        case = next(c for c in suite_document["suite"]["cases"] if c["case_id"] == case_review["case_id"])
        citation_coverage = all(all(digest(case["evidence"][i]) in cited for i in criterion["evidence_indices"])
                                for criterion in case["criteria"])
        passed = (case_review["answer_verdict"] == "supported" and citation_coverage
                  and all(c["verdict"] == "pass" for c in case_review["criteria"]))
        results.append({"case_id": case_review["case_id"], "passed": passed, "citation_coverage": citation_coverage,
                        "evidence": packets[case_review["case_id"]]})
    criteria = [c for case in review["case_reviews"] for c in case["criteria"]]
    metrics = {"cases": len(results), "passed_cases": sum(r["passed"] for r in results),
               "failed_cases": sum(not r["passed"] for r in results), "criteria": len(criteria),
               "passed_criteria": sum(c["verdict"] == "pass" for c in criteria),
               "failed_criteria": sum(c["verdict"] == "fail" for c in criteria),
               "unassessed_criteria": sum(c["verdict"] == "unable_to_assess" for c in criteria)}
    source_root = Path(__file__).parent
    runtime = digest({p.relative_to(source_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_root.rglob('*.py'))})
    run = {"suite": suite_document, "submission": submission, "adjudication": adjudication,
           "runtime_source_sha256": runtime, "results": results, "metrics": metrics,
           "gate": {"passed": metrics["failed_cases"] == 0, "maximum_failed_cases": 0},
           "qualification": {"scope": "bounded_source_grounded_answer_quality",
                             "separate_reviewer_claim": review["reviewer"]["independence_claim"] == "separate_reviewer",
                             "reviewer_identity_authenticated": False, "corpus_wide_quality_established": False,
                             "suite_freeze": "content_bound_without_external_timestamp"},
           "limitations": ["Semantic verdicts are the named reviewer's judgments; the runner validates bindings and arithmetic.",
                           "Distinct identity strings do not authenticate independence, human approval, or a blinded holdout.",
                           "These selected questions do not estimate corpus-wide accuracy, live model behavior, or retrieval recall."]}
    for pin in sorted(packages):
        service.store.authorized_package(principal, pin)
    require(service.store.cache_state(principal) == state, "authorization_changed", "Authorization changed during answer qualification.")
    return {"schema_version": "0.1.0", "run": run, "run_sha256": digest(run)}
