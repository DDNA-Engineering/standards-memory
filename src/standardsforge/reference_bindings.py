"""Explicit reviewed navigation across packages; never baseline selection."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .coverage_ledger import digest
from .errors import StandardsForgeError, require


def _object(value: Any, fields: set[str]) -> None:
    require(isinstance(value, dict) and set(value) == fields, "invalid_reference_bindings", "Reference binding fields are closed.")


def _text(value: Any, maximum: int = 4096) -> None:
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum,
            "invalid_reference_bindings", "Expected bounded nonempty reference text.")


def _selector(value: Any) -> None:
    from .service import StandardsForgeService
    _object(value, {"package_digest", "edition_id", "record_id", "quote_sha256"})
    for key in ("package_digest", "quote_sha256"):
        StandardsForgeService._validate_package_digest(value[key])
    for key in ("edition_id", "record_id"):
        _text(value[key], 512)


def validate_bindings(document: Any) -> dict[str, Any]:
    _object(document, {"schema_version", "binding_set", "binding_set_sha256"})
    body = document["binding_set"]
    _object(body, {"binding_set_id", "bindings", "scope", "project_applicability"})
    _text(body["binding_set_id"], 256)
    require(document["schema_version"] == "0.1.0" and document["binding_set_sha256"] == digest(body),
            "invalid_reference_bindings", "Reference artifact content binding failed.")
    require(body["scope"] == "reviewed_navigation_only" and body["project_applicability"] == "not_decided",
            "invalid_reference_bindings", "Navigation cannot assert project applicability or baseline approval.")
    require(isinstance(body["bindings"], list) and 1 <= len(body["bindings"]) <= 10000,
            "invalid_reference_bindings", "Require 1 to 10000 explicit bindings.")
    seen, endpoints, counts = set(), set(), {}
    for binding in body["bindings"]:
        _object(binding, {"binding_id", "source", "reference", "target", "status", "edition_basis", "rationale", "review"})
        _text(binding["binding_id"], 256)
        require(binding["binding_id"] not in seen, "invalid_reference_bindings", "Duplicate binding ID.")
        seen.add(binding["binding_id"])
        _selector(binding["source"])
        reference = binding["reference"]
        _object(reference, {"start_byte", "end_byte", "exact_text"})
        _text(reference["exact_text"])
        require(type(reference["start_byte"]) is int and type(reference["end_byte"]) is int
                and 0 <= reference["start_byte"] < reference["end_byte"]
                and reference["end_byte"] - reference["start_byte"] == len(reference["exact_text"].encode("utf-8")),
                "invalid_reference_bindings", "Reference offsets must bind exact UTF-8 bytes within the source record.")
        key = (binding["source"]["package_digest"], binding["source"]["record_id"])
        endpoint = (*key, reference["start_byte"], reference["end_byte"])
        require(endpoint not in endpoints, "invalid_reference_bindings", "An occurrence cannot silently select multiple target editions.")
        endpoints.add(endpoint)
        counts[key] = counts.get(key, 0) + 1
        require(counts[key] <= 100, "invalid_reference_bindings", "At most 100 reviewed reference occurrences per source record.")
        require(binding["status"] in {"resolved", "unresolved"}, "invalid_reference_bindings", "Invalid reference status.")
        if binding["status"] == "resolved":
            _selector(binding["target"])
            require(binding["target"]["package_digest"] != binding["source"]["package_digest"],
                    "invalid_reference_bindings", "Cross-package bindings require a separate target package.")
            require(binding["edition_basis"] in {"source_explicit_edition", "reviewer_selected_navigation_edition"},
                    "invalid_reference_bindings", "A resolved target needs an explicit edition-selection basis.")
        else:
            require(binding["target"] is None and binding["edition_basis"] == "unresolved",
                    "invalid_reference_bindings", "Unresolved references cannot imply a selected target.")
        _text(binding["rationale"])
        review = binding["review"]
        _object(review, {"kind", "identity", "reviewed_at", "binding_sha256"})
        require(review["kind"] in {"agent", "human"}, "invalid_reference_bindings", "Explicit reviewer provenance is required.")
        for key in ("identity", "reviewed_at"):
            _text(review[key], 256)
        require(review["binding_sha256"] == digest({k: v for k, v in binding.items() if k != "review"}),
                "invalid_reference_bindings", "Reviewer decision is stale for this exact binding.")
    return body


class ReferenceBindings:
    def __init__(self, path: str | Path, sha256: str):
        from .service import StandardsForgeService
        StandardsForgeService._validate_package_digest(sha256)
        try:
            with Path(path).open("rb") as stream:
                raw = stream.read(8 * 1024 * 1024 + 1)
            require(len(raw) <= 8 * 1024 * 1024 and hashlib.sha256(raw).hexdigest() == sha256,
                    "invalid_reference_bindings", "Reference artifact size or trusted SHA-256 pin failed.")
            document = json.loads(raw)
        except (OSError, UnicodeError, ValueError) as exc:
            raise StandardsForgeError("invalid_reference_bindings", "Cannot read the local reference artifact.") from exc
        self.__body = copy.deepcopy(validate_bindings(document))
        self.sha256 = sha256

    def matching(self, package_digest: str, record_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy([b for b in self.__body["bindings"]
                              if b["source"]["package_digest"] == package_digest and b["source"]["record_id"] == record_id])


def _evidence(service: Any, selector: dict[str, str], principal: str) -> dict[str, Any]:
    packet = service.get_clause(selector["package_digest"], principal_id=principal, record_id=selector["record_id"])
    record = next(r for r in packet["evidence"] if r["record_id"] == selector["record_id"])
    require(packet["package"]["edition_id"] == selector["edition_id"]
            and record["citation"]["quote_sha256"] == selector["quote_sha256"],
            "stale_reference_binding", "Reviewed reference endpoint differs from the pinned source record.")
    return packet


def follow_references(service: Any, package_digest: str, record_id: str, principal_id: str,
                      *, max_bytes: int | None = None) -> dict[str, Any]:
    service._validate_package_digest(package_digest)
    _text(record_id, 512)
    service.store.authorized_package(principal_id, package_digest)
    require(service.reference_bindings is not None, "reference_bindings_not_configured",
            "Trusted startup must configure a locally pinned reviewed reference artifact.")
    state = service.store.cache_state(principal_id)
    bindings = service.reference_bindings.matching(package_digest, record_id)
    source = service.get_clause(package_digest, principal_id=principal_id, record_id=record_id)
    record = next(r for r in source["evidence"] if r["record_id"] == record_id)
    text = record["text"].encode("utf-8")
    packages = {package_digest}
    # Preauthorize every selected endpoint before returning any target metadata.
    for binding in bindings:
        if binding["target"] is not None:
            target_digest = binding["target"]["package_digest"]
            service.store.authorized_package(principal_id, target_digest)
            packages.add(target_digest)
    results = []
    for binding in bindings:
        selector, ref = binding["source"], binding["reference"]
        require(source["package"]["edition_id"] == selector["edition_id"]
                and record["citation"]["quote_sha256"] == selector["quote_sha256"]
                and text[ref["start_byte"]:ref["end_byte"]] == ref["exact_text"].encode("utf-8"),
                "stale_reference_binding", "Reviewed reference span differs from the exact source evidence.")
        target = _evidence(service, binding["target"], principal_id) if binding["target"] is not None else None
        results.append({"binding": binding, "target_evidence": target})
    packet = {"schema_version": "0.1.0", "operation": "follow_references",
              "binding_artifact_sha256": service.reference_bindings.sha256,
              "source_evidence": source, "references": results,
              "coverage": {"scope": "configured_reviewed_bindings_for_record", "returned": len(results),
                           "unresolved": sum(b["status"] == "unresolved" for b in bindings),
                           "all_source_references_reviewed": False, "transitive_closure_complete": False,
                           "project_applicability": "not_decided"},
              "limitations": ["Only explicit reviewed bindings are followed; zero bindings does not mean zero source references.",
                              "A reviewer-selected navigation edition is not the source-mandated or project-approved edition.",
                              "Links are one hop; each endpoint retains its own required context and coverage.",
                              "Review provenance is recorded, not authenticated human approval."]}
    service._finalize_budget(packet, max_bytes)
    for target_digest in sorted(packages):
        service.store.authorized_package(principal_id, target_digest)
    require(service.store.cache_state(principal_id) == state, "authorization_changed",
            "Authorization or installed state changed during reference traversal; retry the request.")
    return packet
