from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from .errors import StandardsForgeError, require
from .identity import normalize_identifier
from .models import InventoryEntry, ValidatedPack


MAX_FILES = 512
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024
ALLOWED_SUFFIXES = {".json", ".txt", ".md", ".pdf"}
REQUIRED_FILES = {"manifest.json", "rights.json", "records.json"}

_MANIFEST_KEYS = {
    "schema_version",
    "pack_id",
    "document_family_id",
    "edition_id",
    "publisher",
    "identifier",
    "title",
    "revision",
    "publication_date",
    "category",
    "representation",
    "inventory_path",
    "rights_path",
    "records_path",
    "coverage",
}
_RIGHTS_KEYS = {
    "rights_schema_version",
    "content_class",
    "redistribution",
    "processing",
    "model_use",
    "statement",
}
_RECORD_KEYS = {
    "record_id",
    "edition_id",
    "kind",
    "clause_reference",
    "heading",
    "text",
    "source",
    "derivation",
    "dependencies",
    "structure",
}
_SOURCE_REQUIRED_KEYS = {"path", "sha256", "page", "locator", "quote_sha256"}
_SOURCE_TEXT_KEYS = {"text_path", "text_sha256"}
_SOURCE_OFFSET_KEYS = {"text_start_byte", "text_end_byte"}
_SOURCE_KEYS = _SOURCE_REQUIRED_KEYS | _SOURCE_TEXT_KEYS | _SOURCE_OFFSET_KEYS
_DEPENDENCY_KEYS = {"relationship", "target_record_id", "required"}
_DERIVATION_KEYS = {"statement_role", "method", "review_status"}
_STRUCTURE_REQUIRED_KEYS = {
    "logical_id",
    "content_sha256",
    "parent_logical_id",
    "ordinal",
    "source_spans",
    "relationships",
}
_STRUCTURE_OPTIONAL_KEYS = {"semantics", "review"}
_STRUCTURE_KEYS = _STRUCTURE_REQUIRED_KEYS | _STRUCTURE_OPTIONAL_KEYS
_STRUCTURE_SPAN_KEYS = {
    "path",
    "sha256",
    "text_path",
    "text_sha256",
    "physical_page",
    "start_byte",
    "end_byte",
    "quote_sha256",
}
_STRUCTURE_RELATIONSHIP_KEYS = {
    "relationship",
    "target_status",
    "target_logical_id",
    "target_locator",
    "candidate_logical_ids",
    "required",
    "method",
    "review_status",
    "evidence_spans",
}
_SEMANTIC_KEYS = {
    "schema_version",
    "content_role",
    "normativity",
    "statement",
    "qualifiers",
    "quantities",
    "unresolved_issues",
    "project_applicability",
}
_REVIEW_EVENT_KEYS = {
    "schema_version",
    "status",
    "reviewed_content_sha256",
    "scope",
    "reviewer",
    "reviewed_at",
    "method",
    "tool",
    "unresolved_issues",
    "attestation",
}
_STRUCTURAL_KINDS = {
    "document",
    "section",
    "clause",
    "paragraph",
    "list",
    "list_item",
    "table",
    "table_row",
    "table_cell",
    "definition",
    "note",
    "figure",
    "unsupported_region",
}
_STRUCTURAL_RELATIONSHIPS = {
    "contains",
    "sequence_after",
    "governed_by",
    "defines",
    "uses_definition",
    "qualifies",
    "exception_to",
    "references",
    "caption_of",
    "table_footnote_for",
    "footnote_for",
    "header_for",
    "illustrates",
    "continues_on",
}
_COVERAGE_KEYS = {
    "corpus_scope",
    "edition_composition",
    "parsed_source_coverage",
    "dependency_closure",
    "enumeration_traversal",
    "output_budget_coverage",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        raise StandardsForgeError("invalid_pack_path", "An inventoried file could not be read.", {"path": path.name}) from exc


def _safe_relative_path(value: str) -> PurePosixPath:
    require(isinstance(value, str) and bool(value), "invalid_pack_path", "Pack paths must be non-empty strings.")
    path = PurePosixPath(value.replace("\\", "/"))
    require(not path.is_absolute(), "invalid_pack_path", "Absolute paths are forbidden in a pack.", path=value)
    require(".." not in path.parts, "invalid_pack_path", "Parent traversal is forbidden in a pack.", path=value)
    require(path.suffix.lower() in ALLOWED_SUFFIXES, "executable_pack_content", "Pack file type is not data-only.", path=value)
    return path


def _read_json(path: Path) -> Any:
    try:
        size = path.stat().st_size
        require(size <= MAX_JSON_BYTES, "pack_limit_exceeded", "A JSON file exceeds the size limit.", path=path.name)
        return json.loads(path.read_text(encoding="utf-8"))
    except StandardsForgeError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_pack_json", "A required pack JSON file is invalid.", {"path": path.name}) from exc


def _strict_object(value: Any, allowed: set[str], code: str, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), code, f"{label} must be a JSON object.")
    unknown = sorted(set(value) - allowed)
    require(not unknown, code, f"{label} has unknown fields.", fields=unknown)
    return value


def _span_indices(value: Any, span_count: int, label: str) -> list[int]:
    require(
        isinstance(value, list)
        and value
        and len(value) == len(set(value))
        and all(type(index) is int and 0 <= index < span_count for index in value)
        and value == sorted(value),
        "invalid_record",
        f"{label} span indices are invalid.",
    )
    return value


