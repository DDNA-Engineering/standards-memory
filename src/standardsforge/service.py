from __future__ import annotations

from collections import deque
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
from .query_cache import VersionedLRUCache
from .store import LocalStore


def _decode_utf8(data: bytes) -> str:
    return data.decode("utf-8")


class _RequestVerificationContext:
    """Request-local verified source bytes and UTF-8 decodings.

    Integrity results are deliberately not retained on the service or in the
    query caches: every request gets a fresh context and re-hashes each distinct
    path/digest pair before using it.
    """

    def __init__(self) -> None:
        self._roots: dict[str, Path] = {}
        self._paths: dict[tuple[str, str], Path] = {}
        self._verified_files: set[tuple[str, str]] = set()
        self._verified_bytes: dict[tuple[str, str], bytes] = {}
        self._decoded_text: dict[tuple[str, str], str] = {}

    def _path(self, object_path: Path, relative_path: str) -> tuple[Path, tuple[str, str]]:
        root_key = str(object_path)
        root = self._roots.get(root_key)
        if root is None:
            try:
                root = object_path.resolve(strict=True)
            except OSError as exc:
                raise StandardsForgeError("source_integrity_failure", "Stored source evidence could not be read.") from exc
            self._roots[root_key] = root

        relative = PurePosixPath(relative_path)
        cache_key = (str(root), relative.as_posix())
        path = self._paths.get(cache_key)
        if path is not None:
            return path, cache_key

        candidate = object_path.joinpath(*relative.parts)
        require(not candidate.is_symlink(), "source_integrity_failure", "Stored source evidence cannot be a symbolic link.")
        try:
            path = candidate.resolve(strict=True)
            path.relative_to(root)
        except (OSError, ValueError) as exc:
            raise StandardsForgeError("source_integrity_failure", "Stored source evidence escaped its object directory.") from exc
        self._paths[cache_key] = path
        return path, cache_key

    def verified_file(
        self,
        object_path: Path,
        relative_path: str,
        expected_sha256: str,
        failure_message: str,
    ) -> None:
        path, _ = self._path(object_path, relative_path)
        cache_key = (str(path), expected_sha256)
        if cache_key in self._verified_files or cache_key in self._verified_bytes:
            return
        try:
            with path.open("rb") as stream:
                actual_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError as exc:
            raise StandardsForgeError("source_integrity_failure", "Stored source evidence could not be read.") from exc
        require(actual_sha256 == expected_sha256, "source_integrity_failure", failure_message)
        self._verified_files.add(cache_key)

    def verified_bytes(
        self,
        object_path: Path,
        relative_path: str,
        expected_sha256: str,
        failure_message: str,
    ) -> bytes:
        path, _ = self._path(object_path, relative_path)
        cache_key = (str(path), expected_sha256)
        data = self._verified_bytes.get(cache_key)
        if data is not None:
            return data
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise StandardsForgeError("source_integrity_failure", "Stored source evidence could not be read.") from exc
        require(hashlib.sha256(data).hexdigest() == expected_sha256, "source_integrity_failure", failure_message)
        self._verified_files.add(cache_key)
        self._verified_bytes[cache_key] = data
        return data

    def decoded_text(
        self,
        object_path: Path,
        relative_path: str,
        expected_sha256: str,
    ) -> str:
        data = self.verified_bytes(
            object_path,
            relative_path,
            expected_sha256,
            "Stored extracted source text failed its digest check.",
        )
        path, _ = self._path(object_path, relative_path)
        cache_key = (str(path), expected_sha256)
        text = self._decoded_text.get(cache_key)
        if text is not None:
            return text
        try:
            text = _decode_utf8(data)
        except UnicodeDecodeError as exc:
            raise StandardsForgeError("source_integrity_failure", "Stored source evidence could not be read.") from exc
        self._decoded_text[cache_key] = text
        return text


