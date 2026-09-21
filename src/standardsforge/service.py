from __future__ import annotations

import hashlib
import base64
import binascii
import hmac
import json
import re
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import StandardsForgeError, require
from .identity import normalize_identifier
from .pack import open_validated_pack
from .policy import authorize_install, load_policy
from .store import LocalStore


class StandardsForgeService:
    """Application operations shared by local transports."""

    def __init__(self, db_path: str | Path, object_root: str | Path) -> None:
        self.store = LocalStore(db_path, object_root)

    @staticmethod
    def _validate_package_digest(package_digest: str) -> None:
        require(
            isinstance(package_digest, str) and re.fullmatch(r"[0-9a-f]{64}", package_digest) is not None,
            "invalid_package_pin",
            "A lowercase SHA-256 package digest is required.",
        )

    @staticmethod
    def _package_payload(package: Any) -> dict[str, Any]:
        return {
            "package_digest": package["package_digest"],
            "pack_id": package["pack_id"],
            "document_family_id": package["document_family_id"],
            "edition_id": package["edition_id"],
            "identifier": package["identifier"],
            "revision": package["revision"],
            "title": package["title"],
        }

    @staticmethod
    def _finalize_budget(packet: dict[str, Any], max_bytes: int | None) -> dict[str, Any]:
        if max_bytes is not None:
            require(type(max_bytes) is int and max_bytes > 0, "invalid_budget", "max_bytes must be a positive integer.")
        packet["budget"] = {"kind": "bytes", "used": 0, "limit": max_bytes}
        while True:
            encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if packet["budget"]["used"] == len(encoded):
                break
            packet["budget"]["used"] = len(encoded)
        if max_bytes is not None and len(encoded) > max_bytes:
            raise StandardsForgeError(
                "budget_too_small",
                "The complete atomic evidence unit does not fit the requested byte budget.",
                {"required_bytes": len(encoded), "max_bytes": max_bytes},
            )
        return packet

    def verify_pack(self, source: str | Path) -> dict[str, Any]:
        with open_validated_pack(source) as pack:
            return {
                "valid": True,
                "package_digest": pack.package_digest,
                "pack_id": pack.manifest["pack_id"],
                "edition_id": pack.manifest["edition_id"],
                "record_count": len(pack.records),
                "content_class": pack.rights["content_class"],
                "authorization_effect": "none",
            }

    def install_pack(self, source: str | Path, policy_path: str | Path) -> dict[str, Any]:
        policy = load_policy(policy_path)
        with open_validated_pack(source) as pack:
            authorize_install(policy, pack)
            result = self.store.install(pack, policy)
        return {"operation": "install", "status": "installed", **result}

    def resolve_document(self, identifier: str, principal_id: str, edition_id: str | None = None) -> dict[str, Any]:
        normalized = normalize_identifier(identifier)
        rows = self.store.authorized_packages(principal_id, normalized, edition_id)
        if not rows:
            raise StandardsForgeError("not_found", "No authorized resource matches the request.")
        if len(rows) != 1:
            raise StandardsForgeError(
                "ambiguous_document",
                "The identifier does not resolve to exactly one authorized package; provide an edition or package pin.",
                {
                    "candidates": [
                        {"edition_id": row["edition_id"], "package_digest": row["package_digest"]}
                        for row in rows
                    ]
                },
            )
        row = rows[0]
        return {
            "operation": "resolve_document",
            "retrieval_mode": "exact_identifier",
            "document_family_id": row["document_family_id"],
            "identifier": row["identifier"],
            "normalized_identifier": row["normalized_identifier"],
            "title": row["title"],
            "edition_id": row["edition_id"],
            "revision": row["revision"],
            "package_digest": row["package_digest"],
        }

    @staticmethod
    def _record_payload(row: Any, object_path: Path) -> dict[str, Any]:
        source = json.loads(row["source_json"])
        rel = PurePosixPath(source["path"])
        source_path = object_path.joinpath(*rel.parts)
        require(not source_path.is_symlink(), "source_integrity_failure", "Stored source evidence cannot be a symbolic link.")
        try:
            source_path.resolve(strict=True).relative_to(object_path.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise StandardsForgeError("source_integrity_failure", "Stored source evidence escaped its object directory.") from exc
        try:
            source_bytes = source_path.read_bytes()
            source_text = source_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise StandardsForgeError("source_integrity_failure", "Stored source evidence could not be read.") from exc
        actual_source_hash = hashlib.sha256(source_bytes).hexdigest()
        actual_quote_hash = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
        require(actual_source_hash == source["sha256"], "source_integrity_failure", "Stored source evidence failed its digest check.")
        require(actual_quote_hash == source["quote_sha256"], "source_integrity_failure", "Stored evidence text failed its digest check.")
        require(row["text"] in source_text, "source_integrity_failure", "Stored evidence text is absent from its preserved source.")
        return {
            "record_id": row["record_id"],
            "kind": row["kind"],
            "clause_reference": row["clause_reference"],
            "heading": row["heading"],
            "text": row["text"],
            "derivation": json.loads(row["derivation_json"]),
            "citation": {
                "source_path": source["path"],
                "source_sha256": source["sha256"],
                "page": source["page"],
                "locator": source["locator"],
                "quote_sha256": source["quote_sha256"],
            },
            "source_checks": {
                "source_digest_verified": True,
                "quote_digest_verified": True,
                "exact_quote_present": True,
            },
        }

    def get_clause(
        self,
        package_digest: str,
        clause_reference: str,
        principal_id: str,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        self._validate_package_digest(package_digest)
        require(isinstance(clause_reference, str) and bool(clause_reference.strip()), "invalid_clause_reference", "A clause reference is required.")
        package = self.store.authorized_package(principal_id, package_digest)
        root = Path(package["object_path"])
        root_record = self.store.record_by_clause(package_digest, clause_reference.strip())
        if root_record is None:
            raise StandardsForgeError("not_found", "No authorized resource matches the request.")

        ordered_rows = [root_record]
        relationships: list[dict[str, str]] = []
        visited = {root_record["record_id"]}
        queue = [root_record["record_id"]]
        while queue:
            current = queue.pop(0)
            for dependency in self.store.required_dependencies(package_digest, current):
                target_id = dependency["target_record_id"]
                relationships.append(
                    {"source_record_id": current, "relationship": dependency["relationship"], "target_record_id": target_id}
                )
                if target_id in visited:
                    continue
                target = self.store.record_by_id(package_digest, target_id)
                if target is None:
                    raise StandardsForgeError("incomplete_dependency", "Required evidence dependency is unavailable.")
                visited.add(target_id)
                ordered_rows.append(target)
                queue.append(target_id)

        packet: dict[str, Any] = {
            "schema_version": "0.1.0",
            "operation": "get_clause",
            "retrieval_mode": "exact_pinned_clause",
            "package": self._package_payload(package),
            "evidence": [self._record_payload(row, root) for row in ordered_rows],
            "required_relationships": relationships,
            "completeness": {
                "corpus_scope": "pinned_package",
                "edition_composition": "declared_complete",
                "parsed_source_coverage": "complete_for_returned_records",
                "dependency_closure": "complete",
                "enumeration_traversal": "not_requested",
                "output_budget_coverage": "complete",
                "complete_for_requested_scope": True,
            },
            "limitations": [
                "Exact quote checks do not establish PDF visual fidelity.",
                "This evidence packet is not an applicability or compliance decision.",
            ],
        }
        self._finalize_budget(packet, max_bytes)
        self.store.authorized_package(principal_id, package_digest)
        return packet

    def build_context(
        self,
        package_digest: str,
        clause_references: list[str],
        principal_id: str,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        self._validate_package_digest(package_digest)
        require(
            isinstance(clause_references, list)
            and 1 <= len(clause_references) <= 64
            and all(isinstance(value, str) and value.strip() for value in clause_references),
            "invalid_clause_reference",
            "build_context requires from 1 to 64 clause references.",
        )
        requested = list(dict.fromkeys(value.strip() for value in clause_references))
        package = self.store.authorized_package(principal_id, package_digest)
        evidence: list[dict[str, Any]] = []
        relationships: list[dict[str, str]] = []
        seen_records: set[str] = set()
        seen_relationships: set[tuple[str, str, str]] = set()
        for reference in requested:
            clause_packet = self.get_clause(package_digest, reference, principal_id)
            for item in clause_packet["evidence"]:
                if item["record_id"] not in seen_records:
                    seen_records.add(item["record_id"])
                    evidence.append(item)
            for relationship in clause_packet["required_relationships"]:
                key = (
                    relationship["source_record_id"],
                    relationship["relationship"],
                    relationship["target_record_id"],
                )
                if key not in seen_relationships:
                    seen_relationships.add(key)
                    relationships.append(relationship)

        packet: dict[str, Any] = {
            "schema_version": "0.1.0",
            "operation": "build_context",
            "retrieval_mode": "exact_pinned_multi_clause",
            "package": self._package_payload(package),
            "requested_clause_references": requested,
            "evidence": evidence,
            "required_relationships": relationships,
            "completeness": {
                "corpus_scope": "pinned_package",
                "edition_composition": "declared_complete",
                "parsed_source_coverage": "complete_for_returned_records",
                "dependency_closure": "complete",
                "enumeration_traversal": "not_requested",
                "output_budget_coverage": "complete",
                "complete_for_requested_scope": True,
            },
            "limitations": [
                "Exact quote checks do not establish PDF visual fidelity.",
                "Context assembly does not decide applicability or compliance.",
            ],
        }
        self._finalize_budget(packet, max_bytes)
        self.store.authorized_package(principal_id, package_digest)
        return packet

    def _encode_cursor(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        signature = hmac.new(self.store.cursor_secret(), raw, hashlib.sha256).digest()
        body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        tag = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return body + "." + tag

    def _decode_cursor(self, token: str) -> dict[str, Any]:
        require(isinstance(token, str) and 1 <= len(token) <= 4096, "invalid_cursor", "The continuation cursor is invalid.")
        try:
            body, tag = token.split(".", 1)
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            signature = base64.urlsafe_b64decode(tag + "=" * (-len(tag) % 4))
        except (ValueError, TypeError, binascii.Error) as exc:
            raise StandardsForgeError("invalid_cursor", "The continuation cursor is invalid.") from exc
        expected = hmac.new(self.store.cursor_secret(), raw, hashlib.sha256).digest()
        require(hmac.compare_digest(signature, expected), "invalid_cursor", "The continuation cursor signature is invalid.")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StandardsForgeError("invalid_cursor", "The continuation cursor payload is invalid.") from exc
        require(isinstance(payload, dict), "invalid_cursor", "The continuation cursor payload is invalid.")
        required_keys = {
            "version", "package_digest", "principal_fingerprint", "policy_fingerprint",
            "scope_prefix", "last_ordinal", "returned_count", "expires_at",
        }
        require(set(payload) == required_keys, "invalid_cursor", "The continuation cursor fields are invalid.")
        require(payload["version"] == 1, "invalid_cursor", "The continuation cursor version is unsupported.")
        require(type(payload["last_ordinal"]) is int, "invalid_cursor", "The continuation cursor ordinal is invalid.")
        require(
            type(payload["returned_count"]) is int and payload["returned_count"] >= 0,
            "invalid_cursor",
            "The continuation cursor count is invalid.",
        )
        require(type(payload["expires_at"]) in {int, float}, "invalid_cursor", "The continuation cursor expiry is invalid.")
        require(payload["expires_at"] >= time.time(), "expired_cursor", "The continuation cursor has expired.")
        return payload

    def enumerate_obligations(
        self,
        package_digest: str,
        principal_id: str,
        scope_prefix: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        self._validate_package_digest(package_digest)
        require(type(limit) is int and 1 <= limit <= 100, "invalid_limit", "Enumeration limit must be from 1 to 100.")
        if scope_prefix is not None:
            require(
                isinstance(scope_prefix, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", scope_prefix.strip()) is not None,
                "invalid_scope",
                "The scope prefix is invalid.",
            )
            scope_prefix = scope_prefix.strip()

        package = self.store.authorized_package(principal_id, package_digest)
        principal_fingerprint = hashlib.sha256(principal_id.encode("utf-8")).hexdigest()
        after_ordinal = -1
        previously_returned = 0
        if cursor is not None:
            payload = self._decode_cursor(cursor)
            require(payload["package_digest"] == package_digest, "cursor_scope_mismatch", "The cursor belongs to a different package.")
            require(payload["scope_prefix"] == scope_prefix, "cursor_scope_mismatch", "The cursor belongs to a different scope.")
            require(
                payload["principal_fingerprint"] == principal_fingerprint,
                "cursor_scope_mismatch",
                "The cursor belongs to a different principal.",
            )
            require(
                payload["policy_fingerprint"] == package["grant_policy_fingerprint"],
                "cursor_policy_changed",
                "The authorization policy changed after the cursor was issued.",
            )
            after_ordinal = payload["last_ordinal"]
            previously_returned = payload["returned_count"]

        rows = self.store.obligation_records(package_digest, scope_prefix, after_ordinal, limit + 1)
        page_rows = rows[:limit]
        has_more = len(rows) > limit
        obligations: list[dict[str, Any]] = []
        for row in page_rows:
            clause = self.get_clause(package_digest, row["clause_reference"], principal_id)
            obligations.append(
                {
                    "clause_reference": row["clause_reference"],
                    "record_id": row["record_id"],
                    "evidence": clause["evidence"],
                    "required_relationships": clause["required_relationships"],
                }
            )

        next_cursor = None
        if has_more and page_rows:
            next_cursor = self._encode_cursor(
                {
                    "version": 1,
                    "package_digest": package_digest,
                    "principal_fingerprint": principal_fingerprint,
                    "policy_fingerprint": package["grant_policy_fingerprint"],
                    "scope_prefix": scope_prefix,
                    "last_ordinal": page_rows[-1]["ordinal"],
                    "returned_count": previously_returned + len(page_rows),
                    "expires_at": int(time.time()) + 900,
                }
            )
        total = self.store.obligation_count(package_digest, scope_prefix)
        cumulative_returned = previously_returned + len(obligations)
        response = {
            "schema_version": "0.1.0",
            "operation": "enumerate_obligations",
            "retrieval_mode": "stable_record_traversal",
            "package": self._package_payload(package),
            "scope_prefix": scope_prefix,
            "obligations": obligations,
            "page": {
                "returned": len(obligations),
                "previously_returned": previously_returned,
                "cumulative_returned": cumulative_returned,
                "declared_scope_total": total,
                "has_more": has_more,
                "next_cursor": next_cursor,
                "cursor_ttl_seconds": 900 if next_cursor is not None else None,
            },
            "completeness": {
                "corpus_scope": "pinned_package",
                "edition_composition": "declared_complete",
                "parsed_source_coverage": "complete_for_fixture" if not has_more else "page_complete",
                "dependency_closure": "complete_for_returned_records",
                "enumeration_traversal": "complete" if not has_more else "continuation_required",
                "output_budget_coverage": "complete_for_page",
                "complete_for_requested_scope": not has_more and cumulative_returned == total,
                "packet_contains_entire_scope": previously_returned == 0 and not has_more,
            },
            "limitations": [
                "Enumeration covers records explicitly classified as obligations in the pinned pack.",
                "Extraction completeness remains distinct from database traversal completeness.",
                "A final page can complete a cursor traversal without repeating evidence from earlier pages.",
            ],
        }
        self._finalize_budget(response, max_bytes)
        self.store.authorized_package(principal_id, package_digest)
        return response

    def diff_editions(
        self,
        from_package_digest: str,
        to_package_digest: str,
        principal_id: str,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        self._validate_package_digest(from_package_digest)
        self._validate_package_digest(to_package_digest)
        before_package = self.store.authorized_package(principal_id, from_package_digest)
        after_package = self.store.authorized_package(principal_id, to_package_digest)
        require(
            before_package["document_family_id"] == after_package["document_family_id"],
            "different_document_families",
            "Edition comparison requires packages from the same document family.",
        )
        before_rows = {row["record_id"]: row for row in self.store.all_records(from_package_digest)}
        after_rows = {row["record_id"]: row for row in self.store.all_records(to_package_digest)}
        before_root = Path(before_package["object_path"])
        after_root = Path(after_package["object_path"])
        changes: list[dict[str, Any]] = []
        status_by_id: dict[str, str] = {}
        comparison_fields = ("kind", "clause_reference", "heading", "text", "statement_role", "derivation_json")
        for record_id in sorted(set(before_rows) | set(after_rows)):
            before = before_rows.get(record_id)
            after = after_rows.get(record_id)
            if before is None:
                status = "added"
            elif after is None:
                status = "removed"
            elif any(before[field] != after[field] for field in comparison_fields):
                status = "modified"
            else:
                status = "unchanged"
            status_by_id[record_id] = status
            change: dict[str, Any] = {"record_id": record_id, "status": status}
            if before is not None:
                change["before_text_sha256"] = hashlib.sha256(before["text"].encode("utf-8")).hexdigest()
            if after is not None:
                change["after_text_sha256"] = hashlib.sha256(after["text"].encode("utf-8")).hexdigest()
            if before is not None and after is not None:
                change["source_location_changed"] = before["source_json"] != after["source_json"]
            if status in {"removed", "modified"} and before is not None:
                change["before"] = self._record_payload(before, before_root)
            if status in {"added", "modified"} and after is not None:
                change["after"] = self._record_payload(after, after_root)
            changes.append(change)

        before_dependencies = {
            (row["source_record_id"], row["relationship"], row["target_record_id"], bool(row["required"]))
            for row in self.store.all_dependencies(from_package_digest)
        }
        after_dependencies = {
            (row["source_record_id"], row["relationship"], row["target_record_id"], bool(row["required"]))
            for row in self.store.all_dependencies(to_package_digest)
        }
        impacted: set[str] = set()
        for source_id, relationship, target_id, required in before_dependencies | after_dependencies:
            edge = (source_id, relationship, target_id, required)
            if edge not in before_dependencies or edge not in after_dependencies or status_by_id.get(target_id) != "unchanged":
                impacted.add(source_id)

        counts = {status: sum(1 for change in changes if change["status"] == status) for status in ("added", "removed", "modified", "unchanged")}
        packet: dict[str, Any] = {
            "schema_version": "0.1.0",
            "operation": "diff_editions",
            "alignment_mode": "exact_record_id_only",
            "from_package": self._package_payload(before_package),
            "to_package": self._package_payload(after_package),
            "changes": changes,
            "change_counts": counts,
            "dependency_context_impacts": sorted(impacted),
            "dependency_edges_added": [list(edge) for edge in sorted(after_dependencies - before_dependencies)],
            "dependency_edges_removed": [list(edge) for edge in sorted(before_dependencies - after_dependencies)],
            "limitations": [
                "The comparison does not infer record moves or equivalence from text similarity.",
                "Changes and dependency impacts are review evidence, not project baseline updates.",
            ],
        }
        self._finalize_budget(packet, max_bytes)
        self.store.authorized_package(principal_id, from_package_digest)
        self.store.authorized_package(principal_id, to_package_digest)
        return packet

    def search(self, query: str, principal_id: str, limit: int = 20) -> dict[str, Any]:
        require(type(limit) is int and 1 <= limit <= 100, "invalid_limit", "Search limit must be from 1 to 100.")
        require(isinstance(query, str), "invalid_query", "Search query must be text.")
        tokens = re.findall(r"[\w./-]+", query, flags=re.UNICODE)
        require(tokens, "invalid_query", "Search query contains no searchable terms.")
        fts_query = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens[:32])
        rows = self.store.search(principal_id, fts_query, limit)
        return {
            "operation": "search",
            "retrieval_mode": "lexical_fts5",
            "query": query,
            "results": [
                {
                    "package_digest": row["package_digest"],
                    "edition_id": row["edition_id"],
                    "identifier": row["identifier"],
                    "title": row["title"],
                    "record_id": row["record_id"],
                    "kind": row["kind"],
                    "clause_reference": row["clause_reference"],
                    "heading": row["heading"],
                    "score": row["score"],
                }
                for row in rows
            ],
            "limitations": ["Lexical rank is a discovery signal, not applicability or compliance."],
        }

    def revoke(self, package_digest: str, principal_id: str) -> dict[str, Any]:
        changed = self.store.revoke(principal_id, package_digest)
        return {"operation": "revoke", "revoked": changed, "package_digest": package_digest, "principal_id": principal_id}
