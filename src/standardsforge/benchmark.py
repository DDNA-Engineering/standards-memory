from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from jsonschema import FormatChecker
from jsonschema.validators import validator_for

from . import __version__
from .errors import StandardsForgeError
from .pack import validate_pack_directory
from .policy import load_policy
from .service import StandardsForgeService


RUNNER_VERSION = "0.1.0"
DEFAULT_POLICY = Path("examples/policies/local-synthetic.json")


class BenchmarkContractError(ValueError):
    """A benchmark artifact is malformed or not bound to its declared content."""


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BenchmarkContractError("Benchmark content is not canonical JSON data.") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkContractError(f"Cannot read JSON artifact: {path}") from exc


def _validator(schema_path: Path):
    schema = _load_json(schema_path)
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    return validator_class(schema, format_checker=FormatChecker())


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    errors = sorted(_validator(schema_path).iter_errors(instance), key=lambda item: list(item.absolute_path))
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise BenchmarkContractError(f"{label} fails schema at {location}: {error.message}")


def validate_suite_document(document: Any, root: Path) -> dict[str, Any]:
    _validate_schema(document, root / "contracts/benchmark-suite.schema.json", "Benchmark suite")
    suite = document["suite"]
    actual_review_digest = _digest(suite)
    if document["review"]["reviewed_content_sha256"] != actual_review_digest:
        raise BenchmarkContractError("Benchmark review digest does not match canonical suite content.")

    bindings = suite["source_bindings"]
    binding_ids = [item["binding_id"] for item in bindings]
    if len(binding_ids) != len(set(binding_ids)):
        raise BenchmarkContractError("Benchmark binding IDs must be unique.")
    case_ids = [item["case_id"] for item in suite["cases"]]
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkContractError("Benchmark case IDs must be unique.")

    known_bindings = set(binding_ids)
    for case in suite["cases"]:
        request = case["request"]
        references = [
            request[key]
            for key in ("package_binding", "from_binding", "to_binding")
            if key in request
        ]
        expected_binding = case["expectations"]["expected_binding"]
        if expected_binding is not None:
            references.append(expected_binding)
        unknown = sorted(set(references) - known_bindings)
        if unknown:
            raise BenchmarkContractError(f"Case {case['case_id']} references unknown bindings: {unknown}")
        if case["operation"] == "diff_editions" and request["from_binding"] == request["to_binding"]:
            raise BenchmarkContractError(f"Case {case['case_id']} compares one binding to itself.")
    return suite


def _safe_pack_path(root: Path, relative: str) -> Path:
    candidate = root.joinpath(*relative.split("/")).resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if not candidate.is_relative_to(resolved_root) or candidate.is_symlink() or not candidate.is_dir():
        raise BenchmarkContractError(f"Benchmark pack path escapes the repository or is not a directory: {relative}")
    current = candidate
    while current != resolved_root:
        if current.is_symlink():
            raise BenchmarkContractError(f"Benchmark pack path traverses a symlink: {relative}")
        current = current.parent
    return candidate


def _representation(manifest: dict[str, Any]) -> str:
    explicit = manifest.get("representation")
    if explicit is not None:
        return explicit
    parsed = manifest["coverage"]["parsed_source_coverage"]
    if parsed.startswith("text_layer_extracted_"):
        return "page_text"
    if parsed.startswith("partial_reviewed_structural_"):
        return "reviewed_structure"
    return "curated_records"