def _validate_semantic_record(
    value: Any,
    *,
    record_text: str,
    statement_role: str,
    kind: str,
    span_fragments: list[str],
) -> dict[str, Any]:
    semantics = _strict_object(value, _SEMANTIC_KEYS, "invalid_record", "record semantics")
    require(set(semantics) == _SEMANTIC_KEYS, "invalid_record", "Every semantic field is required.")
    require(semantics["schema_version"] == "0.1.0", "invalid_record", "Unsupported semantic schema.")
    content_roles = {
        "requirement_candidate", "governing_condition", "exception", "applicability_statement",
        "definition", "table_header", "table_row", "table_footnote", "note", "prose",
    }
    require(semantics["content_role"] in content_roles, "invalid_record", "Unsupported semantic content role.")
    require(semantics["normativity"] in {"normative", "informative", "mixed", "unclassified"}, "invalid_record", "Unsupported semantic normativity.")
    require(semantics["project_applicability"] == "not_decided", "invalid_record", "Semantic evidence cannot decide project applicability.")
    issues = semantics["unresolved_issues"]
    require(isinstance(issues, list) and len(issues) == len(set(issues)) and all(isinstance(item, str) and item for item in issues), "invalid_record", "Semantic unresolved issues are invalid.")

    def selected_text(indices: list[int]) -> str:
        return "\n".join(span_fragments[index] for index in indices)

    statement = semantics["statement"]
    if semantics["content_role"] == "requirement_candidate":
        require(statement_role == "obligation" and isinstance(statement, dict), "invalid_record", "Requirement candidates require an explicit obligation classification and statement decomposition.")
    if statement is not None:
        statement = _strict_object(statement, {"subject", "action", "modality", "polarity", "exact_text", "span_indices"}, "invalid_record", "semantic statement")
        require(set(statement) == {"subject", "action", "modality", "polarity", "exact_text", "span_indices"}, "invalid_record", "Every semantic statement field is required.")
        require(all(isinstance(statement[key], str) and statement[key] for key in ("subject", "action", "exact_text")), "invalid_record", "Semantic statement text fields are invalid.")
        require(statement["modality"] in {"shall", "must", "should", "may", "will", "other"} and statement["polarity"] in {"affirmative", "negative"}, "invalid_record", "Semantic statement modality or polarity is invalid.")
        indices = _span_indices(statement["span_indices"], len(span_fragments), "Semantic statement")
        require(statement["exact_text"] in selected_text(indices), "invalid_record", "Semantic statement exact text is absent from its cited spans.")
        statement_lower = statement["exact_text"].casefold()
        require(statement["subject"].casefold() in statement_lower and statement["action"].casefold() in statement_lower, "invalid_record", "Semantic statement subject or action is absent from exact text.")
        if statement["modality"] != "other":
            require(statement["modality"] in statement_lower.split(), "invalid_record", "Semantic statement modality is absent from exact text.")
    for qualifier in semantics["qualifiers"]:
        qualifier = _strict_object(qualifier, {"kind", "exact_text", "span_indices"}, "invalid_record", "semantic qualifier")
        require(set(qualifier) == {"kind", "exact_text", "span_indices"}, "invalid_record", "Every semantic qualifier field is required.")
        require(qualifier["kind"] in {"condition", "exception", "source_applicability", "test_condition", "acceptance_criterion", "tailoring_instruction"}, "invalid_record", "Semantic qualifier kind is invalid.")
        indices = _span_indices(qualifier["span_indices"], len(span_fragments), "Semantic qualifier")
        require(isinstance(qualifier["exact_text"], str) and qualifier["exact_text"] in selected_text(indices), "invalid_record", "Semantic qualifier exact text is absent from its cited spans.")
    for quantity in semantics["quantities"]:
        quantity = _strict_object(quantity, {"raw", "value", "unit", "tolerance", "span_indices"}, "invalid_record", "semantic quantity")
        require(set(quantity) == {"raw", "value", "unit", "tolerance", "span_indices"}, "invalid_record", "Every semantic quantity field is required.")
        indices = _span_indices(quantity["span_indices"], len(span_fragments), "Semantic quantity")
        require(isinstance(quantity["raw"], str) and quantity["raw"] in selected_text(indices), "invalid_record", "Semantic quantity raw text is absent from its cited spans.")
        require(all(quantity[key] is None or isinstance(quantity[key], str) for key in ("value", "unit", "tolerance")), "invalid_record", "Semantic quantity fields must be text or null.")
    require(record_text == "\n".join(span_fragments), "invalid_record", "Semantic record text is not the exact ordered span assembly.")
    if semantics["content_role"] == "definition":
        require(kind == "definition", "invalid_record", "Definition semantics require a definition node.")
    if semantics["content_role"].startswith("table_"):
        expected_kind = {"table_header": "table_cell", "table_row": "table_row", "table_footnote": "note"}[semantics["content_role"]]
        require(kind == expected_kind, "invalid_record", "Table semantics disagree with the record kind.")
    return semantics