class StandardsForgeService:
    def __init__(self, db_path: str | Path, object_root: str | Path) -> None:
        self.store = LocalStore(db_path, object_root)
        self._closure_cache = VersionedLRUCache("required-evidence-closure", "1", max_entries=256)
        self._search_cache = VersionedLRUCache("authorized-lexical-search", "1", max_entries=256)

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
    def _declared_coverage(package: Any) -> dict[str, str]:
        manifest = json.loads(package["manifest_json"])
        return manifest["coverage"]

    @staticmethod
    def _package_representation(package: Any) -> str:
        """Return an explicit representation, with deterministic legacy-pack inference."""
        manifest = json.loads(package["manifest_json"])
        explicit = manifest.get("representation")
        if explicit is not None:
            return explicit
        parsed_coverage = manifest["coverage"]["parsed_source_coverage"]
        if parsed_coverage.startswith("text_layer_extracted_"):
            return "page_text"
        if parsed_coverage.startswith("partial_reviewed_structural_"):
            return "reviewed_structure"
        return "curated_records"

    @staticmethod
    def _coverage_status(value: str) -> str:
        if value in {"complete", "complete_for_fixture"}:
            return "complete"
        if value in {"not_derived", "not_evaluated", "unclassified", "unknown"} or value.startswith(
            ("incomplete", "partial_", "text_layer_extracted_", "automated_outline_")
        ):
            return "incomplete"
        return "unknown"

    @classmethod
    def _coverage_dimensions(
        cls,
        declared: dict[str, str],
        *,
        dependency_retrieval_complete: bool | None,
        dependency_retrieval_status: str,
        traversal_complete: bool | None,
        traversal_status: str,
        response_fit_complete: bool = True,
    ) -> dict[str, Any]:
        edition_status = cls._coverage_status(declared["edition_composition"])
        parsing_status = cls._coverage_status(declared["parsed_source_coverage"])
        if "incomplete" in {edition_status, parsing_status}:
            source_status = "incomplete"
        elif edition_status == parsing_status == "complete":
            source_status = "complete"
        else:
            source_status = "unknown"
        dependency_identification_status = cls._coverage_status(declared["dependency_closure"])
        return {
            "version": "1.0",
            "source_interpretation": {
                "complete": source_status == "complete",
                "status": source_status,
                "edition_composition": declared["edition_composition"],
                "parsed_source_coverage": declared["parsed_source_coverage"],
            },
            "required_dependencies": {
                "identification_complete": dependency_identification_status == "complete",
                "identification_status": dependency_identification_status,
                "declared_coverage": declared["dependency_closure"],
                "retrieval_complete": dependency_retrieval_complete,
                "retrieval_status": dependency_retrieval_status,
            },
            "database_traversal": {
                "complete": traversal_complete,
                "status": traversal_status,
            },
            "response_fit": {
                "complete": response_fit_complete,
                "status": "complete" if response_fit_complete else "budget_too_small",
                "unit": "bytes",
            },
        }

    @staticmethod
    def _dimensions_complete(dimensions: dict[str, Any], *, require_traversal: bool) -> bool:
        checks = [
            dimensions["source_interpretation"]["complete"],
            dimensions["required_dependencies"]["identification_complete"],
            dimensions["required_dependencies"]["retrieval_complete"],
            dimensions["response_fit"]["complete"],
        ]
        if require_traversal:
            checks.append(dimensions["database_traversal"]["complete"])
        return all(value is True for value in checks)

    @staticmethod
    def _render_concise_evidence_profile(packet: dict[str, Any]) -> dict[str, Any]:
        evidence = packet.get("evidence")
        require(isinstance(evidence, list), "response_render_error", "The detailed packet has no evidence list.")

        records: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        derivations: list[dict[str, Any]] = []
        spans: list[dict[str, Any]] = []
        structure_nodes: list[dict[str, Any]] = []
        source_refs: dict[str, str] = {}
        derivation_refs: dict[str, str] = {}
        span_refs: dict[str, str] = {}
        structure_refs: dict[str, str] = {}
        record_refs: dict[str, str] = {}
        record_by_id: dict[str, dict[str, Any]] = {}
        logical_to_record_id: dict[str, str] = {}

        def intern_source(
            path: str,
            sha256: str,
            text_path: str | None = None,
            text_sha256: str | None = None,
            checks: dict[str, Any] | None = None,
        ) -> str:
            source_file: dict[str, Any] = {"path": path, "sha256": sha256}
            if text_path is not None:
                source_file["text_path"] = text_path
                source_file["text_sha256"] = text_sha256
            source_key = json.dumps(source_file, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            source_ref = source_refs.get(source_key)
            if source_ref is None:
                source_ref = f"s{len(sources) + 1}"
                source_refs[source_key] = source_ref
                sources.append({"ref": source_ref, **source_file, "verified": True})
            if checks:
                require(
                    checks.get("source_digest_verified") is True
                    and (text_path is None or checks.get("extracted_text_digest_verified") is True),
                    "response_render_error",
                    "A source was not verified before concise rendering.",
                )
            return source_ref

        def intern_derivation(derivation: dict[str, Any]) -> str:
            key = json.dumps(derivation, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            derivation_ref = derivation_refs.get(key)
            if derivation_ref is None:
                derivation_ref = f"d{len(derivations) + 1}"
                derivation_refs[key] = derivation_ref
                derivations.append({"ref": derivation_ref, **derivation})
            return derivation_ref

        def intern_span(span: dict[str, Any]) -> str:
            source_ref = intern_source(
                span["path"],
                span["sha256"],
                span.get("text_path"),
                span.get("text_sha256"),
                {
                    "source_digest_verified": True,
                    "extracted_text_digest_verified": True,
                },
            )
            value = {
                "source_ref": source_ref,
                "physical_page": span["physical_page"],
                "start_byte": span["start_byte"],
                "end_byte": span["end_byte"],
                "quote_sha256": span["quote_sha256"],
            }
            key = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            span_ref = span_refs.get(key)
            if span_ref is None:
                span_ref = f"p{len(spans) + 1}"
                span_refs[key] = span_ref
                spans.append({"ref": span_ref, **value, "verified": True})
            return span_ref

        for item in evidence:
            require(isinstance(item, dict), "response_render_error", "An evidence record is invalid.")
            record_id = item.get("record_id")
            require(isinstance(record_id, str) and bool(record_id), "response_render_error", "An evidence record has no canonical ID.")
            if record_id in record_by_id:
                require(
                    record_by_id[record_id] == item,
                    "response_render_error",
                    "Repeated evidence records disagree within one packet.",
                    record_id=record_id,
                )
                continue

            citation = item.get("citation")
            derivation = item.get("derivation")
            source_checks = item.get("source_checks")
            require(
                isinstance(citation, dict) and isinstance(derivation, dict) and isinstance(source_checks, dict),
                "response_render_error",
                "An evidence record is missing citation or derivation metadata.",
                record_id=record_id,
            )
            require(
                source_checks.get("source_digest_verified") is True
                and source_checks.get("quote_digest_verified") is True
                and source_checks.get("exact_quote_present") is True
                and ("text_path" not in citation or source_checks.get("extracted_text_digest_verified") is True),
                "response_render_error",
                "An evidence citation was not fully verified before concise rendering.",
                record_id=record_id,
            )
            source_ref = intern_source(
                citation["source_path"],
                citation["source_sha256"],
                citation.get("text_path"),
                citation.get("text_sha256"),
                source_checks,
            )
            derivation_ref = intern_derivation(derivation)
            record_ref = f"e{len(records) + 1}"
            record_refs[record_id] = record_ref
            record_by_id[record_id] = item
            concise_citation = {
                "source_ref": source_ref,
                "page": citation["page"],
                "locator": citation["locator"],
                "quote_sha256": citation["quote_sha256"],
                "verified": True,
            }
            for offset_name in ("text_start_byte", "text_end_byte"):
                if offset_name in citation:
                    concise_citation[offset_name] = citation[offset_name]
            record: dict[str, Any] = {
                "ref": record_ref,
                "record_id": record_id,
                "kind": item["kind"],
                "clause_reference": item["clause_reference"],
                "heading": item["heading"],
                "text": item["text"],
                "citation": concise_citation,
                "derivation_ref": derivation_ref,
            }
            structure = item.get("structure")
            if structure is not None:
                require(isinstance(structure, dict), "response_render_error", "Structural evidence is invalid.", record_id=record_id)
                logical_id = structure.get("logical_id")
                require(isinstance(logical_id, str) and logical_id, "response_render_error", "Structural evidence has no logical ID.", record_id=record_id)
                structure_key = json.dumps(structure, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                structure_ref = structure_refs.get(structure_key)
                if structure_ref is None:
                    structure_ref = f"n{len(structure_nodes) + 1}"
                    structure_refs[structure_key] = structure_ref
                    node_spans = structure.get("source_spans")
                    require(isinstance(node_spans, list) and node_spans, "response_render_error", "A structural node has no source spans.", record_id=record_id)
                    structure_nodes.append(
                        {
                            "ref": structure_ref,
                            "record_ref": record_ref,
                            "logical_id": logical_id,
                            "content_sha256": structure["content_sha256"],
                            "parent_logical_id": structure.get("parent_logical_id"),
                            "ordinal": structure["ordinal"],
                            "span_refs": [intern_span(span) for span in node_spans],
                        }
                    )
                else:
                    prior_node = next(node for node in structure_nodes if node["ref"] == structure_ref)
                    require(prior_node["record_ref"] == record_ref, "response_render_error", "A structural node is attached to conflicting records.")
                logical_to_record_id[logical_id] = record_id
                record["structure_ref"] = structure_ref
            records.append(record)

        # Keep the required dependency graph and source-annotated structural
        # relationships in one table. A resolved required structural edge is
        # therefore represented once, with its source proof attached.
        relationships_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        relationships: list[dict[str, Any]] = []
        for relationship in packet.get("required_relationships", []):
            source_record_id = relationship.get("source_record_id")
            target_record_id = relationship.get("target_record_id")
            require(
                source_record_id in record_refs and target_record_id in record_refs,
                "response_render_error",
                "A required relationship points outside the packet evidence.",
            )
            key = (source_record_id, relationship["relationship"], target_record_id, "resolved")
            edge = relationships_by_key.get(key)
            if edge is None:
                edge = {
                    "source_ref": record_refs[source_record_id],
                    "relationship": relationship["relationship"],
                    "required": True,
                    "target_status": "resolved",
                    "target_ref": record_refs[target_record_id],
                }
                relationships_by_key[key] = edge
                relationships.append(edge)

        for item in evidence:
            if "structure" not in item:
                continue
            source_record_id = item["record_id"]
            for structural in item["structure"].get("relationships", []):
                target_status = structural["target_status"]
                target_logical_id = structural.get("target_logical_id")
                target_record_id = logical_to_record_id.get(target_logical_id) if target_logical_id else None
                target_key: Any = target_record_id or target_logical_id or structural.get("target_locator")
                candidates = structural.get("candidate_logical_ids") or []
                derivation_ref = intern_derivation(
                    {"method": structural["method"], "review_status": structural["review_status"]}
                )
                key: tuple[Any, ...] = (source_record_id, structural["relationship"], target_key, target_status)
                if target_status != "resolved":
                    # Non-resolved edges do not have one target to distinguish
                    # them. Preserve separate candidate sets and review
                    # derivations instead of letting a later declaration
                    # replace those fields on an earlier edge.
                    key = (*key, tuple(candidates), derivation_ref)
                edge = relationships_by_key.get(key)
                if edge is None:
                    edge = {
                        "source_ref": record_refs[source_record_id],
                        "relationship": structural["relationship"],
                        "required": structural["required"],
                        "target_status": target_status,
                    }
                    relationships_by_key[key] = edge
                    relationships.append(edge)
                else:
                    require(edge["required"] == structural["required"], "response_render_error", "Repeated relationship declarations disagree.")
                if target_record_id is not None:
                    edge["target_ref"] = record_refs[target_record_id]
                if target_logical_id is not None:
                    edge["target_logical_id"] = target_logical_id
                target_locator = structural.get("target_locator")
                if target_locator:
                    edge["target_locator"] = target_locator
                if candidates:
                    edge["candidate_logical_ids"] = candidates
                edge["derivation_ref"] = derivation_ref
                evidence_span_refs = [intern_span(span) for span in structural["evidence_spans"]]
                existing_span_refs = edge.setdefault("evidence_span_refs", [])
                for span_ref in evidence_span_refs:
                    if span_ref not in existing_span_refs:
                        existing_span_refs.append(span_ref)

        completeness = packet.get("completeness")
        require(isinstance(completeness, dict), "response_render_error", "The detailed packet has no completeness declaration.")
        dimensions = completeness.get("dimensions")
        require(isinstance(dimensions, dict), "response_render_error", "The detailed packet has no completeness dimensions.")
        concise_coverage = {
            "declared": completeness["declared_pack_coverage"],
            "source_interpretation": {
                "complete": dimensions["source_interpretation"]["complete"],
                "status": dimensions["source_interpretation"]["status"],
            },
            "required_dependencies": {
                "identification_complete": dimensions["required_dependencies"]["identification_complete"],
                "identification_status": dimensions["required_dependencies"]["identification_status"],
                "retrieval_complete": dimensions["required_dependencies"]["retrieval_complete"],
                "retrieval_status": dimensions["required_dependencies"]["retrieval_status"],
            },
            "database_traversal": dimensions["database_traversal"],
            "response_fit": dimensions["response_fit"],
            "complete_for_requested_scope": completeness["complete_for_requested_scope"],
            "scope_interpretation": completeness["scope_interpretation"],
        }

        concise_packet = {
            key: value
            for key, value in packet.items()
            if key not in {"evidence", "required_relationships", "completeness", "budget"}
        }
        concise_packet["response_profile"] = "concise_evidence_v1"
        concise_packet["authorization"] = {
            "status": "authorized",
            "package_digest": packet["package"]["package_digest"],
        }
        if "requested_clause_references" in packet:
            concise_packet["requested_clause_references"] = packet["requested_clause_references"]
        concise_packet["evidence"] = records
        concise_packet["relationships"] = relationships
        concise_packet["provenance"] = {
            "sources": sources,
            "derivations": derivations,
            "structure_nodes": structure_nodes,
            "spans": spans,
        }
        concise_packet["coverage"] = concise_coverage
        concise_packet["token_measurement"] = {
            "status": "unavailable",
            "reason": "no_local_tokenizer_configured",
        }
        return concise_packet

    @staticmethod
    def _render_response_profile(packet: dict[str, Any], response_profile: str | None) -> dict[str, Any]:
        require(
            response_profile in {None, "detailed_json_v1", "compact_evidence_v1", "concise_evidence_v1"},
            "invalid_response_profile",
            "The response profile is unsupported.",
            supported=["detailed_json_v1", "compact_evidence_v1", "concise_evidence_v1"],
        )
        if response_profile in {None, "detailed_json_v1"}:
            return packet
        if response_profile == "concise_evidence_v1":
            return StandardsForgeService._render_concise_evidence_profile(packet)

        evidence = packet.get("evidence")
        require(isinstance(evidence, list), "response_render_error", "The detailed packet has no evidence list.")

        records: list[dict[str, Any]] = []
        source_files: list[dict[str, Any]] = []
        derivations: list[dict[str, Any]] = []
        record_refs: dict[str, str] = {}
        source_refs: dict[str, str] = {}
        derivation_refs: dict[str, str] = {}
        unique_records: dict[str, dict[str, Any]] = {}

        for item in evidence:
            require(isinstance(item, dict), "response_render_error", "An evidence record is invalid.")
            record_id = item.get("record_id")
            require(isinstance(record_id, str) and bool(record_id), "response_render_error", "An evidence record has no canonical ID.")
            if record_id in unique_records:
                require(
                    unique_records[record_id] == item,
                    "response_render_error",
                    "Repeated evidence records disagree within one packet.",
                    record_id=record_id,
                )
                continue
            unique_records[record_id] = item

            citation = item.get("citation")
            derivation = item.get("derivation")
            source_checks = item.get("source_checks")
            require(
                isinstance(citation, dict) and isinstance(derivation, dict) and isinstance(source_checks, dict),
                "response_render_error",
                "An evidence record is missing citation or derivation metadata.",
                record_id=record_id,
            )

            source_file = {
                "path": citation["source_path"],
                "sha256": citation["source_sha256"],
            }
            if "text_path" in citation:
                source_file["text_path"] = citation["text_path"]
                source_file["text_sha256"] = citation["text_sha256"]
            source_file_key = json.dumps(source_file, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            source_ref = source_refs.get(source_file_key)
            if source_ref is None:
                source_ref = f"s{len(source_files) + 1}"
                source_refs[source_file_key] = source_ref
                source_verification = {
                    key: source_checks[key]
                    for key in ("source_digest_verified", "extracted_text_digest_verified")
                    if key in source_checks
                }
                source_files.append({"ref": source_ref, **source_file, "source_checks": source_verification})

            derivation_key = json.dumps(derivation, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            derivation_ref = derivation_refs.get(derivation_key)
            if derivation_ref is None:
                derivation_ref = f"d{len(derivations) + 1}"
                derivation_refs[derivation_key] = derivation_ref
                derivations.append({"ref": derivation_ref, **derivation})

            record_ref = f"e{len(records) + 1}"
            record_refs[record_id] = record_ref
            record_checks = {
                key: source_checks[key]
                for key in ("quote_digest_verified", "exact_quote_present")
                if key in source_checks
            }
            compact_record = {
                    "ref": record_ref,
                    "record_id": record_id,
                    "kind": item["kind"],
                    "clause_reference": item["clause_reference"],
                    "heading": item["heading"],
                    "text": item["text"],
                    "source_ref": source_ref,
                    "page": citation["page"],
                    "locator": citation["locator"],
                    "quote_sha256": citation["quote_sha256"],
                    "source_checks": record_checks,
                    "derivation_ref": derivation_ref,
                }
            if "structure" in item:
                compact_record["structure"] = item["structure"]
            records.append(compact_record)

        relationships: list[dict[str, Any]] = []
        for relationship in packet.get("required_relationships", []):
            source_record_id = relationship.get("source_record_id")
            target_record_id = relationship.get("target_record_id")
            require(
                source_record_id in record_refs and target_record_id in record_refs,
                "response_render_error",
                "A required relationship points outside the packet evidence.",
            )
            relationships.append(
                {
                    "source_ref": record_refs[source_record_id],
                    "relationship": relationship["relationship"],
                    "target_ref": record_refs[target_record_id],
                }
            )

        compact_packet = {
            key: value
            for key, value in packet.items()
            if key not in {"evidence", "required_relationships", "budget"}
        }
        compact_packet["response_profile"] = "compact_evidence_v1"
        compact_packet["evidence"] = {
            "records": records,
            "source_files": source_files,
            "derivations": derivations,
        }
        compact_packet["required_relationships"] = relationships
        compact_packet["token_measurement"] = {
            "status": "unavailable",
            "reason": "no_local_tokenizer_configured",
        }
        return compact_packet

    @staticmethod
    def _finalize_budget(packet: dict[str, Any], max_bytes: int | None) -> dict[str, Any]:
        if max_bytes is not None:
            require(type(max_bytes) is int and max_bytes > 0, "invalid_budget", "max_bytes must be a positive integer.")
        packet["budget"] = {"kind": "bytes", "used": 0, "limit": max_bytes}
        # The only length-changing value after this serialization is the
        # decimal representation of budget.used. Solve that fixed point with
        # integer arithmetic instead of serializing the complete packet until
        # it converges.
        encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        fixed_bytes = len(encoded) - 1
        used = len(encoded)
        while True:
            next_used = fixed_bytes + len(str(used))
            if next_used == used:
                break
            used = next_used
        packet["budget"]["used"] = used
        if max_bytes is not None and used > max_bytes:
            raise StandardsForgeError(
                "budget_too_small",
                "The complete atomic evidence unit does not fit the requested byte budget.",
                {
                    "required_bytes": used,
                    "max_bytes": max_bytes,
                    "response_fit": {"complete": False, "status": "budget_too_small", "unit": "bytes"},
                },
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

    @staticmethod
    def _document_sort_key(row: Any) -> tuple[str, str, str, str, str]:
        return (
            row["normalized_identifier"],
            row["document_family_id"],
            row["edition_id"],
            StandardsForgeService._package_representation(row),
            row["package_digest"],
        )

    def _authorized_document_snapshot(self, principal_id: str) -> tuple[list[Any], str]:
        before = self.store.cache_state(principal_id)["visibility_fingerprint"]
        rows = self.store.authorized_document_packages(principal_id)
        after = self.store.cache_state(principal_id)["visibility_fingerprint"]
        require(
            before == after,
            "authorization_changed",
            "Document visibility changed while the inventory was being assembled; retry the query.",
        )
        return sorted(rows, key=self._document_sort_key), after

    def list_documents(
        self,
        principal_id: str,
        identifier_prefix: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List only document packages currently authorized for one bound principal."""

        require(type(limit) is int and 1 <= limit <= 100, "invalid_limit", "Document limit must be from 1 to 100.")
        normalized_prefix = None if identifier_prefix is None else normalize_identifier(identifier_prefix)
        rows, visibility_fingerprint = self._authorized_document_snapshot(principal_id)
        if normalized_prefix is not None:
            rows = [row for row in rows if row["normalized_identifier"].startswith(normalized_prefix)]

        principal_fingerprint = hashlib.sha256(principal_id.encode("utf-8")).hexdigest()
        after_key: tuple[str, str, str, str, str] | None = None
        previously_returned = 0
        if cursor is not None:
            payload = self._decode_document_cursor(cursor)
            require(payload["principal_fingerprint"] == principal_fingerprint, "cursor_scope_mismatch", "The cursor belongs to a different principal.")
            require(payload["normalized_identifier_prefix"] == normalized_prefix, "cursor_scope_mismatch", "The cursor belongs to a different identifier prefix.")
            require(payload["visibility_fingerprint"] == visibility_fingerprint, "cursor_inventory_changed", "The authorized document inventory changed after the cursor was issued.")
            after_key = tuple(payload["last_key"])
            previously_returned = payload["returned_count"]
            rows = [row for row in rows if self._document_sort_key(row) > after_key]

        matching_total = previously_returned + len(rows)
        page_rows = rows[:limit]
        has_more = len(rows) > limit
        cumulative_returned = previously_returned + len(page_rows)
        next_cursor = None
        if has_more and page_rows:
            next_cursor = self._encode_cursor(
                {
                    "version": 1,
                    "operation": "list_documents",
                    "principal_fingerprint": principal_fingerprint,
                    "normalized_identifier_prefix": normalized_prefix,
                    "visibility_fingerprint": visibility_fingerprint,
                    "last_key": list(self._document_sort_key(page_rows[-1])),
                    "returned_count": cumulative_returned,
                    "expires_at": int(time.time()) + 900,
                }
            )

        documents = [
            {
                "pack_id": row["pack_id"],
                "document_family_id": row["document_family_id"],
                "identifier": row["identifier"],
                "normalized_identifier": row["normalized_identifier"],
                "title": row["title"],
                "edition_id": row["edition_id"],
                "revision": row["revision"],
                "publication_date": row["publication_date"],
                "representation": self._package_representation(row),
                "package_digest": row["package_digest"],
                "record_count": row["record_count"],
                "declared_coverage": self._declared_coverage(row),
            }
            for row in page_rows
        ]
        for row in page_rows:
            self.store.authorized_package(principal_id, row["package_digest"])
        require(
            self.store.cache_state(principal_id)["visibility_fingerprint"] == visibility_fingerprint,
            "authorization_changed",
            "Document visibility changed while the inventory was being assembled; retry the query.",
        )
        return {
            "schema_version": "0.1.0",
            "operation": "list_documents",
            "retrieval_mode": "authorized_installed_package_catalog",
            "filters": {"identifier_prefix": identifier_prefix, "normalized_identifier_prefix": normalized_prefix},
            "snapshot_sha256": visibility_fingerprint,
            "documents": documents,
            "page": {
                "returned": len(documents),
                "previously_returned": previously_returned,
                "cumulative_returned": cumulative_returned,
                "matching_authorized_package_count": matching_total,
                "has_more": has_more,
                "next_cursor": next_cursor,
                "cursor_ttl_seconds": 900 if next_cursor is not None else None,
            },
            "limitations": [
                "The inventory contains only packages currently authorized for the bound principal.",
                "Publisher currentness does not establish a project-approved baseline.",
            ],
        }

    def _resolve_candidates(self, rows: list[Any], normalized_identifier: str) -> tuple[list[dict[str, Any]], bool]:
        exact_rows = [row for row in rows if row["normalized_identifier"] == normalized_identifier]
        prefix_rows = [row for row in rows if row["normalized_identifier"].startswith(normalized_identifier)]
        seed_rows = exact_rows or prefix_rows
        family_ids = {row["document_family_id"] for row in seed_rows}
        related_rows = [row for row in rows if row["document_family_id"] in family_ids]
        candidates: list[dict[str, Any]] = []
        for row in related_rows:
            match_basis = (
                "exact_identifier_alternate_selector"
                if row in exact_rows
                else "identifier_prefix" if row in prefix_rows else "document_family"
            )
            candidates.append(
                {
                    "match_basis": match_basis,
                    "document_family_id": row["document_family_id"],
                    "identifier": row["identifier"],
                    "normalized_identifier": row["normalized_identifier"],
                    "title": row["title"],
                    "edition_id": row["edition_id"],
                    "revision": row["revision"],
                    "representation": self._package_representation(row),
                    "package_digest": row["package_digest"],
                    "resolve_selector": {
                        "identifier": row["identifier"],
                        "edition_id": row["edition_id"],
                        "representation": self._package_representation(row),
                    },
                }
            )
        candidates.sort(key=lambda candidate: (candidate["normalized_identifier"], candidate["edition_id"], candidate["representation"], candidate["package_digest"]))
        return candidates[:20], len(candidates) > 20

    def resolve_document(
        self,
        identifier: str,
        principal_id: str,
        edition_id: str | None = None,
        representation: str | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_identifier(identifier)
        before_visibility = self.store.cache_state(principal_id)["visibility_fingerprint"]
        rows = self.store.authorized_packages(principal_id, normalized, edition_id)
        if representation is not None:
            require(
                representation in {"page_text", "derived_structure", "reviewed_structure", "curated_records"},
                "invalid_representation",
                "The requested document representation is unsupported.",
            )
            rows = [row for row in rows if self._package_representation(row) == representation]
        if not rows:
            authorized_rows, candidate_visibility = self._authorized_document_snapshot(principal_id)
            require(before_visibility == candidate_visibility, "authorization_changed", "Document visibility changed while the resolution result was being assembled; retry the query.")
            candidates, candidates_truncated = self._resolve_candidates(authorized_rows, normalized)
            try:
                for candidate in candidates:
                    self.store.authorized_package(principal_id, candidate["package_digest"])
            except StandardsForgeError as exc:
                if exc.code != "not_found":
                    raise
                raise StandardsForgeError("authorization_changed", "Document visibility changed while the resolution result was being assembled; retry the query.") from exc
            require(self.store.cache_state(principal_id)["visibility_fingerprint"] == candidate_visibility, "authorization_changed", "Document visibility changed while the resolution result was being assembled; retry the query.")
            raise StandardsForgeError(
                "not_found",
                "No authorized resource matches the request.",
                {
                    "operation": "resolve_document",
                    "requested": {"identifier": identifier, "normalized_identifier": normalized, "edition_id": edition_id, "representation": representation},
                    "candidates": candidates,
                    "candidates_truncated": candidates_truncated,
                    "discovery_operation": "list_documents",
                },
            )
        if len(rows) != 1:
            for candidate_row in rows:
                self.store.authorized_package(principal_id, candidate_row["package_digest"])
            require(self.store.cache_state(principal_id)["visibility_fingerprint"] == before_visibility, "authorization_changed", "Document visibility changed while the resolution result was being assembled; retry the query.")
            raise StandardsForgeError(
                "ambiguous_document",
                "The identifier does not resolve to exactly one authorized package; provide an edition and representation, or use an exact package pin.",
                {
                    "candidates": [
                        {
                            "edition_id": row["edition_id"],
                            "representation": self._package_representation(row),
                            "package_digest": row["package_digest"],
                        }
                        for row in rows
                    ]
                },
            )
        row = rows[0]
        result = {
            "operation": "resolve_document",
            "retrieval_mode": "exact_identifier",
            "document_family_id": row["document_family_id"],
            "identifier": row["identifier"],
            "normalized_identifier": row["normalized_identifier"],
            "title": row["title"],
            "edition_id": row["edition_id"],
            "revision": row["revision"],
            "representation": self._package_representation(row),
            "package_digest": row["package_digest"],
        }
        current = self.store.authorized_package(principal_id, row["package_digest"])
        require(current["grant_policy_fingerprint"] == row["grant_policy_fingerprint"] and self.store.cache_state(principal_id)["visibility_fingerprint"] == before_visibility, "authorization_changed", "Document visibility changed while the resolution result was being assembled; retry the query.")
        return result

    @staticmethod
    def _record_payload(
        row: Any,
        object_path: Path,
        verification: _RequestVerificationContext | None = None,
    ) -> dict[str, Any]:
        verification = verification if verification is not None else _RequestVerificationContext()
        source = json.loads(row["source_json"])
        source_relative = source["path"]
        evidence_relative = source.get("text_path", source_relative)
        evidence_digest = source.get("text_sha256", source["sha256"])
        if source_relative != evidence_relative:
            verification.verified_file(
                object_path,
                source_relative,
                source["sha256"],
                "Stored source evidence failed its digest check.",
            )
        evidence_bytes = verification.verified_bytes(
            object_path,
            evidence_relative,
            evidence_digest,
            "Stored extracted source text failed its digest check.",
        )
        actual_quote_hash = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
        require(actual_quote_hash == source["quote_sha256"], "source_integrity_failure", "Stored evidence text failed its digest check.")
        citation = {
            "source_path": source["path"],
            "source_sha256": source["sha256"],
            "page": source["page"],
            "locator": source["locator"],
            "quote_sha256": source["quote_sha256"],
        }
        source_checks = {
            "source_digest_verified": True,
            "quote_digest_verified": True,
            "exact_quote_present": True,
        }
        if "text_path" in source:
            citation["text_path"] = source["text_path"]
            citation["text_sha256"] = source["text_sha256"]
            source_checks["extracted_text_digest_verified"] = True
        if "text_start_byte" in source or "text_end_byte" in source:
            require(
                type(source.get("text_start_byte")) is int
                and type(source.get("text_end_byte")) is int
                and 0 <= source["text_start_byte"] < source["text_end_byte"] <= len(evidence_bytes),
                "source_integrity_failure",
                "Stored evidence text offsets are invalid.",
            )
            start_byte = source["text_start_byte"]
            end_byte = source["text_end_byte"]
            quote_bytes = evidence_bytes[start_byte:end_byte]
            try:
                quote_text = quote_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise StandardsForgeError(
                    "source_integrity_failure",
                    "Stored evidence text offsets split UTF-8 text.",
                ) from exc
            require(
                quote_text == row["text"]
                and hashlib.sha256(quote_bytes).hexdigest() == source["quote_sha256"],
                "source_integrity_failure",
                "Stored evidence text offsets do not reproduce the exact record text.",
            )
            citation["text_start_byte"] = start_byte
            citation["text_end_byte"] = end_byte
        payload = {
            "record_id": row["record_id"],
            "kind": row["kind"],
            "clause_reference": row["clause_reference"],
            "heading": row["heading"],
            "text": row["text"],
            "derivation": json.loads(row["derivation_json"]),
            "citation": citation,
            "source_checks": source_checks,
        }
        structure = json.loads(row["structure_json"])
        if structure:
            def verify_span(span: Any, *, expected_text: str | None = None) -> None:
                require(isinstance(span, dict), "source_integrity_failure", "Stored structural source span is invalid.")
                required = {
                    "path", "sha256", "text_path", "text_sha256", "physical_page",
                    "start_byte", "end_byte", "quote_sha256",
                }
                require(required <= set(span), "source_integrity_failure", "Stored structural source span is incomplete.")
                require(
                    type(span["physical_page"]) is int and span["physical_page"] >= 1
                    and type(span["start_byte"]) is int and type(span["end_byte"]) is int
                    and 0 <= span["start_byte"] < span["end_byte"],
                    "source_integrity_failure",
                    "Stored structural source span offsets are invalid.",
                )
                verification.verified_file(
                    object_path,
                    span["path"],
                    span["sha256"],
                    "Stored structural source failed its digest check.",
                )
                verification.decoded_text(
                    object_path,
                    span["text_path"],
                    span["text_sha256"],
                )
                text_bytes = verification.verified_bytes(
                    object_path,
                    span["text_path"],
                    span["text_sha256"],
                    "Stored structural source text failed its digest check.",
                )
                require(
                    span["end_byte"] <= len(text_bytes),
                    "source_integrity_failure",
                    "Stored structural source span exceeds its text sidecar.",
                )
                quote_bytes = text_bytes[span["start_byte"]:span["end_byte"]]
                start_is_boundary = (
                    span["start_byte"] == 0 or text_bytes[span["start_byte"]] & 0xC0 != 0x80
                )
                end_is_boundary = (
                    span["end_byte"] == len(text_bytes) or text_bytes[span["end_byte"]] & 0xC0 != 0x80
                )
                require(
                    start_is_boundary and end_is_boundary,
                    "source_integrity_failure",
                    "Stored structural source span splits UTF-8 text.",
                )
                require(
                    hashlib.sha256(quote_bytes).hexdigest() == span["quote_sha256"],
                    "source_integrity_failure",
                    "Stored structural source span failed its quote digest check.",
                )
                if expected_text is not None:
                    require(
                        quote_bytes == expected_text.encode("utf-8"),
                        "source_integrity_failure",
                        "Stored structural source span does not reproduce the record text.",
                    )

            node_spans = structure.get("source_spans")
            require(isinstance(node_spans, list) and node_spans, "source_integrity_failure", "Stored structural node spans are missing.")
            for span in node_spans:
                verify_span(span, expected_text=row["text"])
                require(
                    span["path"] == source["path"]
                    and span["sha256"] == source["sha256"]
                    and span["text_path"] == evidence_relative
                    and span["text_sha256"] == evidence_digest
                    and span["physical_page"] == source["page"]
                    and span["quote_sha256"] == source["quote_sha256"],
                    "source_integrity_failure",
                    "Stored structural node span disagrees with its primary citation.",
                )

            relationships = structure.get("relationships")
            require(isinstance(relationships, list), "source_integrity_failure", "Stored structural relationships are invalid.")
            for relationship in relationships:
                require(isinstance(relationship, dict), "source_integrity_failure", "Stored structural relationship is invalid.")
                evidence_spans = relationship.get("evidence_spans")
                require(
                    isinstance(evidence_spans, list) and evidence_spans,
                    "source_integrity_failure",
                    "Stored structural relationship evidence spans are missing.",
                )
                for span in evidence_spans:
                    verify_span(span)
            payload["structure"] = structure
        elif "text_start_byte" not in source:
            source_text = verification.decoded_text(object_path, evidence_relative, evidence_digest)
            require(row["text"] in source_text, "source_integrity_failure", "Stored evidence text is absent from its preserved source.")
        return payload

    def _evidence_graph(
        self,
        package_digest: str,
        clause_references: list[str],
    ) -> tuple[list[Any], list[dict[str, str]]]:
        cache_key = self._closure_cache.key(
            {
                "package_digest": package_digest,
                "ordered_unique_clause_references": clause_references,
                "traversal": "required_edges_breadth_first_per_root_v1",
            }
        )
        cached = self._closure_cache.get(cache_key)
        if cached is not None:
            record_ids = cached.get("record_ids")
            relationships = cached.get("relationships")
            if isinstance(record_ids, list) and isinstance(relationships, list):
                rows = self.store.records_by_ids(package_digest, record_ids)
                if len(rows) == len(record_ids):
                    return rows, relationships
            self._closure_cache.discard(cache_key)

        rows, relationships, missing = self.store.evidence_graph(package_digest, clause_references)
        if missing:
            raise StandardsForgeError("not_found", "No authorized resource matches the request.")
        self._closure_cache.put(
            cache_key,
            {"record_ids": [row["record_id"] for row in rows], "relationships": relationships},
        )
        return rows, relationships

    def _evidence_graph_by_root(
        self,
        package_digest: str,
        clause_references: list[str],
    ) -> dict[str, tuple[list[Any], list[dict[str, str]]]]:
        """Batch-load a union closure, then project each root's legacy BFS packet."""

        references = list(dict.fromkeys(clause_references))
        rows, relationships = self._evidence_graph(package_digest, references)
        rows_by_id = {row["record_id"]: row for row in rows}
        rows_by_reference = {row["clause_reference"]: row for row in rows}
        edges_by_source: dict[str, list[dict[str, str]]] = {}
        for edge in relationships:
            edges_by_source.setdefault(edge["source_record_id"], []).append(edge)

        projected: dict[str, tuple[list[Any], list[dict[str, str]]]] = {}
        for reference in references:
            root = rows_by_reference.get(reference)
            if root is None:
                raise StandardsForgeError("not_found", "No authorized resource matches the request.")
            ordered_rows: list[Any] = []
            ordered_edges: list[dict[str, str]] = []
            queue = deque([root["record_id"]])
            traversed: set[str] = set()
            while queue:
                record_id = queue.popleft()
                if record_id in traversed:
                    continue
                traversed.add(record_id)
                row = rows_by_id.get(record_id)
                if row is None:
                    raise StandardsForgeError("incomplete_dependency", "Required evidence dependency is unavailable.")
                ordered_rows.append(row)
                for edge in edges_by_source.get(record_id, []):
                    ordered_edges.append(edge)
                    if edge["target_record_id"] not in traversed:
                        queue.append(edge["target_record_id"])
            projected[reference] = (ordered_rows, ordered_edges)
        return projected

    def get_clause(
        self,
        package_digest: str,
        clause_reference: str | None = None,
        principal_id: str | None = None,
        max_bytes: int | None = None,
        response_profile: str | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_package_digest(package_digest)
        require(isinstance(principal_id, str) and bool(principal_id), "invalid_principal", "A trusted principal is required.")
        if clause_reference is not None:
            require(
                isinstance(clause_reference, str) and bool(clause_reference.strip()),
                "invalid_clause_reference",
                "A clause reference must be non-empty text.",
            )
        if record_id is not None:
            require(isinstance(record_id, str) and bool(record_id), "invalid_record_id", "A record ID must be non-empty text.")
        require(
            clause_reference is not None or record_id is not None,
            "invalid_record_selector",
            "A clause reference or exact record ID is required.",
        )
        package = self.store.authorized_package(principal_id, package_digest)
        if clause_reference is None:
            selected = self.store.record_by_id(package_digest, record_id)
            if selected is None:
                raise StandardsForgeError("not_found", "No authorized resource matches the request.")
            clause_reference = selected["clause_reference"]
        declared_coverage = self._declared_coverage(package)
        coverage_dimensions = self._coverage_dimensions(
            declared_coverage,
            dependency_retrieval_complete=True,
            dependency_retrieval_status="complete_for_returned_required_graph",
            traversal_complete=None,
            traversal_status="not_requested",
        )
        root = Path(package["object_path"])
        ordered_rows, relationships = self._evidence_graph(package_digest, [clause_reference.strip()])
        if record_id is not None:
            root_row = next((row for row in ordered_rows if row["clause_reference"] == clause_reference.strip()), None)
            require(
                root_row is not None and root_row["record_id"] == record_id,
                "record_selector_mismatch",
                "The record ID does not match the clause reference in the pinned package.",
            )
        verification = _RequestVerificationContext()

        packet: dict[str, Any] = {
            "schema_version": "0.1.0",
            "operation": "get_clause",
            "retrieval_mode": "exact_pinned_clause",
            "package": self._package_payload(package),
            "evidence": [self._record_payload(row, root, verification) for row in ordered_rows],
            "required_relationships": relationships,
            "completeness": {
                "corpus_scope": declared_coverage["corpus_scope"],
                "edition_composition": declared_coverage["edition_composition"],
                "parsed_source_coverage": declared_coverage["parsed_source_coverage"],
                "dependency_closure": "complete_for_returned_required_graph",
                "enumeration_traversal": "not_requested",
                "output_budget_coverage": "complete",
                "complete_for_requested_scope": self._dimensions_complete(
                    coverage_dimensions, require_traversal=False
                ),
                "scope_interpretation": "selected_record_and_required_dependencies_only_not_corpus_completeness",
                "declared_pack_coverage": declared_coverage,
                "dimensions": coverage_dimensions,
            },
            "limitations": [
                "Exact quote checks do not establish PDF visual fidelity.",
                "This evidence packet is not an applicability or compliance decision.",
            ],
        }
        packet = self._render_response_profile(packet, response_profile)
        self._finalize_budget(packet, max_bytes)
        self.store.authorized_package(principal_id, package_digest)
        return packet

    def build_context(
        self,
        package_digest: str,
        clause_references: list[str],
        principal_id: str,
        max_bytes: int | None = None,
        response_profile: str | None = None,
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
        declared_coverage = self._declared_coverage(package)
        coverage_dimensions = self._coverage_dimensions(
            declared_coverage,
            dependency_retrieval_complete=True,
            dependency_retrieval_status="complete_for_returned_required_graph",
            traversal_complete=None,
            traversal_status="not_requested",
        )
        ordered_rows, relationships = self._evidence_graph(package_digest, requested)
        verification = _RequestVerificationContext()
        evidence = [self._record_payload(row, Path(package["object_path"]), verification) for row in ordered_rows]

        packet: dict[str, Any] = {
            "schema_version": "0.1.0",
            "operation": "build_context",
            "retrieval_mode": "exact_pinned_multi_clause",
            "package": self._package_payload(package),
            "requested_clause_references": requested,
            "evidence": evidence,
            "required_relationships": relationships,
            "completeness": {
                "corpus_scope": declared_coverage["corpus_scope"],
                "edition_composition": declared_coverage["edition_composition"],
                "parsed_source_coverage": declared_coverage["parsed_source_coverage"],
                "dependency_closure": "complete_for_returned_required_graph",
                "enumeration_traversal": "not_requested",
                "output_budget_coverage": "complete",
                "complete_for_requested_scope": self._dimensions_complete(
                    coverage_dimensions, require_traversal=False
                ),
                "scope_interpretation": "selected_records_and_required_dependencies_only_not_corpus_completeness",
                "declared_pack_coverage": declared_coverage,
                "dimensions": coverage_dimensions,
            },
            "limitations": [
                "Exact quote checks do not establish PDF visual fidelity.",
                "Context assembly does not decide applicability or compliance.",
            ],
        }
        packet = self._render_response_profile(packet, response_profile)
        self._finalize_budget(packet, max_bytes)
        self.store.authorized_package(principal_id, package_digest)
        return packet

    def _encode_cursor(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        signature = hmac.new(self.store.cursor_secret(), raw, hashlib.sha256).digest()
        body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        tag = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return body + "." + tag

    def _decode_signed_cursor(self, token: str) -> dict[str, Any]:
        require(isinstance(token, str) and 1 <= len(token) <= 4096, "invalid_cursor", "The continuation cursor is invalid.")
        try:
            body, tag = token.split(".", 1)
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            signature = base64.urlsafe_b64decode(tag + "=" * (-len(tag) % 4))
        except (ValueError, TypeError, binascii.Error) as exc:
            raise StandardsForgeError("invalid_cursor", "The continuation cursor is invalid.") from exc
        canonical_body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        canonical_tag = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        require(
            body == canonical_body and tag == canonical_tag,
            "invalid_cursor",
            "The continuation cursor encoding is not canonical.",
        )
        expected = hmac.new(self.store.cursor_secret(), raw, hashlib.sha256).digest()
        require(hmac.compare_digest(signature, expected), "invalid_cursor", "The continuation cursor signature is invalid.")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StandardsForgeError("invalid_cursor", "The continuation cursor payload is invalid.") from exc
        require(isinstance(payload, dict), "invalid_cursor", "The continuation cursor payload is invalid.")
        require(type(payload.get("expires_at")) in {int, float}, "invalid_cursor", "The continuation cursor expiry is invalid.")
        require(payload["expires_at"] >= time.time(), "expired_cursor", "The continuation cursor has expired.")
        return payload

    def _decode_cursor(self, token: str) -> dict[str, Any]:
        payload = self._decode_signed_cursor(token)
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
        return payload

    def _decode_document_cursor(self, token: str) -> dict[str, Any]:
        payload = self._decode_signed_cursor(token)
        required_keys = {
            "version", "operation", "principal_fingerprint", "normalized_identifier_prefix",
            "visibility_fingerprint", "last_key", "returned_count", "expires_at",
        }
        require(set(payload) == required_keys, "invalid_cursor", "The continuation cursor fields are invalid.")
        require(payload["version"] == 1 and payload["operation"] == "list_documents", "invalid_cursor", "The continuation cursor version or operation is unsupported.")
        require(isinstance(payload["last_key"], list) and len(payload["last_key"]) == 5 and all(isinstance(value, str) for value in payload["last_key"]), "invalid_cursor", "The continuation cursor document key is invalid.")
        require(type(payload["returned_count"]) is int and payload["returned_count"] >= 0, "invalid_cursor", "The continuation cursor count is invalid.")
        require(payload["normalized_identifier_prefix"] is None or isinstance(payload["normalized_identifier_prefix"], str), "invalid_cursor", "The continuation cursor prefix is invalid.")
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
        declared_coverage = self._declared_coverage(package)
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
        page_references = [row["clause_reference"] for row in page_rows]
        closures_by_root = (
            self._evidence_graph_by_root(package_digest, page_references)
            if page_references
            else {}
        )
        verification = _RequestVerificationContext()
        object_path = Path(package["object_path"])
        obligations: list[dict[str, Any]] = []
        for row in page_rows:
            ordered_rows, required_relationships = closures_by_root[row["clause_reference"]]
            obligations.append(
                {
                    "clause_reference": row["clause_reference"],
                    "record_id": row["record_id"],
                    "evidence": [
                        self._record_payload(evidence_row, object_path, verification)
                        for evidence_row in ordered_rows
                    ],
                    "required_relationships": required_relationships,
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
        traversal_complete = not has_more and cumulative_returned == total
        coverage_dimensions = self._coverage_dimensions(
            declared_coverage,
            dependency_retrieval_complete=True,
            dependency_retrieval_status="complete_for_returned_required_graph",
            traversal_complete=traversal_complete,
            traversal_status="complete" if traversal_complete else "continuation_required",
        )
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
                "corpus_scope": declared_coverage["corpus_scope"],
                "edition_composition": declared_coverage["edition_composition"],
                "parsed_source_coverage": declared_coverage["parsed_source_coverage"],
                "dependency_closure": "complete_for_returned_records",
                "enumeration_traversal": "complete" if not has_more else "continuation_required",
                "output_budget_coverage": "complete_for_page",
                "complete_for_requested_scope": self._dimensions_complete(
                    coverage_dimensions, require_traversal=True
                ),
                "packet_contains_entire_scope": previously_returned == 0 and not has_more,
                "scope_interpretation": "explicitly_classified_obligation_rows_only_not_extraction_completeness",
                "declared_pack_coverage": declared_coverage,
                "classified_obligation_count": total,
                "dimensions": coverage_dimensions,
            },
            "limitations": [
                "Enumeration covers records explicitly classified as obligations in the pinned pack.",
                "Extraction completeness remains distinct from database traversal completeness.",
                "A final page can complete a cursor traversal without repeating evidence from earlier pages.",
            ],
        }
        self._finalize_budget(response, max_bytes)
        current_package = self.store.authorized_package(principal_id, package_digest)
        require(
            current_package["grant_policy_fingerprint"] == package["grant_policy_fingerprint"],
            "authorization_changed",
            "Enumeration authorization changed while the result was being assembled; retry the query.",
        )
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
        before_verification = _RequestVerificationContext()
        after_verification = _RequestVerificationContext()
        changes: list[dict[str, Any]] = []
        status_by_id: dict[str, str] = {}
        comparison_fields = (
            "kind",
            "clause_reference",
            "heading",
            "text",
            "statement_role",
            "derivation_json",
            "structure_json",
        )
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
                change["before"] = self._record_payload(before, before_root, before_verification)
            if status in {"added", "modified"} and after is not None:
                change["after"] = self._record_payload(after, after_root, after_verification)
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

    def search(
        self,
        query: str,
        principal_id: str,
        limit: int = 20,
        package_digest: str | None = None,
        scope_prefix: str | None = None,
    ) -> dict[str, Any]:
        require(type(limit) is int and 1 <= limit <= 100, "invalid_limit", "Search limit must be from 1 to 100.")
        require(isinstance(query, str), "invalid_query", "Search query must be text.")
        requested_package_digest = package_digest
        requested_scope_prefix = scope_prefix
        if requested_package_digest is not None:
            self._validate_package_digest(requested_package_digest)
            self.store.authorized_package(principal_id, requested_package_digest)
        if scope_prefix is not None:
            require(isinstance(scope_prefix, str) and bool(scope_prefix.strip()), "invalid_scope", "Search scope must be non-empty text.")
            scope_prefix = scope_prefix.strip()
        tokens = re.findall(r"[\w./-]+", query, flags=re.UNICODE)
        require(tokens, "invalid_query", "Search query contains no searchable terms.")
        require(
            len(tokens) <= 32,
            "invalid_query",
            "Search queries may contain at most 32 searchable terms.",
            max_terms=32,
            actual_terms=len(tokens),
        )
        fts_query = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        for _ in range(2):
            state = self.store.cache_state(principal_id)
            cache_key = self._search_cache.key(
                {
                    "principal_sha256": hashlib.sha256(principal_id.encode("utf-8")).hexdigest(),
                    "fts_query": fts_query,
                    "limit": limit,
                    "package_digest": requested_package_digest,
                    "scope_prefix": scope_prefix,
                    "ranker": "sqlite-fts5-bm25-v2-snippet-projection",
                    **state,
                }
            )
            cached = self._search_cache.get(cache_key)
            if cached is not None:
                if self.store.cache_state(principal_id) == state:
                    if requested_package_digest is not None:
                        self.store.authorized_package(principal_id, requested_package_digest)
                    cached["query"] = query
                    cached["filters"] = {
                        "package_digest": requested_package_digest,
                        "scope_prefix": requested_scope_prefix,
                    }
                    return cached
                continue

            rows = self.store.search(principal_id, fts_query, limit, requested_package_digest, scope_prefix)
            coverage_by_package: dict[str, dict[str, Any]] = {}
            for row in rows:
                result_package_digest = row["package_digest"]
                if result_package_digest in coverage_by_package:
                    continue
                declared_coverage = self._declared_coverage(row)
                coverage_by_package[result_package_digest] = {
                    "declared_pack_coverage": declared_coverage,
                    "dimensions": self._coverage_dimensions(
                        declared_coverage,
                        dependency_retrieval_complete=None,
                        dependency_retrieval_status="not_requested",
                        traversal_complete=False,
                        traversal_status="ranked_search_window_not_exhaustive_traversal",
                    ),
                }
            search_results: list[dict[str, Any]] = []
            for row in rows:
                result = {
                    "package_digest": row["package_digest"],
                    "edition_id": row["edition_id"],
                    "identifier": row["identifier"],
                    "title": row["title"],
                    "record_id": row["record_id"],
                    "kind": row["kind"],
                    "clause_reference": row["clause_reference"],
                    "heading": row["heading"],
                    "source": json.loads(row["source_json"]),
                    "matched_snippet": row["matched_snippet"],
                    "score": row["score"],
                    "evidence_selector": {
                        "operation": "get_clause",
                        "package_digest": row["package_digest"],
                        "record_id": row["record_id"],
                        "clause_reference": row["clause_reference"],
                    },
                }
                if row["heading_ancestry"]:
                    result["heading_ancestry"] = row["heading_ancestry"]
                search_results.append(result)
            packet = {
                "operation": "search",
                "retrieval_mode": "lexical_fts5",
                "query": query,
                "snippet_markers": {"start": "⟦", "end": "⟧"},
                "filters": {
                    "package_digest": requested_package_digest,
                    "scope_prefix": requested_scope_prefix,
                },
                "results": search_results,
                "coverage_by_package": coverage_by_package,
                "completeness": {
                    "database_traversal": {
                        "complete": False,
                        "status": "ranked_search_window_not_exhaustive_traversal",
                        "returned": len(rows),
                        "limit": limit,
                    },
                    "response_fit": {"complete": True, "status": "complete", "unit": "records"},
                },
                "limitations": ["Lexical rank is a discovery signal, not applicability or compliance."],
            }
            if self.store.cache_state(principal_id) == state:
                if requested_package_digest is not None:
                    self.store.authorized_package(principal_id, requested_package_digest)
                self._search_cache.put(cache_key, packet)
                return packet
        raise StandardsForgeError(
            "authorization_changed",
            "Search authorization changed while the result was being assembled; retry the query.",
        )

    def revoke(self, package_digest: str, principal_id: str) -> dict[str, Any]:
        changed = self.store.revoke(principal_id, package_digest)
        return {"operation": "revoke", "revoked": changed, "package_digest": package_digest, "principal_id": principal_id}
