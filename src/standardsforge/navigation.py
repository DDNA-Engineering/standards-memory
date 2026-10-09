"""Source-verified navigation; no inferred classification or external acquisition."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from .errors import StandardsForgeError, require

RELATIONS = ("all", "roots", "children", "parent", "adjacent", "outgoing", "incoming")


def browse_records(service: Any, package_digest: str, principal_id: str, *,
                   relation: str = "all", record_id: str | None = None,
                   kind: str | None = None, scope_prefix: str | None = None,
                   limit: int = 50, cursor: str | None = None,
                   max_bytes: int | None = None) -> dict[str, Any]:
    from .service import _RequestVerificationContext, _utf8_text

    service._validate_package_digest(package_digest)
    require(relation in RELATIONS, "invalid_relation", "Unsupported navigation relation.")
    require(type(limit) is int and 1 <= limit <= 100, "invalid_limit", "Record limit must be from 1 to 100.")
    for name, value in (("record_id", record_id), ("kind", kind), ("scope_prefix", scope_prefix)):
        require(value is None or _utf8_text(value) and 0 < len(value) <= 512 and bool(value.strip()),
                "invalid_selector", f"{name} must be bounded nonempty UTF-8 text when supplied.")
    # Scope matches search and enumerate_obligations: surrounding whitespace is not part of the prefix.
    scope_prefix = None if scope_prefix is None else scope_prefix.strip()
    require(kind is None or re.fullmatch(r"[a-z_]{1,64}", kind) is not None,
            "invalid_kind", "Record kind must be a lowercase kind identifier.")
    require((record_id is None) == (relation in {"all", "roots"}), "invalid_selector",
            "Supply record_id exactly for children, parent, adjacent, outgoing or incoming navigation.")
    package = service.store.authorized_package(principal_id, package_digest)
    state = service.store.cache_state(principal_id)
    filters = {"relation": relation, "record_id": record_id, "kind": kind, "scope_prefix": scope_prefix}
    binding = {"operation": "browse_records", "package_digest": package_digest,
               "principal_sha256": hashlib.sha256(principal_id.encode("utf-8")).hexdigest(),
               "visibility_fingerprint": state["visibility_fingerprint"], "filters": filters}
    after, returned = -1, 0
    if cursor is not None:
        payload = service._decode_signed_cursor(cursor)
        require(set(payload) == {*binding, "last_ordinal", "returned_count", "expires_at"},
                "invalid_cursor", "Invalid navigation cursor fields.")
        require(all(payload[k] == v for k, v in binding.items()), "cursor_scope_mismatch",
                "Navigation cursor belongs to another package, query, principal or authorization snapshot.")
        require(type(payload["last_ordinal"]) is int and payload["last_ordinal"] >= 0
                and type(payload["returned_count"]) is int and payload["returned_count"] > 0,
                "invalid_cursor", "Invalid navigation position.")
        after, returned = payload["last_ordinal"], payload["returned_count"]
    verification = _RequestVerificationContext()
    anchor = None
    if record_id is not None:
        anchor = service.store.record_by_id(package_digest, record_id)
        if anchor is None:
            raise StandardsForgeError("not_found", "No authorized resource matches the request.")
        service._record_payload(anchor, Path(package["object_path"]), verification)
    rows, total = service.store.navigation_page(package_digest, relation, anchor, kind, scope_prefix, after, limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    records = []
    edges = service.store.navigation_edges(package_digest, record_id, relation) if relation in {"incoming", "outgoing"} else []
    for row in rows:
        evidence = service._record_payload(row, Path(package["object_path"]), verification)
        structure = evidence.get("structure", {})
        traversed = [dict(edge, required=bool(edge["required"])) for edge in edges
                     if row["record_id"] == edge["target_record_id" if relation == "outgoing" else "source_record_id"]]
        if relation in {"incoming", "outgoing"}:
            source, target = (anchor, row) if relation == "outgoing" else (row, anchor)
            target_logical = json.loads(target["structure_json"]).get("logical_id")
            for edge in json.loads(source["structure_json"]).get("relationships", []):
                if edge.get("target_status") == "resolved" and edge.get("target_logical_id") == target_logical:
                    projected = {"source_record_id": source["record_id"], "target_record_id": target["record_id"],
                                 "relationship": edge["relationship"], "required": edge["required"]}
                    if projected not in traversed:
                        traversed.append(projected)
        records.append({
            "record_id": row["record_id"], "clause_reference": row["clause_reference"],
            "kind": row["kind"], "heading": row["heading"], "ordinal": row["ordinal"],
            "statement_role": row["statement_role"], "derivation": evidence["derivation"],
            "logical_id": structure.get("logical_id"), "parent_logical_id": structure.get("parent_logical_id"),
            "relationships": structure.get("relationships", []),
            "traversed_relationships": traversed,
            "citation": evidence["citation"], "source_checks": evidence["source_checks"],
            "evidence_selector": {"operation": "get_clause", "package_digest": package_digest,
                                  "record_id": row["record_id"], "clause_reference": row["clause_reference"],
                                  "response_profile": "concise_evidence_v1"},
        })
    next_cursor = service._encode_cursor({**binding, "last_ordinal": rows[-1]["ordinal"],
                                         "returned_count": returned + len(rows), "expires_at": int(time.time()) + 900}) if more else None
    packet = {"schema_version": "0.1.0", "operation": "browse_records",
              "retrieval_mode": "source_verified_record_navigation", "package": service._package_payload(package),
              "filters": filters, "records": records,
              "page": {"returned": len(rows), "previously_returned": returned,
                       "cumulative_returned": returned + len(rows), "matching_record_count": total,
                       "has_more": more, "next_cursor": next_cursor},
              "coverage": {"declared_pack_coverage": service._declared_coverage(package),
                           "traversal_complete": not more and returned + len(rows) == total,
                           "scope_interpretation": "installed_records_matching_filters_not_source_semantic_completeness"},
              "limitations": ["Navigation does not classify unreviewed records or establish extraction completeness.",
                              "Retrieve the evidence selector for exact text and required governing context."]}
    service._finalize_budget(packet, max_bytes)
    service.store.authorized_package(principal_id, package_digest)
    require(service.store.cache_state(principal_id) == state, "authorization_changed",
            "Authorization or installed state changed during navigation; retry the request.")
    return packet