def _validate_review_event(
    value: Any,
    *,
    content_sha256: str,
    has_semantics: bool,
) -> dict[str, Any]:
    review = _strict_object(value, _REVIEW_EVENT_KEYS, "invalid_record", "review event")
    require(set(review) == _REVIEW_EVENT_KEYS, "invalid_record", "Every review-event field is required.")
    require(review["schema_version"] == "0.1.0", "invalid_record", "Unsupported review-event schema.")
    require(review["status"] in {"agent_reviewed", "human_verified", "human_verified_with_uncertainty"}, "invalid_record", "Rejected or unknown review status cannot be installed as reviewed evidence.")
    require(review["reviewed_content_sha256"] == content_sha256, "invalid_record", "Review event binds different content.")
    expected_scope = "structure_and_semantics" if has_semantics else "structure_only"
    require(review["scope"] == expected_scope, "invalid_record", "Review-event scope disagrees with the record.")
    reviewer = _strict_object(review["reviewer"], {"id", "type"}, "invalid_record", "reviewer")
    require(set(reviewer) == {"id", "type"} and isinstance(reviewer["id"], str) and reviewer["id"] and reviewer["type"] in {"agent", "human"}, "invalid_record", "Review identity is invalid.")
    require(not (reviewer["type"] == "agent" and review["status"].startswith("human_")), "invalid_record", "Agent review cannot claim human verification.")
    require(isinstance(review["reviewed_at"], str) and review["reviewed_at"], "invalid_record", "Review timestamp is required.")
    try:
        datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise StandardsForgeError("invalid_record", "Review timestamp is invalid.") from exc
    require(isinstance(review["method"], str) and review["method"], "invalid_record", "Review method is required.")
    tool = review["tool"]
    if reviewer["type"] == "agent":
        require(isinstance(tool, dict), "invalid_record", "Agent review requires tool provenance.")
    if tool is not None:
        tool = _strict_object(tool, {"name", "version", "configuration_sha256"}, "invalid_record", "review tool")
        require(set(tool) == {"name", "version", "configuration_sha256"} and all(isinstance(tool[key], str) and tool[key] for key in ("name", "version")), "invalid_record", "Review tool identity is invalid.")
        configuration_sha256 = tool["configuration_sha256"]
        require(configuration_sha256 is None or isinstance(configuration_sha256, str) and len(configuration_sha256) == 64 and all(character in "0123456789abcdef" for character in configuration_sha256), "invalid_record", "Review tool configuration digest is invalid.")
    issues = review["unresolved_issues"]
    require(isinstance(issues, list) and len(issues) == len(set(issues)) and all(isinstance(item, str) and item for item in issues), "invalid_record", "Review unresolved issues are invalid.")
    require(review["attestation"] == "extraction_review_not_project_applicability_or_approval", "invalid_record", "Review event cannot assert project applicability or approval.")
    return review


def _validate_inventory(root: Path) -> tuple[tuple[InventoryEntry, ...], str]:
    raw = _strict_object(
        _read_json(root / "inventory.json"),
        {"schema_version", "algorithm", "files"},
        "invalid_inventory",
        "inventory",
    )
    require(raw.get("schema_version") == "0.1.0", "unsupported_schema_version", "Unsupported inventory schema.")
    require(raw.get("algorithm") == "sha256", "invalid_inventory", "Only SHA-256 inventories are supported.")
    files = raw.get("files")
    require(isinstance(files, list) and 1 <= len(files) <= MAX_FILES, "invalid_inventory", "Inventory files must be a bounded non-empty list.")

    entries: list[InventoryEntry] = []
    seen: set[str] = set()
    total = 0
    for item in files:
        item = _strict_object(item, {"path", "sha256", "bytes"}, "invalid_inventory", "inventory entry")
        rel = _safe_relative_path(item.get("path"))
        rel_text = rel.as_posix()
        require(rel_text != "inventory.json", "invalid_inventory", "The inventory cannot list itself.")
        require(rel_text not in seen, "invalid_inventory", "Inventory paths must be unique.", path=rel_text)
        expected_hash = item.get("sha256")
        expected_size = item.get("bytes")
        require(isinstance(expected_hash, str) and len(expected_hash) == 64, "invalid_inventory", "Invalid SHA-256 value.", path=rel_text)
        require(type(expected_size) is int and expected_size >= 0, "invalid_inventory", "Invalid byte count.", path=rel_text)
        disk_path = root.joinpath(*rel.parts)
        require(disk_path.is_file(), "missing_pack_file", "An inventoried file is missing.", path=rel_text)
        try:
            actual_size = disk_path.stat().st_size
        except OSError as exc:
            raise StandardsForgeError("invalid_pack_path", "An inventoried file could not be read.", {"path": rel_text}) from exc
        require(actual_size == expected_size, "pack_size_mismatch", "An inventoried byte count does not match.", path=rel_text)
        require(_file_sha256(disk_path) == expected_hash, "pack_hash_mismatch", "An inventoried digest does not match.", path=rel_text)
        total += actual_size
        require(total <= MAX_TOTAL_BYTES, "pack_limit_exceeded", "Pack content exceeds the total size limit.")
        seen.add(rel_text)
        entries.append(InventoryEntry(rel_text, expected_hash, expected_size))

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "inventory.json"
    }
    require(actual == seen, "untracked_pack_content", "Every pack file must be inventoried.", missing=sorted(actual - seen), extra=sorted(seen - actual))
    require(REQUIRED_FILES <= seen, "missing_pack_file", "The pack is missing required contract files.", files=sorted(REQUIRED_FILES - seen))
    entries.sort(key=lambda entry: entry.path)
    package_digest = _sha256(_canonical_json([{"path": e.path, "sha256": e.sha256, "bytes": e.bytes} for e in entries]))
    return tuple(entries), package_digest