@contextmanager
def _network_denied() -> Iterator[None]:
    def denied(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Network access is denied during benchmark execution.")

    with patch.object(socket, "socket", denied), patch.object(socket, "create_connection", denied):
        yield


def _dispatch(
    service: StandardsForgeService,
    case: dict[str, Any],
    digests: dict[str, str],
    principal_id: str,
) -> dict[str, Any]:
    request = case["request"]
    operation = case["operation"]
    if operation == "resolve_document":
        return service.resolve_document(
            request["identifier"], principal_id, request["edition_id"], request["representation"]
        )
    if operation == "search":
        return service.search(
            request["query"],
            principal_id,
            request["limit"],
            package_digest=digests[request["package_binding"]],
            query_mode=request["query_mode"],
        )
    if operation == "get_clause":
        return service.get_clause(
            digests[request["package_binding"]],
            None,
            principal_id,
            record_id=request["record_id"],
        )
    if operation == "diff_editions":
        return service.diff_editions(
            digests[request["from_binding"]], digests[request["to_binding"]], principal_id
        )
    raise BenchmarkContractError(f"Unsupported benchmark operation: {operation}")


def _error_response(exc: Exception) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
    if isinstance(exc, StandardsForgeError):
        payload["code"] = exc.code
        payload["details"] = exc.details
    return {"benchmark_error": payload}


def _sample(operation: Any, cache_state: str) -> dict[str, Any]:
    started = time.perf_counter_ns()
    try:
        response = operation()
    except Exception as exc:  # preserve every failed case in the run artifact
        response = _error_response(exc)
    elapsed = time.perf_counter_ns() - started
    body = canonical_json(response)
    return {
        "cache_state": cache_state,
        "elapsed_ns": elapsed,
        "response_bytes": len(body),
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "response": response,
    }


def _json_pointer(value: Any, pointer: str) -> Any:
    current = value
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(pointer) from exc
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def _response_records(response: dict[str, Any]) -> list[dict[str, Any]]:
    operation = response.get("operation")
    records: list[dict[str, Any]] = []
    if operation == "search":
        for item in response.get("results", []):
            records.append({"record_id": item.get("record_id"), "package_digest": item.get("package_digest"), "text": item.get("matched_snippet", ""), "citation": item.get("source"), "selector": item.get("evidence_selector"), "response_kind": "search"})
    elif operation == "get_clause":
        package_digest = response.get("package", {}).get("package_digest")
        for item in response.get("evidence", []):
            records.append({"record_id": item.get("record_id"), "package_digest": package_digest, "text": item.get("text", ""), "citation": item.get("citation"), "response_kind": "evidence"})
    elif operation == "diff_editions":
        sides = (("before", response.get("from_package", {}).get("package_digest")), ("after", response.get("to_package", {}).get("package_digest")))
        for change in response.get("changes", []):
            for side, package_digest in sides:
                item = change.get(side)
                if isinstance(item, dict):
                    records.append({"record_id": item.get("record_id"), "package_digest": package_digest, "text": item.get("text", ""), "citation": item.get("citation"), "response_kind": "evidence"})
    return records


def _result_ids(response: dict[str, Any]) -> list[str]:
    operation = response.get("operation")
    if operation == "search":
        return [item["record_id"] for item in response.get("results", [])]
    if operation == "get_clause":
        return [item["record_id"] for item in response.get("evidence", [])]
    if operation == "diff_editions":
        return [item["record_id"] for item in response.get("changes", [])]
    return []


def _result_count(response: dict[str, Any]) -> int:
    if response.get("operation") == "resolve_document":
        return 1
    return len(_result_ids(response))


def _forbidden_claim_count(response: Any) -> int:
    count = 0
    if isinstance(response, dict):
        for key, value in response.items():
            normalized = key.lower()
            if normalized in {"approved", "approval", "compliant", "compliance"} and value not in (False, None, "not_decided", "not_applicable"):
                count += 1
            if normalized == "project_applicability" and value != "not_decided":
                count += 1
            count += _forbidden_claim_count(value)
    elif isinstance(response, list):
        count += sum(_forbidden_claim_count(item) for item in response)
    return count


def _case_assertions(
    case: dict[str, Any],
    response: dict[str, Any],
    warm_response: dict[str, Any],
    binding_by_id: dict[str, dict[str, Any]],
    records_by_digest: dict[str, dict[str, dict[str, Any]]],
    response_validator: Any,
) -> tuple[dict[str, int], list[str], int, int]:
    expected = case["expectations"]
    failures: list[str] = []
    ids = _result_ids(response)
    id_set = set(ids)
    records = _response_records(response)

    relevant_expected = set(expected["relevant_record_ids"])
    required_expected = set(expected["required_record_ids"])
    relevant_found = len(relevant_expected & id_set)
    required_found = len(required_expected & id_set)
    if relevant_found != len(relevant_expected):
        failures.append("missing_relevant_records")
    if required_found != len(required_expected):
        failures.append("missing_required_context")
    if set(expected["forbidden_record_ids"]) & id_set:
        failures.append("forbidden_records_returned")

    text_by_record: dict[str, list[str]] = {}
    for item in records:
        text_by_record.setdefault(str(item["record_id"]), []).append(str(item["text"]))
    critical_found = sum(
        1
        for fact in expected["critical_facts"]
        if any(fact["exact_text"] in text for text in text_by_record.get(fact["record_id"], []))
    )
    if critical_found != len(expected["critical_facts"]):
        failures.append("lost_critical_facts")
    forbidden_facts_found = sum(
        1
        for fact in expected["forbidden_facts"]
        if any(fact["exact_text"] in text for text in text_by_record.get(fact["record_id"], []))
    )
    if forbidden_facts_found:
        failures.append("forbidden_facts_returned")

    wrong_edition = 0
    identity_checks = 0
    expected_binding_id = expected["expected_binding"]
    if expected_binding_id is not None:
        expected_digest = binding_by_id[expected_binding_id]["package_digest"]
        if response.get("operation") == "resolve_document":
            identity_checks = 1
            wrong_edition = int(response.get("package_digest") != expected_digest)
        elif response.get("operation") == "get_clause":
            identity_checks = 1
            wrong_edition = int(response.get("package", {}).get("package_digest") != expected_digest)
        else:
            identity_checks = len(records)
            wrong_edition = sum(item["package_digest"] != expected_digest for item in records)
    elif response.get("operation") == "diff_editions":
        request = case["request"]
        identity_checks = 2
        wrong_edition = int(response.get("from_package", {}).get("package_digest") != binding_by_id[request["from_binding"]]["package_digest"])
        wrong_edition += int(response.get("to_package", {}).get("package_digest") != binding_by_id[request["to_binding"]]["package_digest"])
    if wrong_edition:
        failures.append("wrong_edition_results")

    citation_mismatches = 0
    citation_checks = 0
    for item in records:
        citation = item["citation"]
        record = records_by_digest.get(str(item["package_digest"]), {}).get(str(item["record_id"]))
        if not isinstance(citation, dict) or record is None:
            citation_mismatches += 1
            citation_checks += 1
            continue
        citation_checks += 1
        source = record["source"]
        compared = {
            "path": citation.get("path", citation.get("source_path")),
            "sha256": citation.get("sha256", citation.get("source_sha256")),
            "page": citation.get("page"),
            "locator": citation.get("locator"),
            "quote_sha256": citation.get("quote_sha256"),
        }
        expected_source = {key: source.get(key) for key in compared}
        text_matches = item["text"] == record["text"]
        if item["response_kind"] == "search":
            highlights: list[str] = []
            remainder = str(item["text"])
            while "⟦" in remainder and "⟧" in remainder:
                _, marked = remainder.split("⟦", 1)
                highlighted, remainder = marked.split("⟧", 1)
                highlights.append(highlighted)
            selector = item.get("selector")
            text_matches = bool(highlights) and all(
                highlighted.casefold() in record["text"].casefold()
                for highlighted in highlights
            ) and selector == {
                "operation": "get_clause",
                "package_digest": item["package_digest"],
                "record_id": item["record_id"],
                "clause_reference": record["clause_reference"],
            }
        returned_quote_matches = (
            item["response_kind"] == "search"
            or hashlib.sha256(str(item["text"]).encode("utf-8")).hexdigest()
            == citation.get("quote_sha256")
        )
        if (
            compared != expected_source
            or hashlib.sha256(record["text"].encode("utf-8")).hexdigest()
            != source["quote_sha256"]
            or not text_matches
            or not returned_quote_matches
        ):
            citation_mismatches += 1
    if citation_mismatches:
        failures.append("citation_mismatches")

    false_complete = 0
    if expected["answerability"] == "outside_baseline":
        complete = response.get("completeness", {}).get("database_traversal", {}).get("complete")
        false_complete = int(complete is True)
        if false_complete:
            failures.append("false_complete_result")

    forbidden_claims = _forbidden_claim_count(response)
    if forbidden_claims:
        failures.append("forbidden_claims_returned")

    revision_mismatches = 0
    if expected["expected_change_statuses"]:
        actual = {item.get("record_id"): item.get("status") for item in response.get("changes", [])}
        revision_mismatches = sum(actual.get(record_id) != status for record_id, status in expected["expected_change_statuses"].items())
        if revision_mismatches:
            failures.append("revision_status_mismatches")

    result_count_mismatches = 0
    if expected["expected_result_count"] is not None:
        result_count_mismatches = int(_result_count(response) != expected["expected_result_count"])
        if result_count_mismatches:
            failures.append("result_count_mismatch")

    json_mismatches = 0
    for expectation in expected["required_json_values"]:
        try:
            actual = _json_pointer(response, expectation["pointer"])
        except KeyError:
            actual = object()
        if actual != expectation["value"]:
            json_mismatches += 1
    if json_mismatches:
        failures.append("required_json_value_mismatch")

    response_schema_mismatches = len(list(response_validator.iter_errors(response)))
    if response_schema_mismatches:
        failures.append("response_schema_mismatch")
    warm_mismatches = int(canonical_json(response) != canonical_json(warm_response))
    if warm_mismatches:
        failures.append("warm_response_mismatch")

    assertions = {
        "relevant_expected": len(relevant_expected), "relevant_found": relevant_found,
        "required_context_expected": len(required_expected), "required_context_found": required_found,
        "critical_facts_expected": len(expected["critical_facts"]), "critical_facts_found": critical_found,
        "wrong_edition_results": wrong_edition, "citation_mismatches": citation_mismatches,
        "false_complete_results": false_complete, "forbidden_facts_found": forbidden_facts_found,
        "forbidden_claims_found": forbidden_claims, "revision_mismatches": revision_mismatches,
        "result_count_mismatches": result_count_mismatches, "json_value_mismatches": json_mismatches,
        "response_schema_mismatches": response_schema_mismatches, "warm_response_mismatches": warm_mismatches,
    }
    return assertions, sorted(set(failures)), identity_checks, citation_checks


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator < 1 or numerator > denominator:
        raise BenchmarkContractError("Measured ratios require 0 <= numerator <= denominator and a positive denominator.")
    return {"status": "measured", "numerator": numerator, "denominator": denominator, "value": numerator / denominator, "unit": "ratio"}


def _ratio_or_not_measured(numerator: int, denominator: int, reason: str) -> dict[str, Any]:
    return _ratio(numerator, denominator) if denominator else _not_measured(reason)


def _not_measured(reason: str) -> dict[str, str]:
    return {"status": "not_measured", "reason": reason}


def _git_identity(root: Path) -> dict[str, Any]:
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)

    commit_result = run("rev-parse", "HEAD")
    status_result = run("status", "--porcelain")
    commit = commit_result.stdout.strip().lower()
    if commit_result.returncode != 0 or len(commit) != 40:
        commit = None
    dirty = status_result.returncode != 0 or bool(status_result.stdout.strip())
    return {"git_commit": commit, "git_dirty": dirty}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _expected_metrics(
    case_results: list[dict[str, Any]],
    suite_cases: list[dict[str, Any]],
    identity_checks: int,
    citation_checks: int,
) -> dict[str, Any]:
    assertions = [result["assertions"] for result in case_results]
    discovery_indices = [
        index
        for index, case in enumerate(suite_cases)
        if case["operation"] == "search" and case["dimension"] == "discovery"
    ]
    relevant_expected = sum(assertions[index]["relevant_expected"] for index in discovery_indices)
    relevant_found = sum(assertions[index]["relevant_found"] for index in discovery_indices)
    required_expected = sum(item["required_context_expected"] for item in assertions)
    required_found = sum(item["required_context_found"] for item in assertions)
    facts_expected = sum(item["critical_facts_expected"] for item in assertions)
    facts_found = sum(item["critical_facts_found"] for item in assertions)
    wrong_editions = sum(item["wrong_edition_results"] for item in assertions)
    citation_mismatches = sum(item["citation_mismatches"] for item in assertions)
    outside_cases = sum(
        case["expectations"]["answerability"] == "outside_baseline"
        for case in suite_cases
    )
    false_complete = sum(item["false_complete_results"] for item in assertions)
    total_response_bytes = sum(
        result[state]["response_bytes"]
        for result in case_results
        for state in ("cold", "warm")
    )
    sample_count = len(case_results) * 2
    return {
        "case_pass_rate": _ratio(sum(result["passed"] for result in case_results), len(case_results)),
        "discovery_recall_at_k": _ratio_or_not_measured(relevant_found, relevant_expected, "No discovery cases declare relevant records."),
        "required_context_recall": _ratio_or_not_measured(required_found, required_expected, "No cases declare required context."),
        "critical_fact_exact_match": _ratio_or_not_measured(facts_found, facts_expected, "No cases declare critical facts."),
        "wrong_edition_rate": _ratio_or_not_measured(wrong_editions, identity_checks, "No package or edition identities were checked."),
        "citation_mismatch_rate": _ratio_or_not_measured(citation_mismatches, citation_checks, "No returned records carried citations."),
        "false_complete_rate": _ratio_or_not_measured(false_complete, outside_cases, "No outside-baseline cases were declared."),
        "all_case_response_bytes": {"status": "measured", "numerator": total_response_bytes, "denominator": sample_count, "value": total_response_bytes / sample_count, "unit": "bytes_per_sample"},
        "real_document_discovery_accuracy": _not_measured("Only fictional synthetic packs are in scope."),
        "real_document_semantic_fidelity": _not_measured("No human-reviewed real-document corpus is in scope."),
        "tokenizer_normalized_efficiency": _not_measured("No tokenizer is used by this benchmark."),
        "peak_process_resources": _not_measured("Peak process resources are not sampled."),
        "engineer_time_saved": _not_measured("Engineer time requires a separate human study."),
    }