def validate_pack_directory(root: str | Path) -> ValidatedPack:
    pack_root = Path(root).resolve()
    require(pack_root.is_dir(), "pack_not_found", "The pack directory does not exist.")
    symlinks = [path.relative_to(pack_root).as_posix() for path in pack_root.rglob("*") if path.is_symlink()]
    require(not symlinks, "invalid_pack_path", "Symbolic links are forbidden in a pack.", paths=sorted(symlinks))
    require((pack_root / "inventory.json").is_file(), "missing_pack_file", "inventory.json is required.")
    inventory, package_digest = _validate_inventory(pack_root)

    manifest = _strict_object(_read_json(pack_root / "manifest.json"), _MANIFEST_KEYS, "invalid_manifest", "manifest")
    require(manifest.get("schema_version") == "0.1.0", "unsupported_schema_version", "Unsupported manifest schema.")
    for key in (
        "pack_id", "document_family_id", "edition_id", "publisher", "identifier", "title",
        "revision", "publication_date", "category", "inventory_path", "rights_path", "records_path",
    ):
        require(isinstance(manifest.get(key), str) and bool(manifest[key]), "invalid_manifest", f"{key} is required.")
    try:
        date.fromisoformat(manifest["publication_date"])
    except ValueError as exc:
        raise StandardsForgeError("invalid_manifest", "publication_date must be an ISO calendar date.") from exc
    require(manifest["inventory_path"] == "inventory.json", "invalid_manifest", "The inventory path must be inventory.json.")
    require(manifest["rights_path"] == "rights.json", "invalid_manifest", "The rights path must be rights.json.")
    require(manifest["records_path"] == "records.json", "invalid_manifest", "The records path must be records.json.")
    if "representation" in manifest:
        require(
            manifest["representation"] in {"page_text", "derived_structure", "reviewed_structure", "curated_records"},
            "invalid_manifest",
            "The manifest representation is unsupported.",
        )
    normalize_identifier(manifest["identifier"])
    coverage = _strict_object(manifest.get("coverage"), _COVERAGE_KEYS, "invalid_manifest", "coverage")
    require(set(coverage) == _COVERAGE_KEYS, "invalid_manifest", "All completeness dimensions are required.")
    require(all(isinstance(value, str) and value for value in coverage.values()), "invalid_manifest", "Completeness values must be non-empty strings.")

    rights = _strict_object(_read_json(pack_root / "rights.json"), _RIGHTS_KEYS, "invalid_rights", "rights")
    require(rights.get("rights_schema_version") == "0.1.0", "unsupported_schema_version", "Unsupported rights schema.")
    for key in ("content_class", "redistribution", "model_use", "statement"):
        require(isinstance(rights.get(key), str) and bool(rights[key]), "invalid_rights", f"{key} is required.")
    require(isinstance(rights.get("processing"), list) and all(isinstance(v, str) for v in rights["processing"]), "invalid_rights", "processing must be a string list.")

    raw_records = _strict_object(_read_json(pack_root / "records.json"), {"schema_version", "records"}, "invalid_records", "records document")
    records_schema_version = raw_records.get("schema_version")
    require(
        records_schema_version in {"0.1.0", "0.2.0"},
        "unsupported_schema_version",
        "Unsupported records schema.",
    )
    require(isinstance(raw_records.get("records"), list) and raw_records["records"], "invalid_records", "At least one record is required.")

    inventory_by_path = {entry.path: entry for entry in inventory}
    records: list[dict[str, Any]] = []
    record_ids: set[str] = set()
    clause_references: set[str] = set()
    logical_ids: set[str] = set()
    evidence_text_cache: dict[str, str] = {}
    evidence_bytes_cache: dict[str, bytes] = {}
    for record in raw_records["records"]:
        record = dict(_strict_object(record, _RECORD_KEYS, "invalid_record", "record"))
        for key in ("record_id", "edition_id", "kind", "clause_reference", "heading"):
            require(isinstance(record.get(key), str) and bool(record[key]), "invalid_record", f"{key} is required.")
        if records_schema_version == "0.1.0":
            require(isinstance(record.get("text"), str) and bool(record["text"]), "invalid_record", "text is required.")
        else:
            require("text" not in record, "invalid_record", "Records schema 0.2.0 reconstructs page text from source byte offsets.")
        require(record["edition_id"] == manifest["edition_id"], "edition_mismatch", "A record belongs to a different edition.", record_id=record["record_id"])
        require(
            record["kind"] in ({"clause", "note", "page"} | _STRUCTURAL_KINDS),
            "invalid_record",
            "Unsupported record kind.",
            record_id=record["record_id"],
        )
        require(record["record_id"] not in record_ids, "invalid_record", "Record IDs must be unique.", record_id=record["record_id"])
        require(
            record["clause_reference"] not in clause_references,
            "invalid_record",
            "Record clause references must be unique within an edition.",
            clause_reference=record["clause_reference"],
        )
        record_ids.add(record["record_id"])
        clause_references.add(record["clause_reference"])

        source = _strict_object(record.get("source"), _SOURCE_KEYS, "invalid_record", "record source")
        require(_SOURCE_REQUIRED_KEYS <= set(source), "invalid_record", "Every required source locator field is required.")
        text_fields = set(source) & _SOURCE_TEXT_KEYS
        require(
            text_fields in (set(), _SOURCE_TEXT_KEYS),
            "invalid_record",
            "Source text_path and text_sha256 must be supplied together.",
        )
        offset_fields = set(source) & _SOURCE_OFFSET_KEYS
        require(
            offset_fields in (set(), _SOURCE_OFFSET_KEYS),
            "invalid_record",
            "Source text_start_byte and text_end_byte must be supplied together.",
        )
        if offset_fields:
            require(record["kind"] == "page", "invalid_record", "Source text offsets are currently supported only for page records.")
            require(text_fields == _SOURCE_TEXT_KEYS, "invalid_record", "Source text offsets require an inventoried text sidecar.")
        rel = _safe_relative_path(source["path"]).as_posix()
        require(rel.startswith("sources/"), "invalid_record", "Record sources must be under sources/.", record_id=record["record_id"])
        require(rel in inventory_by_path, "invalid_record", "The record source is not inventoried.", record_id=record["record_id"])
        require(source["sha256"] == inventory_by_path[rel].sha256, "invalid_record", "The record source digest does not match the inventory.", record_id=record["record_id"])
        require(type(source["page"]) is int and source["page"] >= 1, "invalid_record", "Source page must be a positive integer.")
        require(isinstance(source["locator"], str) and source["locator"], "invalid_record", "Source locator is required.")
        evidence_rel = rel
        if text_fields:
            require(PurePosixPath(rel).suffix.lower() == ".pdf", "invalid_record", "A source text sidecar is only valid for a PDF source.")
            evidence_rel = _safe_relative_path(source["text_path"]).as_posix()
            require(evidence_rel.startswith("sources/"), "invalid_record", "Source text sidecars must be under sources/.")
            require(evidence_rel in inventory_by_path, "invalid_record", "The source text sidecar is not inventoried.")
            require(
                source["text_sha256"] == inventory_by_path[evidence_rel].sha256,
                "invalid_record",
                "The source text sidecar digest does not match the inventory.",
                record_id=record["record_id"],
            )
        else:
            require(PurePosixPath(rel).suffix.lower() != ".pdf", "invalid_record", "PDF record sources require an inventoried text sidecar.")
        if evidence_rel not in evidence_text_cache:
            try:
                evidence_bytes_cache[evidence_rel] = (pack_root / Path(evidence_rel)).read_bytes()
                evidence_text_cache[evidence_rel] = evidence_bytes_cache[evidence_rel].decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise StandardsForgeError("invalid_record", "The record evidence text is not readable UTF-8.", {"record_id": record["record_id"]}) from exc
        source_text = evidence_text_cache[evidence_rel]
        if offset_fields:
            start_byte = source["text_start_byte"]
            end_byte = source["text_end_byte"]
            source_bytes = evidence_bytes_cache[evidence_rel]
            require(
                type(start_byte) is int
                and type(end_byte) is int
                and 0 <= start_byte < end_byte <= len(source_bytes),
                "invalid_record",
                "Source text byte offsets are outside the sidecar.",
                record_id=record["record_id"],
            )
            quote_bytes = source_bytes[start_byte:end_byte]
            try:
                quote_text = quote_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise StandardsForgeError("invalid_record", "Source text byte offsets split UTF-8 text.", {"record_id": record["record_id"]}) from exc
            if records_schema_version == "0.2.0":
                record["text"] = quote_text
            require(quote_text == record["text"], "source_quote_missing", "Source text offsets do not reproduce the exact record text.", record_id=record["record_id"])
            require(_sha256(quote_bytes) == source["quote_sha256"], "invalid_record", "Source text offsets do not match the quote digest.", record_id=record["record_id"])
        else:
            require(records_schema_version == "0.1.0", "invalid_record", "Records schema 0.2.0 requires exact source byte offsets.")
            require(record["text"] in source_text, "source_quote_missing", "Exact record text is absent from its source.", record_id=record["record_id"])
        require(source["quote_sha256"] == _sha256(record["text"].encode("utf-8")), "invalid_record", "Quote digest does not match exact record text.", record_id=record["record_id"])

        structure = record.get("structure")
        if structure is not None:
            structure = _strict_object(structure, _STRUCTURE_KEYS, "invalid_record", "record structure")
            require(_STRUCTURE_REQUIRED_KEYS <= set(structure), "invalid_record", "Every required structure field is required.")
            logical_id = structure["logical_id"]
            require(isinstance(logical_id, str) and logical_id, "invalid_record", "A structural logical ID is required.")
            require(logical_id not in logical_ids, "invalid_record", "Structural logical IDs must be unique within an edition.", logical_id=logical_id)
            logical_ids.add(logical_id)
            require(
                isinstance(structure["content_sha256"], str)
                and structure["content_sha256"] == _sha256(record["text"].encode("utf-8")),
                "invalid_record",
                "The structural content digest must match the exact record text.",
                logical_id=logical_id,
            )
            require(
                structure["parent_logical_id"] is None
                or isinstance(structure["parent_logical_id"], str) and structure["parent_logical_id"],
                "invalid_record",
                "A structural parent logical ID must be null or non-empty text.",
                logical_id=logical_id,
            )
            require(type(structure["ordinal"]) is int and structure["ordinal"] >= 0, "invalid_record", "A structural ordinal must be a non-negative integer.")
            spans = structure["source_spans"]
            require(
                isinstance(spans, list) and 1 <= len(spans) <= 64,
                "invalid_record",
                "Structural records require between one and 64 ordered source spans.",
            )
            span_fragments: list[str] = []
            prior_span_key: tuple[int, int, int] | None = None
            normalized_span_locations: list[tuple[str, str, int, str]] = []
            for raw_span in spans:
                span = _strict_object(raw_span, _STRUCTURE_SPAN_KEYS, "invalid_record", "structural source span")
                require(set(span) == _STRUCTURE_SPAN_KEYS, "invalid_record", "Every structural source span field is required.")
                span_source_rel = _safe_relative_path(span["path"]).as_posix()
                span_text_rel = _safe_relative_path(span["text_path"]).as_posix()
                require(span_source_rel in inventory_by_path and span_text_rel in inventory_by_path, "invalid_record", "Structural span files must be inventoried.")
                require(span["sha256"] == inventory_by_path[span_source_rel].sha256, "invalid_record", "Structural span source digest does not match the inventory.")
                require(span["text_sha256"] == inventory_by_path[span_text_rel].sha256, "invalid_record", "Structural span text digest does not match the inventory.")
                require(type(span["physical_page"]) is int and span["physical_page"] >= 1, "invalid_record", "Structural span page must be positive.")
                require(type(span["start_byte"]) is int and type(span["end_byte"]) is int and 0 <= span["start_byte"] < span["end_byte"], "invalid_record", "Structural span byte offsets are invalid.")
                span_key = (span["physical_page"], span["start_byte"], span["end_byte"])
                require(prior_span_key is None or span_key > prior_span_key, "invalid_record", "Structural source spans must be unique and ordered.")
                if prior_span_key is not None and span_key[0] == prior_span_key[0]:
                    require(span_key[1] >= prior_span_key[2], "invalid_record", "Structural source spans cannot overlap.")
                prior_span_key = span_key
                span_bytes = pack_root.joinpath(*PurePosixPath(span_text_rel).parts).read_bytes()
                require(span["end_byte"] <= len(span_bytes), "invalid_record", "Structural span exceeds its text sidecar.")
                quote_bytes = span_bytes[span["start_byte"]:span["end_byte"]]
                try:
                    quote_text = quote_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise StandardsForgeError("invalid_record", "Structural span offsets split UTF-8 text.", {"logical_id": logical_id}) from exc
                require(span["quote_sha256"] == _sha256(quote_bytes), "invalid_record", "Structural span quote digest is invalid.", logical_id=logical_id)
                span_fragments.append(quote_text)
                normalized_span_locations.append(
                    (span_source_rel, span_text_rel, span["physical_page"], span["quote_sha256"])
                )
            require(
                "\n".join(span_fragments) == record["text"],
                "source_quote_missing",
                "Ordered structural spans do not reproduce the exact record text.",
                logical_id=logical_id,
            )
            first_source_rel, first_text_rel, first_page, first_quote_sha256 = normalized_span_locations[0]
            require(
                all(span_source_rel == rel for span_source_rel, _, _, _ in normalized_span_locations)
                and first_source_rel == rel
                and first_page == source["page"],
                "invalid_record",
                "The primary source locator must agree with the ordered structural spans.",
                logical_id=logical_id,
            )
            if len(spans) == 1:
                require(
                    first_text_rel == evidence_rel
                    and first_quote_sha256 == source["quote_sha256"],
                    "invalid_record",
                    "The primary source locator must agree with the structural source span.",
                    logical_id=logical_id,
                )
            else:
                require(
                    source_text == record["text"] and evidence_rel not in {location[1] for location in normalized_span_locations},
                    "invalid_record",
                    "A multi-span structural record requires an exact assembled evidence sidecar.",
                    logical_id=logical_id,
                )
            semantics = structure.get("semantics")
            if semantics is not None:
                _validate_semantic_record(
                    semantics,
                    record_text=record["text"],
                    statement_role=record["derivation"]["statement_role"],
                    kind=record["kind"],
                    span_fragments=span_fragments,
                )
            review_event = structure.get("review")
            if review_event is not None:
                _validate_review_event(
                    review_event,
                    content_sha256=structure["content_sha256"],
                    has_semantics=semantics is not None,
                )
            require(
                semantics is None or review_event is not None,
                "invalid_record",
                "Reviewed semantics require a query-visible review event.",
            )
            relationships = structure["relationships"]
            require(isinstance(relationships, list), "invalid_record", "Structural relationships must be a list.")
            for relationship in relationships:
                relationship = _strict_object(
                    relationship,
                    _STRUCTURE_RELATIONSHIP_KEYS,
                    "invalid_record",
                    "structural relationship",
                )
                require(set(relationship) == _STRUCTURE_RELATIONSHIP_KEYS, "invalid_record", "Every structural relationship field is required.")
                require(relationship["relationship"] in _STRUCTURAL_RELATIONSHIPS, "invalid_record", "Unsupported structural relationship type.")
                require(relationship["target_status"] in {"resolved", "out_of_scope", "unresolved", "ambiguous"}, "invalid_record", "Unsupported structural relationship target status.")
                require(type(relationship["required"]) is bool, "invalid_record", "Structural relationship required must be boolean.")
                require(all(isinstance(relationship[key], str) and relationship[key] for key in ("method", "review_status")), "invalid_record", "Structural relationship provenance is required.")
                require(isinstance(relationship["evidence_spans"], list) and relationship["evidence_spans"], "invalid_record", "Structural relationship evidence spans are required.")
                for relationship_span in relationship["evidence_spans"]:
                    relationship_span = _strict_object(relationship_span, _STRUCTURE_SPAN_KEYS, "invalid_record", "relationship evidence span")
                    require(set(relationship_span) == _STRUCTURE_SPAN_KEYS, "invalid_record", "Every relationship evidence span field is required.")
                    relationship_source_rel = _safe_relative_path(relationship_span["path"]).as_posix()
                    relationship_text_rel = _safe_relative_path(relationship_span["text_path"]).as_posix()
                    require(relationship_source_rel in inventory_by_path and relationship_text_rel in inventory_by_path, "invalid_record", "Relationship span files must be inventoried.")
                    require(relationship_span["sha256"] == inventory_by_path[relationship_source_rel].sha256 and relationship_span["text_sha256"] == inventory_by_path[relationship_text_rel].sha256, "invalid_record", "Relationship span file digests do not match the inventory.")
                    relationship_bytes = pack_root.joinpath(*PurePosixPath(relationship_text_rel).parts).read_bytes()
                    require(type(relationship_span["start_byte"]) is int and type(relationship_span["end_byte"]) is int and 0 <= relationship_span["start_byte"] < relationship_span["end_byte"] <= len(relationship_bytes), "invalid_record", "Relationship span byte offsets are invalid.")
                    relationship_quote = relationship_bytes[relationship_span["start_byte"]:relationship_span["end_byte"]]
                    try:
                        relationship_quote.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise StandardsForgeError("invalid_record", "Relationship span offsets split UTF-8 text.", {"logical_id": logical_id}) from exc
                    require(relationship_span["quote_sha256"] == _sha256(relationship_quote), "invalid_record", "Relationship span quote digest is invalid.")
                if relationship["target_status"] == "resolved":
                    require(isinstance(relationship["target_logical_id"], str) and relationship["target_logical_id"], "invalid_record", "Resolved structural relationships require a target logical ID.")
                    require(relationship["target_locator"] is None, "invalid_record", "Resolved structural relationships cannot use an external target locator.")
                    require(relationship["candidate_logical_ids"] == [], "invalid_record", "Resolved structural relationships cannot have candidate targets.")
                elif relationship["target_status"] in {"out_of_scope", "unresolved"}:
                    require(relationship["target_logical_id"] is None, "invalid_record", "Unresolved structural relationships cannot assert a target logical ID.")
                    require(isinstance(relationship["target_locator"], str) and relationship["target_locator"], "invalid_record", "Unresolved structural relationships require a target locator.")
                    require(relationship["candidate_logical_ids"] == [], "invalid_record", "Unresolved structural relationships cannot have candidate targets.")
                    require(not relationship["required"], "invalid_record", "Unresolved structural relationships cannot be required evidence dependencies.")
                else:
                    require(relationship["target_logical_id"] is None and relationship["target_locator"] is None, "invalid_record", "Ambiguous structural relationships cannot assert one target.")
                    require(isinstance(relationship["candidate_logical_ids"], list) and len(relationship["candidate_logical_ids"]) >= 2 and all(isinstance(value, str) and value for value in relationship["candidate_logical_ids"]), "invalid_record", "Ambiguous structural relationships require candidate logical IDs.")
                    require(not relationship["required"], "invalid_record", "Ambiguous structural relationships cannot be required evidence dependencies.")

        derivation = _strict_object(record.get("derivation"), _DERIVATION_KEYS, "invalid_record", "record derivation")
        require(set(derivation) == _DERIVATION_KEYS, "invalid_record", "Every derivation field is required.")
        require(
            derivation["statement_role"] in {"obligation", "governing_note", "informative", "unclassified"},
            "invalid_record",
            "Unsupported statement role.",
            record_id=record["record_id"],
        )
        for key in ("method", "review_status"):
            require(isinstance(derivation[key], str) and derivation[key], "invalid_record", f"Derivation {key} is required.")

        deps = record.get("dependencies")
        require(isinstance(deps, list), "invalid_record", "dependencies must be a list.")
        for dep in deps:
            dep = _strict_object(dep, _DEPENDENCY_KEYS, "invalid_record", "dependency")
            require(set(dep) == _DEPENDENCY_KEYS, "invalid_record", "Every dependency field is required.")
            require(isinstance(dep["relationship"], str) and dep["relationship"], "invalid_record", "Dependency relationship is required.")
            require(isinstance(dep["target_record_id"], str) and dep["target_record_id"], "invalid_record", "Dependency target is required.")
            require(type(dep["required"]) is bool, "invalid_record", "Dependency required must be boolean.")
        records.append(record)

    for record in records:
        for dep in record["dependencies"]:
            require(dep["target_record_id"] in record_ids, "unresolved_dependency", "A record dependency is unresolved.", record_id=record["record_id"], target=dep["target_record_id"])

    structural_records = {record["structure"]["logical_id"]: record for record in records if record.get("structure")}
    sequence_sources: set[str] = set()
    for logical_id, record in structural_records.items():
        structure = record["structure"]
        parent = structure["parent_logical_id"]
        require(parent is None or parent in structural_records, "invalid_record", "A structural parent is unresolved.", logical_id=logical_id, parent_logical_id=parent)
        require(parent != logical_id, "invalid_record", "A structural record cannot parent itself.", logical_id=logical_id)
        for relationship in structure["relationships"]:
            if relationship["target_status"] == "resolved":
                require(relationship["target_logical_id"] in structural_records, "invalid_record", "A resolved structural relationship target is unavailable.", logical_id=logical_id, target_logical_id=relationship["target_logical_id"])
            elif relationship["target_status"] == "ambiguous":
                require(all(candidate in structural_records for candidate in relationship["candidate_logical_ids"]), "invalid_record", "An ambiguous structural relationship candidate is unavailable.", logical_id=logical_id)
            if relationship["relationship"] == "sequence_after":
                require(relationship["target_status"] == "resolved", "invalid_record", "Procedure ordering requires one resolved predecessor.", logical_id=logical_id)
                require(relationship["required"], "invalid_record", "A procedure predecessor must be required retrieval context.", logical_id=logical_id)
                target_id = relationship["target_logical_id"]
                target_structure = structural_records[target_id]["structure"]
                require(logical_id not in sequence_sources, "invalid_record", "A procedure step cannot declare multiple immediate predecessors.", logical_id=logical_id)
                sequence_sources.add(logical_id)
                require(record["kind"] == structural_records[target_id]["kind"] == "list_item", "invalid_record", "Procedure ordering is limited to reviewed list-item steps.", logical_id=logical_id, target_logical_id=target_id)
                require(structure["parent_logical_id"] is not None and structure["parent_logical_id"] == target_structure["parent_logical_id"], "invalid_record", "Procedure steps must share one explicit parent.", logical_id=logical_id, target_logical_id=target_id)
                require(target_structure["ordinal"] < structure["ordinal"], "invalid_record", "A procedure predecessor must have an earlier sibling ordinal.", logical_id=logical_id, target_logical_id=target_id)
        expected_required_edges = sorted(
            (
                relationship["relationship"],
                structural_records[relationship["target_logical_id"]]["record_id"],
                True,
            )
            for relationship in structure["relationships"]
            if relationship["target_status"] == "resolved" and relationship["required"]
        )
        actual_required_edges = sorted(
            (dependency["relationship"], dependency["target_record_id"], dependency["required"])
            for dependency in record["dependencies"]
        )
        require(
            actual_required_edges == expected_required_edges,
            "invalid_record",
            "Structural required relationships must exactly match record retrieval dependencies.",
            record_id=record["record_id"],
        )
        ancestors: set[str] = set()
        cursor = parent
        while cursor is not None:
            require(cursor not in ancestors, "invalid_record", "The structural parent graph contains a cycle.", logical_id=logical_id)
            ancestors.add(cursor)
            cursor = structural_records[cursor]["structure"]["parent_logical_id"]

    return ValidatedPack(pack_root, package_digest, manifest, rights, tuple(records), inventory)