def validate_run_artifact(document: Any, suite_document: Any, root: Path) -> None:
    _validate_schema(document, root / "contracts/benchmark-run.schema.json", "Benchmark run")
    suite = validate_suite_document(suite_document, root)
    run = document["run"]
    if document["run_content_sha256"] != _digest(run):
        raise BenchmarkContractError("Benchmark run digest does not match canonical run content.")
    if run["suite"]["suite_sha256"] != _digest(suite_document):
        raise BenchmarkContractError("Benchmark run is not bound to the canonical suite document.")
    expected_ids = [case["case_id"] for case in suite["cases"]]
    result_ids = [result["case_id"] for result in run["case_results"]]
    if result_ids != expected_ids or len(result_ids) != len(set(result_ids)):
        raise BenchmarkContractError("Benchmark run must contain each suite case exactly once in suite order.")

    binding_by_id = {item["binding_id"]: item for item in suite["source_bindings"]}
    records_by_digest: dict[str, dict[str, dict[str, Any]]] = {}
    observed_bindings: list[dict[str, Any]] = []
    for binding in suite["source_bindings"]:
        pack = validate_pack_directory(_safe_pack_path(root, binding["pack_path"]))
        observed = {
            "binding_id": binding["binding_id"], "package_digest": pack.package_digest,
            "pack_id": pack.manifest["pack_id"], "edition_id": pack.manifest["edition_id"],
            "representation": _representation(pack.manifest), "content_class": pack.rights["content_class"],
        }
        if observed != {key: binding[key] for key in observed}:
            raise BenchmarkContractError(f"Binding {binding['binding_id']} no longer matches its validated pack.")
        observed_bindings.append(observed)
        records_by_digest[pack.package_digest] = {
            record["record_id"]: record for record in pack.records
        }
    if run["observed_source_bindings"] != observed_bindings:
        raise BenchmarkContractError("Benchmark observed bindings do not match the suite and validated packs.")
    if run["runner"]["sha256"] != hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest():
        raise BenchmarkContractError("Benchmark runner digest does not match the validating source.")

    response_validator = _validator(root / "contracts/query-response.schema.json")
    identity_checks = 0
    citation_checks = 0
    for case, result in zip(suite["cases"], run["case_results"], strict=True):
        if result["dimension"] != case["dimension"] or result["operation"] != case["operation"]:
            raise BenchmarkContractError(f"Case {result['case_id']} metadata does not match the suite.")
        assertions, failures, checked_identities, checked_citations = _case_assertions(
            case,
            result["cold"]["response"],
            result["warm"]["response"],
            binding_by_id,
            records_by_digest,
            response_validator,
        )
        identity_checks += checked_identities
        citation_checks += checked_citations
        if result["assertions"] != assertions or result["failures"] != failures or result["passed"] != (not failures):
            raise BenchmarkContractError(f"Case {result['case_id']} stored evaluation does not match its raw responses.")

    for result in run["case_results"]:
        for key in ("cold", "warm"):
            sample = result[key]
            body = canonical_json(sample["response"])
            if sample["response_bytes"] != len(body) or sample["response_sha256"] != hashlib.sha256(body).hexdigest():
                raise BenchmarkContractError(f"Case {result['case_id']} has a mismatched {key} response digest or byte count.")
        if result["passed"] != (not result["failures"]):
            raise BenchmarkContractError(f"Case {result['case_id']} pass state conflicts with its failures.")

    passed = sum(result["passed"] for result in run["case_results"])
    failed = len(result_ids) - passed
    summary = run["summary"]
    if summary != {"overall_passed": failed == 0, "case_count": len(result_ids), "passed_count": passed, "failed_count": failed}:
        raise BenchmarkContractError("Benchmark summary arithmetic does not match case results.")

    assertions = [result["assertions"] for result in run["case_results"]]
    observed = {
        "failed_cases": failed,
        "wrong_edition_results": sum(item["wrong_edition_results"] for item in assertions),
        "citation_mismatches": sum(item["citation_mismatches"] for item in assertions),
        "lost_critical_facts": sum(item["critical_facts_expected"] - item["critical_facts_found"] for item in assertions),
        "missing_required_context": sum(item["required_context_expected"] - item["required_context_found"] for item in assertions),
        "false_complete_results": sum(item["false_complete_results"] for item in assertions),
    }
    gate = run["release_gate"]
    if gate["maximums"] != suite["release_blocking_max"] or gate["observed"] != observed:
        raise BenchmarkContractError("Benchmark release gate does not match suite thresholds or observed assertions.")
    gate_passed = all(observed[key] <= gate["maximums"][key] for key in observed)
    if gate["passed"] != gate_passed or summary["overall_passed"] != gate_passed:
        raise BenchmarkContractError("Benchmark pass state does not match the release gate.")

    expected_metrics = _expected_metrics(
        run["case_results"], suite["cases"], identity_checks, citation_checks
    )
    if run["metrics"] != expected_metrics:
        raise BenchmarkContractError("Benchmark metrics do not match the suite and raw case results.")

    for name, metric in run["metrics"].items():
        if metric["status"] != "measured":
            continue
        if metric["numerator"] > metric["denominator"] and metric["unit"] == "ratio":
            raise BenchmarkContractError(f"Metric {name} has numerator greater than denominator.")
        expected_value = metric["numerator"] / metric["denominator"]
        if metric["value"] != expected_value:
            raise BenchmarkContractError(f"Metric {name} value does not match its numerator and denominator.")


def run_benchmark(
    suite_path: Path,
    *,
    root: Path,
    policy_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    suite_path = suite_path.resolve(strict=True)
    suite_document = _load_json(suite_path)
    suite = validate_suite_document(suite_document, root)
    policy_file = (root / DEFAULT_POLICY if policy_path is None else policy_path).resolve(strict=True)
    policy = load_policy(policy_file)
    if suite["principal_id"] != policy.principal_id:
        raise BenchmarkContractError("Suite principal must match the trusted local policy principal.")

    binding_by_id = {item["binding_id"]: item for item in suite["source_bindings"]}
    pack_paths: dict[str, Path] = {}
    records_by_digest: dict[str, dict[str, dict[str, Any]]] = {}
    observed_bindings: list[dict[str, Any]] = []
    for binding in suite["source_bindings"]:
        path = _safe_pack_path(root, binding["pack_path"])
        pack = validate_pack_directory(path)
        observed = {
            "binding_id": binding["binding_id"], "package_digest": pack.package_digest,
            "pack_id": pack.manifest["pack_id"], "edition_id": pack.manifest["edition_id"],
            "representation": _representation(pack.manifest), "content_class": pack.rights["content_class"],
        }
        expected = {key: binding[key] for key in observed}
        if observed != expected:
            raise BenchmarkContractError(f"Binding {binding['binding_id']} does not match its validated pack content.")
        if pack.manifest["pack_id"] not in policy.allowed_pack_ids or pack.rights["content_class"] not in policy.allowed_content_classes:
            raise BenchmarkContractError(f"Trusted policy does not authorize binding {binding['binding_id']}.")
        pack_paths[binding["binding_id"]] = path
        records_by_digest[pack.package_digest] = {record["record_id"]: record for record in pack.records}
        observed_bindings.append(observed)

    started_at = _utc_now()
    response_validator = _validator(root / "contracts/query-response.schema.json")
    case_results: list[dict[str, Any]] = []
    identity_checks = 0
    citation_checks = 0
    with tempfile.TemporaryDirectory(prefix="standardsforge-benchmark-") as temporary:
        base = Path(temporary)
        db_path = base / "benchmark.db"
        object_root = base / "objects"
        installer = StandardsForgeService(db_path, object_root)
        with _network_denied():
            for binding_id in binding_by_id:
                installed = installer.install_pack(pack_paths[binding_id], policy_file)
                if installed["package_digest"] != binding_by_id[binding_id]["package_digest"]:
                    raise BenchmarkContractError(f"Installed digest drifted for binding {binding_id}.")

            digests = {key: value["package_digest"] for key, value in binding_by_id.items()}
            for case in suite["cases"]:
                service = StandardsForgeService(db_path, object_root)
                operation = lambda: _dispatch(service, case, digests, suite["principal_id"])
                cold = _sample(operation, "service_cache_cold")
                warm = _sample(operation, "immediate_repeat_warm")
                assertions, failures, checked_identities, checked_citations = _case_assertions(
                    case, cold["response"], warm["response"], binding_by_id, records_by_digest, response_validator
                )
                identity_checks += checked_identities
                citation_checks += checked_citations
                case_results.append({
                    "case_id": case["case_id"], "dimension": case["dimension"], "operation": case["operation"],
                    "passed": not failures, "failures": failures, "cold": cold, "warm": warm, "assertions": assertions,
                })

    finished_at = _utc_now()
    passed_count = sum(result["passed"] for result in case_results)
    failed_count = len(case_results) - passed_count
    assertions = [result["assertions"] for result in case_results]
    required_expected = sum(item["required_context_expected"] for item in assertions)
    required_found = sum(item["required_context_found"] for item in assertions)
    facts_expected = sum(item["critical_facts_expected"] for item in assertions)
    facts_found = sum(item["critical_facts_found"] for item in assertions)
    wrong_editions = sum(item["wrong_edition_results"] for item in assertions)
    citation_mismatches = sum(item["citation_mismatches"] for item in assertions)
    false_complete = sum(item["false_complete_results"] for item in assertions)
    observed_gate = {
        "failed_cases": failed_count, "wrong_edition_results": wrong_editions,
        "citation_mismatches": citation_mismatches, "lost_critical_facts": facts_expected - facts_found,
        "missing_required_context": required_expected - required_found, "false_complete_results": false_complete,
    }
    gate_passed = all(observed_gate[key] <= suite["release_blocking_max"][key] for key in observed_gate)
    runner_path = Path(__file__).resolve()
    runner_sha256 = hashlib.sha256(runner_path.read_bytes()).hexdigest()
    suite_sha256 = _digest(suite_document)
    run_seed = {"suite_sha256": suite_sha256, "started_at": started_at, "runner_sha256": runner_sha256}
    run = {
        "run_id": _digest(run_seed), "started_at": started_at, "finished_at": finished_at,
        "suite": {"suite_id": suite["suite_id"], "suite_version": suite["suite_version"], "suite_sha256": suite_sha256},
        "qualification_class": suite["qualification_class"], "claim_boundary": suite["claim_boundary"],
        "runner": {"name": "standardsforge-benchmark", "version": RUNNER_VERSION, "sha256": runner_sha256},
        "source_identity": _git_identity(root),
        "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(), "standardsforge_version": __version__},
        "policy_fingerprint": policy.fingerprint, "observed_source_bindings": observed_bindings,
        "protocol": {
            "cache_states": ["service_cache_cold", "immediate_repeat_warm"], "repetitions_per_state": 1,
            "timer": "time.perf_counter_ns", "network": "denied_during_install_and_cases",
            "tokenizer": _not_measured("No tokenizer is used by the lexical fixture benchmark."),
            "peak_process_resources": _not_measured("Peak process resources are not sampled by this qualification run."),
            "engineer_time": _not_measured("Engineer time requires a separate human study."),
        },
        "case_results": case_results,
        "summary": {"overall_passed": gate_passed, "case_count": len(case_results), "passed_count": passed_count, "failed_count": failed_count},
        "release_gate": {"maximums": suite["release_blocking_max"], "observed": observed_gate, "passed": gate_passed},
        "metrics": _expected_metrics(case_results, suite["cases"], identity_checks, citation_checks),
        "limitations": [
            "This run qualifies the benchmark harness and fictional synthetic contract behavior only.",
            "Elapsed time and response bytes are observations, not cross-environment performance gates.",
            "Real-document discovery accuracy, semantic fidelity, tokenizer efficiency, peak resources, and engineer time are not measured.",
        ],
    }
    artifact = {"schema_version": "0.1.0", "run": run, "run_content_sha256": _digest(run)}
    validate_run_artifact(artifact, suite_document, root)

    if output_path is not None:
        destination = output_path.resolve()
        if destination.exists():
            raise BenchmarkContractError(f"Benchmark output already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            temporary_path.write_bytes(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n")
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    return artifact