def _validate_zip_member(info: zipfile.ZipInfo) -> tuple[PurePosixPath, bool]:
    is_directory = info.is_dir()
    raw_name = info.filename.rstrip("/") if is_directory else info.filename
    require(bool(raw_name), "invalid_pack_path", "Empty archive paths are forbidden.")
    if is_directory:
        path = PurePosixPath(raw_name.replace("\\", "/"))
        require(
            not path.is_absolute() and ".." not in path.parts,
            "invalid_pack_path",
            "Unsafe archive directory path.",
            path=info.filename,
        )
    else:
        path = _safe_relative_path(raw_name)
    mode = info.external_attr >> 16
    require(not stat.S_ISLNK(mode), "invalid_pack_path", "Symbolic links are forbidden in a pack.", path=info.filename)
    return path, is_directory


def write_pack_archive(
    source: str | Path,
    destination: str | Path,
    *,
    compresslevel: int = 6,
) -> dict[str, Any]:
    """Write a deterministic, lossless ZIP transport for a validated pack."""

    source_root = Path(source).resolve()
    destination_path = Path(destination).resolve()
    require(source_root.is_dir(), "pack_not_found", "Archive source must be a pack directory.")
    require(destination_path.suffix.lower() == ".zip", "invalid_pack_archive", "Pack archive output must use .zip.")
    require(not destination_path.exists(), "pack_archive_exists", "Pack archive output already exists.", path=str(destination_path))
    require(type(compresslevel) is int and 1 <= compresslevel <= 9, "invalid_compression_level", "ZIP compression level must be 1 through 9.")
    pack = validate_pack_directory(source_root)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination_path.stem}.", suffix=".zip", dir=destination_path.parent)
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        members = ["inventory.json", *(entry.path for entry in pack.inventory)]
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=compresslevel,
            allowZip64=True,
        ) as archive:
            for relative in sorted(members):
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info._compresslevel = compresslevel
                info.create_system = 3
                info.external_attr = (0o100644 & 0xFFFF) << 16
                source_path = source_root.joinpath(*PurePosixPath(relative).parts)
                with source_path.open("rb") as reader, archive.open(info, "w", force_zip64=True) as writer:
                    while chunk := reader.read(1024 * 1024):
                        writer.write(chunk)
        with open_validated_pack(temporary_path) as archived:
            require(archived.package_digest == pack.package_digest, "invalid_pack_archive", "Archived pack digest changed.")
        os.replace(temporary_path, destination_path)
        return {
            "operation": "archive_pack",
            "status": "archived",
            "package_digest": pack.package_digest,
            "archive_path": str(destination_path),
            "archive_bytes": destination_path.stat().st_size,
            "compression": "zip_deflate",
            "compression_level": compresslevel,
        }
    finally:
        temporary_path.unlink(missing_ok=True)


@contextmanager
def open_validated_pack(source: str | Path) -> Iterator[ValidatedPack]:
    source_path = Path(source).resolve()
    if source_path.is_dir():
        yield validate_pack_directory(source_path)
        return
    require(source_path.is_file() and source_path.suffix.lower() == ".zip", "pack_not_found", "Pack source must be a directory or .zip file.")

    with tempfile.TemporaryDirectory(prefix="standardsforge-pack-") as temp:
        target = Path(temp)
        try:
            with zipfile.ZipFile(source_path) as archive:
                infos = archive.infolist()
                require(1 <= len(infos) <= MAX_FILES + 1, "pack_limit_exceeded", "Archive file count is outside the allowed range.")
                require(sum(info.file_size for info in infos) <= MAX_TOTAL_BYTES + MAX_JSON_BYTES, "pack_limit_exceeded", "Archive content exceeds the size limit.")
                seen: set[str] = set()
                for info in infos:
                    rel, is_directory = _validate_zip_member(info)
                    rel_text = rel.as_posix()
                    require(rel_text not in seen, "invalid_pack_path", "Duplicate archive member.", path=rel_text)
                    seen.add(rel_text)
                    output = target.joinpath(*rel.parts)
                    if is_directory:
                        output.mkdir(parents=True, exist_ok=True)
                        continue
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as reader, output.open("xb") as writer:
                        while chunk := reader.read(1024 * 1024):
                            writer.write(chunk)
        except (zipfile.BadZipFile, OSError) as exc:
            raise StandardsForgeError("invalid_pack_archive", "The pack archive is invalid.") from exc
        yield validate_pack_directory(target)
