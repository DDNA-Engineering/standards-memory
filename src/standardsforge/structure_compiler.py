from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .compiler import (
    COMPILER_VERSION,
    MAX_PDF_BYTES,
    PYPDF_VERSION,
    _inventory_entry,
    _source_document,
    _write_json,
)
from .errors import StandardsForgeError, require
from .pack import open_validated_pack, validate_pack_directory
from .pdf_isolation import isolated_pdf_pages
from .pdf_protocol import DEFAULT_LIMITS, LIMIT_POLICY_VERSION, PROTOCOL_VERSION
from .source_catalog import load_source_catalog, verify_source_set


STRUCTURE_COMPILER_VERSION = "0.4.0"
MAX_NODE_SOURCE_SPANS = 64
NODE_KINDS = {
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
}
STATEMENT_ROLES = {"obligation", "governing_note", "informative", "unclassified"}
RELATIONSHIP_TYPES = {
    "defines",
    "uses_definition",
    "governed_by",
    "qualifies",
    "exception_to",
    "references",
    "caption_of",
    "footnote_for",
    "table_footnote_for",
    "header_for",
    "illustrates",
    "continues_on",
    "sequence_after",
}
TARGET_STATUSES = {"resolved", "out_of_scope", "unresolved", "ambiguous"}

_ANNOTATION_KEYS = {
    "schema_version",
    "document_id",
    "edition_id",
    "source_pdf_sha256",
    "compiler",
    "extraction_mode",
    "text_encoding",
    "offset_convention",
    "review",
    "nodes",
    "relationships",
    "unsupported_regions",
}
_PACK_ANNOTATION_KEYS = {
    "source_page_pack_digest", "outline_package_digest", "candidate_record_id",
    "candidate_content_sha256", "proposal_sha256",
}
_COMPILER_KEYS = {"name", "version"}
_REVIEW_REQUIRED_KEYS = {"reviewer_id", "reviewer_type", "reviewed_at"}
_REVIEW_OPTIONAL_KEYS = {"method", "tool", "unresolved_issues", "attestation"}
_DERIVATION_KEYS = {"method", "review_status"}
_NODE_KEYS = {
    "logical_id",
    "kind",
    "parent_logical_id",
    "ordinal",
    "clause_reference",
    "heading",
    "statement_role",
    "exact_text",
    "source_spans",
    "content_sha256",
    "derivation",
}
_NODE_OPTIONAL_KEYS = {"parent_logical_id", "semantics"}
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
_SEMANTIC_CONTENT_ROLES = {
    "requirement_candidate",
    "governing_condition",
    "exception",
    "applicability_statement",
    "definition",
    "table_header",
    "table_row",
    "table_footnote",
    "note",
    "prose",
}
_RELATIONSHIP_KEYS = {
    "source_logical_id",
    "relationship_type",
    "target_status",
    "required",
    "derivation",
    "evidence_spans",
}
_RELATIONSHIP_OPTIONAL_KEYS = {"target_logical_id", "target_reference", "candidate_logical_ids"}
_SOURCE_SPAN_KEYS = {"physical_page", "page_text_sha256", "start_byte", "end_byte"}
_UNSUPPORTED_REQUIRED_KEYS = {"region_id", "reason_code", "source_spans", "derivation"}
_UNSUPPORTED_OPTIONAL_KEYS = {"affected_kinds", "description"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_object(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), "invalid_structure_annotations", f"{label} must be an object.")
    require(set(value) == expected, "invalid_structure_annotations", f"{label} fields are invalid.", fields=sorted(set(value) ^ expected))
    return value


def _bounded_object(value: Any, required: set[str], optional: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), "invalid_structure_annotations", f"{label} must be an object.")
    require(required <= set(value) <= required | optional, "invalid_structure_annotations", f"{label} fields are invalid.", fields=sorted(set(value) ^ required))
    return value


def _validate_span(span: Any, label: str) -> dict[str, Any]:
    value = _strict_object(span, _SOURCE_SPAN_KEYS, label)
    require(type(value["physical_page"]) is int and value["physical_page"] >= 1, "invalid_structure_annotations", f"{label} physical page must be positive.")
    require(isinstance(value["page_text_sha256"], str) and len(value["page_text_sha256"]) == 64, "invalid_structure_annotations", f"{label} page text digest is invalid.")
    require(type(value["start_byte"]) is int and type(value["end_byte"]) is int and 0 <= value["start_byte"] < value["end_byte"], "invalid_structure_annotations", f"{label} byte offsets are invalid.")
    return value


def _validate_derivation(value: Any, label: str, reviewer_type: str) -> dict[str, Any]:
    derivation = _strict_object(value, _DERIVATION_KEYS, label)
    require(isinstance(derivation["method"], str) and derivation["method"], "invalid_structure_annotations", f"{label} method is required.")
    require(derivation["review_status"] in {"agent_reviewed", "human_reviewed", "human_reviewed_with_uncertainty"}, "invalid_structure_annotations", f"{label} review status is invalid.")
    if reviewer_type == "agent":
        require(derivation["review_status"] == "agent_reviewed", "invalid_structure_annotations", f"{label} cannot claim human review from an agent review record.")
    else:
        require(derivation["review_status"] in {"human_reviewed", "human_reviewed_with_uncertainty"}, "invalid_structure_annotations", f"{label} must preserve the declared human review status.")
    return derivation


def _validate_span_indices(value: Any, span_count: int, label: str) -> list[int]:
    require(
        isinstance(value, list)
        and value
        and len(value) == len(set(value))
        and all(type(index) is int and 0 <= index < span_count for index in value)
        and value == sorted(value),
        "invalid_structure_annotations",
        f"{label} span indices are invalid.",
    )
    return value


def _validate_semantics(value: Any, span_count: int, statement_role: str) -> dict[str, Any]:
    semantics = _strict_object(value, _SEMANTIC_KEYS, "node semantics")
    require(semantics["schema_version"] == "0.1.0", "invalid_structure_annotations", "Unsupported node semantic schema.")
    require(semantics["content_role"] in _SEMANTIC_CONTENT_ROLES, "invalid_structure_annotations", "Unsupported semantic content role.")
    require(semantics["normativity"] in {"normative", "informative", "mixed", "unclassified"}, "invalid_structure_annotations", "Unsupported semantic normativity.")
    require(semantics["project_applicability"] == "not_decided", "invalid_structure_annotations", "Semantic extraction cannot decide project applicability.")
    require(isinstance(semantics["unresolved_issues"], list) and all(isinstance(item, str) and item for item in semantics["unresolved_issues"]), "invalid_structure_annotations", "Semantic unresolved issues must be non-empty strings.")
    statement = semantics["statement"]
    if semantics["content_role"] == "requirement_candidate":
        require(statement_role == "obligation", "invalid_structure_annotations", "Requirement candidates must be explicitly classified as obligations.")
        require(isinstance(statement, dict), "invalid_structure_annotations", "Requirement candidates require a reviewed statement decomposition.")
    if statement is not None:
        statement = _strict_object(statement, {"subject", "action", "modality", "polarity", "exact_text", "span_indices"}, "semantic statement")
        require(all(isinstance(statement[key], str) and statement[key] for key in ("subject", "action", "exact_text")), "invalid_structure_annotations", "Semantic statement text fields are required.")
        require(statement["modality"] in {"shall", "must", "should", "may", "will", "other"}, "invalid_structure_annotations", "Semantic statement modality is invalid.")
        require(statement["polarity"] in {"affirmative", "negative"}, "invalid_structure_annotations", "Semantic statement polarity is invalid.")
        _validate_span_indices(statement["span_indices"], span_count, "Semantic statement")
    for collection_name, allowed_keys in (
        ("qualifiers", {"kind", "exact_text", "span_indices"}),
        ("quantities", {"raw", "value", "unit", "tolerance", "span_indices"}),
    ):
        collection = semantics[collection_name]
        require(isinstance(collection, list), "invalid_structure_annotations", f"Semantic {collection_name} must be a list.")
        for item in collection:
            item = _strict_object(item, allowed_keys, f"semantic {collection_name} item")
            _validate_span_indices(item["span_indices"], span_count, f"Semantic {collection_name} item")
            if collection_name == "qualifiers":
                require(item["kind"] in {"condition", "exception", "source_applicability", "test_condition", "acceptance_criterion", "tailoring_instruction"}, "invalid_structure_annotations", "Semantic qualifier kind is invalid.")
                require(isinstance(item["exact_text"], str) and item["exact_text"], "invalid_structure_annotations", "Semantic qualifier exact text is required.")
            else:
                require(isinstance(item["raw"], str) and item["raw"], "invalid_structure_annotations", "Semantic quantity raw text is required.")
                require(all(item[key] is None or isinstance(item[key], str) for key in ("value", "unit", "tolerance")), "invalid_structure_annotations", "Semantic quantity fields must be text or null.")
    return semantics


def load_structure_annotations(path: str | Path) -> dict[str, Any]:
    annotation_path = Path(path).resolve()
    require(annotation_path.is_file(), "structure_annotations_not_found", "The structure annotation file does not exist.")
    try:
        raw = json.loads(annotation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_structure_annotations", "The structure annotation file is invalid JSON.") from exc
    require(isinstance(raw, dict), "invalid_structure_annotations", "Structure annotations must be an object.")
    is_pack_annotation = raw.get("schema_version") == "0.4.0"
    annotations = _strict_object(raw, _ANNOTATION_KEYS | (_PACK_ANNOTATION_KEYS if is_pack_annotation else set()), "structure annotations")
    require(
        annotations["schema_version"] in {"0.1.0", "0.2.0", "0.3.0", "0.4.0"},
        "unsupported_schema_version",
        "Unsupported structure annotation schema.",
    )
    for key in ("document_id", "edition_id", "source_pdf_sha256"):
        require(isinstance(annotations[key], str) and annotations[key], "invalid_structure_annotations", f"{key} is required.")
    require(len(annotations["source_pdf_sha256"]) == 64, "invalid_structure_annotations", "The source PDF digest is invalid.")
    compiler = _strict_object(annotations["compiler"], _COMPILER_KEYS, "compiler")
    require(compiler == {"name": "pypdf", "version": PYPDF_VERSION}, "invalid_structure_annotations", "Structure annotations must bind the pinned PDF compiler.")
    require(annotations["extraction_mode"] == ("layout_rotated_included" if is_pack_annotation else "simple"), "invalid_structure_annotations", "The structural extraction mode does not match its annotation version.")
    require(annotations["text_encoding"] == "UTF-8", "invalid_structure_annotations", "Structural annotations require UTF-8 page text.")
    require(annotations["offset_convention"] == "half_open_utf8_byte_offsets_per_physical_page", "invalid_structure_annotations", "Unsupported structural offset convention.")
    if is_pack_annotation:
        for key in _PACK_ANNOTATION_KEYS - {"candidate_record_id"}:
            require(isinstance(annotations[key], str) and len(annotations[key]) == 64 and all(char in "0123456789abcdef" for char in annotations[key]), "invalid_structure_annotations", f"{key} must be a SHA-256 digest.")
        require(isinstance(annotations["candidate_record_id"], str) and annotations["candidate_record_id"], "invalid_structure_annotations", "A pack-bound annotation requires its source candidate record ID.")
    review = _bounded_object(
        annotations["review"], _REVIEW_REQUIRED_KEYS, _REVIEW_OPTIONAL_KEYS, "review"
    )
    require(all(isinstance(review[key], str) and review[key] for key in _REVIEW_REQUIRED_KEYS), "invalid_structure_annotations", "Review provenance is required.")
    require(review["reviewer_type"] in {"agent", "human"}, "invalid_structure_annotations", "Reviewer type is invalid.")
    if annotations["schema_version"] in {"0.2.0", "0.3.0", "0.4.0"}:
        require(set(review) == _REVIEW_REQUIRED_KEYS | _REVIEW_OPTIONAL_KEYS, "invalid_structure_annotations", "Structure annotations 0.2.0 require complete review provenance.")
        require(isinstance(review["method"], str) and review["method"], "invalid_structure_annotations", "Review method is required.")
        require(review["attestation"] == "extraction_review_not_project_applicability_or_approval", "invalid_structure_annotations", "Review attestation cannot assert project applicability or approval.")
        require(isinstance(review["unresolved_issues"], list) and all(isinstance(item, str) and item for item in review["unresolved_issues"]), "invalid_structure_annotations", "Review unresolved issues must be non-empty strings.")
        tool = review["tool"]
        if review["reviewer_type"] == "agent":
            require(isinstance(tool, dict), "invalid_structure_annotations", "Agent review requires tool provenance.")
        if tool is not None:
            tool = _strict_object(tool, {"name", "version", "configuration_sha256"}, "review tool")
            require(all(isinstance(tool[key], str) and tool[key] for key in ("name", "version")), "invalid_structure_annotations", "Review tool name and version are required.")
            require(tool["configuration_sha256"] is None or isinstance(tool["configuration_sha256"], str) and len(tool["configuration_sha256"]) == 64, "invalid_structure_annotations", "Review tool configuration digest is invalid.")
    nodes = annotations["nodes"]
    require(isinstance(nodes, list) and nodes, "invalid_structure_annotations", "At least one structural node is required.")
    if is_pack_annotation:
        require(len(nodes) == 1 and annotations["relationships"] == [] and annotations["unsupported_regions"] == [], "invalid_structure_annotations", "Pack-bound single-candidate review cannot assert additional nodes, relationships, or reviewed unsupported regions.")
    require(len(nodes) <= 4096, "invalid_structure_annotations", "The structural annotation node limit was exceeded.")
    logical_ids: set[str] = set()
    clause_references: set[str] = set()
    for value in nodes:
        node = _bounded_object(value, _NODE_KEYS - {"parent_logical_id"}, _NODE_OPTIONAL_KEYS, "structural node")
        for key in ("logical_id", "clause_reference", "heading", "exact_text", "content_sha256"):
            require(isinstance(node[key], str) and node[key], "invalid_structure_annotations", f"Structural node {key} is required.")
        require(node["logical_id"] not in logical_ids, "invalid_structure_annotations", "Structural logical IDs must be unique.", logical_id=node["logical_id"])
        require(node["clause_reference"] not in clause_references, "invalid_structure_annotations", "Structural clause references must be unique.", clause_reference=node["clause_reference"])
        logical_ids.add(node["logical_id"])
        clause_references.add(node["clause_reference"])
        require(node["kind"] in NODE_KINDS, "invalid_structure_annotations", "Unsupported structural node kind.", logical_id=node["logical_id"])
        parent = node.get("parent_logical_id")
        require(parent is None or isinstance(parent, str) and parent, "invalid_structure_annotations", "A parent logical ID must be absent or non-empty text.")
        require(type(node["ordinal"]) is int and node["ordinal"] >= 1, "invalid_structure_annotations", "A structural ordinal must be one-based.")
        source_spans = node["source_spans"]
        require(
            isinstance(source_spans, list)
            and source_spans
            and len(source_spans) <= MAX_NODE_SOURCE_SPANS,
            "invalid_structure_annotations",
            "Structural nodes require between one and 64 ordered source spans.",
        )
        if annotations["schema_version"] == "0.1.0":
            require(
                len(source_spans) == 1,
                "invalid_structure_annotations",
                "Structure annotations 0.1.0 require exactly one source span per node.",
            )
        prior_span_key: tuple[int, int, int] | None = None
        for span in source_spans:
            _validate_span(span, "node source span")
            span_key = (span["physical_page"], span["start_byte"], span["end_byte"])
            require(
                prior_span_key is None or span_key > prior_span_key,
                "invalid_structure_annotations",
                "Structural node source spans must be unique and ordered by page and byte offset.",
                logical_id=node["logical_id"],
            )
            if prior_span_key is not None and span_key[0] == prior_span_key[0]:
                require(
                    span_key[1] >= prior_span_key[2],
                    "invalid_structure_annotations",
                    "Structural node source spans on one page cannot overlap.",
                    logical_id=node["logical_id"],
                )
            prior_span_key = span_key
        require(node["content_sha256"] == _sha256(node["exact_text"].encode("utf-8")), "invalid_structure_annotations", "Structural content digest does not match exact text.", logical_id=node["logical_id"])
        require(node["statement_role"] in STATEMENT_ROLES, "invalid_structure_annotations", "Unsupported structural statement role.")
        _validate_derivation(node["derivation"], "node derivation", review["reviewer_type"])
        semantics = node.get("semantics")
        if semantics is not None:
            require(annotations["schema_version"] in {"0.2.0", "0.3.0", "0.4.0"}, "invalid_structure_annotations", "Semantic annotations require structure annotation schema 0.2.0 or newer.")
            _validate_semantics(semantics, len(source_spans), node["statement_role"])
    by_logical_id = {node["logical_id"]: node for node in nodes}
    for node in nodes:
        parent = node.get("parent_logical_id")
        require(parent is None or parent in by_logical_id, "invalid_structure_annotations", "A structural parent is unresolved.", logical_id=node["logical_id"])
        visited: set[str] = set()
        cursor = parent
        while cursor is not None:
            require(cursor not in visited, "invalid_structure_annotations", "The structural parent graph contains a cycle.", logical_id=node["logical_id"])
            visited.add(cursor)
            cursor = by_logical_id[cursor].get("parent_logical_id")
    relationships = annotations["relationships"]
    require(isinstance(relationships, list), "invalid_structure_annotations", "relationships must be a list.")
    sequence_sources: set[str] = set()
    for raw_relationship in relationships:
        relationship = _bounded_object(raw_relationship, _RELATIONSHIP_KEYS, _RELATIONSHIP_OPTIONAL_KEYS, "structural relationship")
        require(relationship["source_logical_id"] in by_logical_id, "invalid_structure_annotations", "A structural relationship source is unavailable.")
        require(relationship["relationship_type"] in RELATIONSHIP_TYPES, "invalid_structure_annotations", "Unsupported structural relationship type.")
        require(relationship["target_status"] in TARGET_STATUSES, "invalid_structure_annotations", "Unsupported target status.")
        require(type(relationship["required"]) is bool, "invalid_structure_annotations", "Relationship required must be boolean.")
        _validate_derivation(relationship["derivation"], "relationship derivation", review["reviewer_type"])
        require(isinstance(relationship["evidence_spans"], list) and relationship["evidence_spans"], "invalid_structure_annotations", "Relationship evidence spans are required.")
        for span in relationship["evidence_spans"]:
            _validate_span(span, "relationship evidence span")
        status = relationship["target_status"]
        if status == "resolved":
            require(relationship.get("target_logical_id") in by_logical_id, "invalid_structure_annotations", "A resolved relationship target is unavailable.")
            require("target_reference" not in relationship and "candidate_logical_ids" not in relationship, "invalid_structure_annotations", "Resolved relationships cannot assert alternate targets.")
        elif status in {"out_of_scope", "unresolved"}:
            require(isinstance(relationship.get("target_reference"), str) and relationship["target_reference"], "invalid_structure_annotations", "Unresolved relationships require a target reference.")
            require("target_logical_id" not in relationship and "candidate_logical_ids" not in relationship, "invalid_structure_annotations", "Unresolved relationships cannot assert logical candidates.")
            require(not relationship["required"], "invalid_structure_annotations", "Unresolved relationships cannot be required dependencies.")
        else:
            candidates = relationship.get("candidate_logical_ids")
            require(isinstance(candidates, list) and len(candidates) >= 2 and len(set(candidates)) == len(candidates) and all(candidate in by_logical_id for candidate in candidates), "invalid_structure_annotations", "Ambiguous relationships require in-scope candidate logical IDs.")
            require("target_logical_id" not in relationship and "target_reference" not in relationship, "invalid_structure_annotations", "Ambiguous relationships cannot assert one target.")
            require(not relationship["required"], "invalid_structure_annotations", "Ambiguous relationships cannot be required dependencies.")
        if relationship["relationship_type"] == "sequence_after":
            require(annotations["schema_version"] in {"0.3.0", "0.4.0"}, "invalid_structure_annotations", "Reviewed procedure ordering requires structure annotation schema 0.3.0 or newer.")
            require(status == "resolved", "invalid_structure_annotations", "Procedure ordering requires one resolved predecessor.")
            require(relationship["required"], "invalid_structure_annotations", "A procedure predecessor must be required retrieval context.")
            source_id = relationship["source_logical_id"]
            target_id = relationship["target_logical_id"]
            source_node = by_logical_id[source_id]
            target_node = by_logical_id[target_id]
            require(source_id not in sequence_sources, "invalid_structure_annotations", "A procedure step cannot declare multiple immediate predecessors.")
            sequence_sources.add(source_id)
            require(source_node["kind"] == target_node["kind"] == "list_item", "invalid_structure_annotations", "Procedure ordering is limited to reviewed list-item steps.")
            require(source_node.get("parent_logical_id") is not None and source_node.get("parent_logical_id") == target_node.get("parent_logical_id"), "invalid_structure_annotations", "Procedure steps must share one explicit parent.")
            require(target_node["ordinal"] < source_node["ordinal"], "invalid_structure_annotations", "A procedure predecessor must have an earlier sibling ordinal.")
    unsupported = annotations["unsupported_regions"]
    require(isinstance(unsupported, list), "invalid_structure_annotations", "unsupported_regions must be a list.")
    for raw_region in unsupported:
        region = _bounded_object(raw_region, _UNSUPPORTED_REQUIRED_KEYS, _UNSUPPORTED_OPTIONAL_KEYS, "unsupported region")
        require(isinstance(region["region_id"], str) and region["region_id"], "invalid_structure_annotations", "Unsupported-region ID is required.")
        require(region["reason_code"] in {"no_text_layer", "ambiguous_structure", "ambiguous_reading_order", "unparsed_table", "unparsed_figure", "unclassified_content", "outside_selected_scope", "other"}, "invalid_structure_annotations", "Unsupported-region reason code is invalid.")
        require(isinstance(region["source_spans"], list) and region["source_spans"], "invalid_structure_annotations", "Unsupported-region source spans are required.")
        for span in region["source_spans"]:
            _validate_span(span, "unsupported-region source span")
        _validate_derivation(region["derivation"], "unsupported-region derivation", review["reviewer_type"])
    return annotations


def _record_id(edition_id: str, logical_id: str) -> str:
    return "struct-" + _sha256(f"{edition_id}\0{logical_id}".encode("utf-8"))[:24]


def compile_structured_pdf_section(
    catalog_path: str | Path,
    document_id: str,
    source_root: str | Path,
    annotations_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Compile reviewed structural annotations into a source-spanned immutable pack."""

    verify_source_set(catalog_path, source_root)
    catalog = load_source_catalog(catalog_path)
    document = _source_document(catalog, document_id)
    annotations = load_structure_annotations(annotations_path)
    require(annotations["schema_version"] != "0.4.0", "invalid_structure_annotations", "Pack-bound annotations require compile-structure-from-pack.")
    review = annotations["review"]
    require(annotations["document_id"] == document["document_id"], "structure_identity_mismatch", "Structure annotations belong to a different document.")
    require(annotations["edition_id"] == document["edition_id"], "structure_identity_mismatch", "Structure annotations belong to a different edition.")
    require(annotations["source_pdf_sha256"] == document["sha256"], "structure_identity_mismatch", "Structure annotations bind a different source PDF.")

    source_path = Path(source_root).resolve() / document["local_filename"]
    return _compile_structured_section(document, source_path, annotations, output_directory)


def compile_structured_page_pack_section(
    source_page_pack: str | Path,
    outline_pack: str | Path,
    annotations_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Compile explicitly reviewed annotations against one verified page-text source pack."""

    annotations = load_structure_annotations(annotations_path)
    require(annotations["schema_version"] == "0.4.0", "invalid_structure_annotations", "Pack compilation requires structure annotations 0.4.0.")
    from .outline_review import export_outline_review_draft

    with tempfile.TemporaryDirectory(prefix="standardsforge-proposal-verify-") as temporary:
        replay = Path(temporary) / "draft.json"
        exported = export_outline_review_draft(outline_pack, source_page_pack, annotations["candidate_record_id"], replay)
        draft = json.loads(replay.read_text(encoding="utf-8"))
        require(
            annotations["proposal_sha256"] == exported["draft_sha256"]
            and annotations["outline_package_digest"] == draft["outline_package_digest"]
            and annotations["candidate_content_sha256"] == draft["candidate_content_sha256"],
            "structure_identity_mismatch", "The reviewed annotation does not bind the exact outline proposal.",
        )
    with open_validated_pack(source_page_pack) as base:
        require(base.manifest["representation"] == "page_text", "structure_source_not_page_text", "A reviewed structure needs a page-text source pack.")
        require(annotations["source_page_pack_digest"] == base.package_digest, "structure_identity_mismatch", "The reviewed annotation binds a different page-text package.")
        require(annotations["document_id"] == base.manifest["identifier"], "structure_identity_mismatch", "Structure annotations belong to a different document.")
        require(annotations["edition_id"] == base.manifest["edition_id"], "structure_identity_mismatch", "Structure annotations belong to a different edition.")
        page_records = [record for record in base.records if record["kind"] == "page"]
        require(page_records and len(page_records) == len(base.records), "structure_source_not_page_text", "Source pack contains non-page records.")
        source_paths = {record["source"]["path"] for record in page_records}
        source_hashes = {record["source"]["sha256"] for record in page_records}
        require(len(source_paths) == len(source_hashes) == 1, "structure_source_ambiguous", "Select a one-component page-text pack for structural review.")
        source_relative = next(iter(source_paths))
        source_sha256 = next(iter(source_hashes))
        require(annotations["source_pdf_sha256"] == source_sha256, "structure_identity_mismatch", "Annotations bind a different source component.")
        source_path = base.root.joinpath(*PurePosixPath(source_relative).parts)
        document = {
            "document_id": base.manifest["identifier"],
            "document_family_id": base.manifest["document_family_id"],
            "edition_id": base.manifest["edition_id"],
            "title": base.manifest["title"],
            "publisher": base.manifest["publisher"],
            "revision": base.manifest["revision"],
            "change": 0,
            "document_date": base.manifest["publication_date"],
            "local_filename": PurePosixPath(source_relative).name,
            "sha256": source_sha256,
            "byte_length": source_path.stat().st_size,
        }
        return _compile_structured_section(
            document, source_path, annotations, output_directory,
            source_page_pack=base,
            source_page_records=page_records,
        )


def _compile_structured_section(
    document: dict[str, Any],
    source_path: Path,
    annotations: dict[str, Any],
    output_directory: str | Path,
    *,
    source_page_pack: Any = None,
    source_page_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    review = annotations["review"]
    require(source_path.stat().st_size <= MAX_PDF_BYTES, "compiler_limit_exceeded", "The PDF exceeds the compiler size limit.")
    output = Path(output_directory).resolve()
    require(not output.exists(), "compiler_output_exists", "The compiler output directory already exists.", path=str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".standardsforge-structure-", dir=output.parent))
    try:
        sources = staging / "sources"
        page_sources = sources / "pages"
        page_sources.mkdir(parents=True)
        pdf_relative = f"sources/{document['local_filename']}"
        shutil.copyfile(source_path, sources / document["local_filename"])
        require(_sha256((sources / document["local_filename"]).read_bytes()) == document["sha256"], "source_hash_mismatch", "The copied structural source PDF changed.")

        all_annotation_spans = [span for node in annotations["nodes"] for span in node["source_spans"]]
        all_annotation_spans.extend(
            span for relationship in annotations["relationships"] for span in relationship["evidence_spans"]
        )
        all_annotation_spans.extend(
            span for region in annotations["unsupported_regions"] for span in region["source_spans"]
        )
        pages: dict[int, tuple[str, str, bytes]] = {}
        selected_pages = sorted({span["physical_page"] for span in all_annotation_spans})
        if source_page_pack is not None:
            assert source_page_records is not None
            by_page: dict[int, dict[str, Any]] = {}
            for record in source_page_records:
                physical_page = record["source"]["page"]
                require(physical_page not in by_page, "structure_source_ambiguous", "The source pack has duplicate physical-page identities.", physical_page=physical_page)
                by_page[physical_page] = record
            for physical_page in selected_pages:
                record = by_page.get(physical_page)
                require(record is not None, "invalid_structure_annotations", "A structural node references a page absent from the verified source pack.", physical_page=physical_page)
                page_bytes = record["text"].encode("utf-8")
                relative = f"sources/pages/physical-{physical_page:04d}.txt"
                staging.joinpath(*PurePosixPath(relative).parts).write_bytes(page_bytes)
                pages[physical_page] = (relative, _sha256(page_bytes), page_bytes)
        else:
            with isolated_pdf_pages(
                source_path,
                source_sha256=document["sha256"],
                source_bytes=document["byte_length"],
                expected_pages=document["page_count"],
                extraction_mode="simple",
                encryption_policy="reject",
            ) as parsed:
                page_count = parsed.page_count
                parsed_by_page = {page.physical_page: page for page in parsed.pages}
                for physical_page in selected_pages:
                    require(physical_page <= page_count, "invalid_structure_annotations", "A structural node references a page outside the source PDF.", physical_page=physical_page)
                    parsed_page = parsed_by_page[physical_page]
                    require(parsed_page.text_layer_status == "extracted", "pdf_text_layer_empty", "A structural source page has no extractable text layer.", page=physical_page)
                    page_bytes = parsed_page.path.read_bytes()
                    relative = f"sources/pages/physical-{physical_page:04d}.txt"
                    staging.joinpath(*PurePosixPath(relative).parts).write_bytes(page_bytes)
                    pages[physical_page] = (relative, parsed_page.sha256, page_bytes)
        for span in all_annotation_spans:
            _, actual_page_hash, page_bytes = pages[span["physical_page"]]
            require(span["page_text_sha256"] == actual_page_hash, "structure_span_mismatch", "A structural page-text digest changed.", physical_page=span["physical_page"])
            require(span["end_byte"] <= len(page_bytes), "invalid_structure_annotations", "A structural span exceeds its extracted page.", physical_page=span["physical_page"])
            try:
                page_bytes[span["start_byte"]:span["end_byte"]].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise StandardsForgeError("invalid_structure_annotations", "A structural span splits UTF-8 text.", {"physical_page": span["physical_page"]}) from exc

        record_id_by_logical_id = {
            node["logical_id"]: _record_id(document["edition_id"], node["logical_id"])
            for node in annotations["nodes"]
        }
        relationships_by_source: dict[str, list[dict[str, Any]]] = {}
        for relationship in annotations["relationships"]:
            normalized_relationship = {
                "relationship": relationship["relationship_type"],
                "target_status": relationship["target_status"],
                "target_logical_id": relationship.get("target_logical_id"),
                "target_locator": relationship.get("target_reference"),
                "candidate_logical_ids": relationship.get("candidate_logical_ids", []),
                "required": relationship["required"],
                "method": relationship["derivation"]["method"],
                "review_status": relationship["derivation"]["review_status"],
                "evidence_spans": [],
            }
            for relationship_span in relationship["evidence_spans"]:
                text_relative, text_sha256, page_bytes = pages[relationship_span["physical_page"]]
                quote_bytes = page_bytes[relationship_span["start_byte"]:relationship_span["end_byte"]]
                normalized_relationship["evidence_spans"].append(
                    {
                        "path": pdf_relative,
                        "sha256": document["sha256"],
                        "text_path": text_relative,
                        "text_sha256": text_sha256,
                        "physical_page": relationship_span["physical_page"],
                        "start_byte": relationship_span["start_byte"],
                        "end_byte": relationship_span["end_byte"],
                        "quote_sha256": _sha256(quote_bytes),
                    }
                )
            relationships_by_source.setdefault(relationship["source_logical_id"], []).append(normalized_relationship)
        records: list[dict[str, Any]] = []
        logical_sidecars: list[str] = []
        for node in sorted(annotations["nodes"], key=lambda item: (item["ordinal"], item["logical_id"])):
            normalized_spans: list[dict[str, Any]] = []
            fragments: list[str] = []
            for node_span in node["source_spans"]:
                physical_page = node_span["physical_page"]
                start_byte = node_span["start_byte"]
                end_byte = node_span["end_byte"]
                text_relative, text_sha256, page_bytes = pages[physical_page]
                quote_bytes = page_bytes[start_byte:end_byte]
                try:
                    fragment = quote_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise StandardsForgeError(
                        "invalid_structure_annotations",
                        "A structural span splits UTF-8 text.",
                        {"logical_id": node["logical_id"]},
                    ) from exc
                fragments.append(fragment)
                normalized_spans.append(
                    {
                        "path": pdf_relative,
                        "sha256": document["sha256"],
                        "text_path": text_relative,
                        "text_sha256": text_sha256,
                        "physical_page": physical_page,
                        "start_byte": start_byte,
                        "end_byte": end_byte,
                        "quote_sha256": _sha256(quote_bytes),
                    }
                )
            assembled_text = "\n".join(fragments)
            require(
                assembled_text == node["exact_text"],
                "structure_span_mismatch",
                "Ordered structural spans do not reproduce the reviewed exact text.",
                logical_id=node["logical_id"],
            )
            quote_sha256 = _sha256(assembled_text.encode("utf-8"))
            require(
                quote_sha256 == node["content_sha256"],
                "structure_span_mismatch",
                "The assembled structural span digest changed.",
                logical_id=node["logical_id"],
            )
            semantics = node.get("semantics")
            if semantics is not None:
                selected_text = lambda indices: "\n".join(fragments[index] for index in indices)
                statement = semantics["statement"]
                if statement is not None:
                    statement_evidence = selected_text(statement["span_indices"])
                    require(statement["exact_text"] in statement_evidence, "structure_span_mismatch", "Semantic statement evidence is absent from its cited spans.", logical_id=node["logical_id"])
                    statement_lower = statement["exact_text"].casefold()
                    require(statement["subject"].casefold() in statement_lower, "invalid_structure_annotations", "Semantic statement subject is absent from its exact text.", logical_id=node["logical_id"])
                    require(statement["action"].casefold() in statement_lower, "invalid_structure_annotations", "Semantic statement action is absent from its exact text.", logical_id=node["logical_id"])
                    if statement["modality"] != "other":
                        require(statement["modality"] in statement_lower.split(), "invalid_structure_annotations", "Semantic statement modality is absent from its exact text.", logical_id=node["logical_id"])
                for qualifier in semantics["qualifiers"]:
                    require(qualifier["exact_text"] in selected_text(qualifier["span_indices"]), "structure_span_mismatch", "Semantic qualifier evidence is absent from its cited spans.", logical_id=node["logical_id"])
                for quantity in semantics["quantities"]:
                    require(quantity["raw"] in selected_text(quantity["span_indices"]), "structure_span_mismatch", "Semantic quantity evidence is absent from its cited spans.", logical_id=node["logical_id"])
                if semantics["content_role"] == "definition":
                    require(node["kind"] == "definition", "invalid_structure_annotations", "Definition semantics require a definition node.")
                if semantics["content_role"].startswith("table_"):
                    required_kind = {
                        "table_header": "table_cell",
                        "table_row": "table_row",
                        "table_footnote": "note",
                    }[semantics["content_role"]]
                    require(node["kind"] == required_kind, "invalid_structure_annotations", "Table semantics disagree with the structural node kind.")
            relationships = relationships_by_source.get(node["logical_id"], [])
            dependencies = [
                {
                    "relationship": relationship["relationship"],
                    "target_record_id": record_id_by_logical_id[relationship["target_logical_id"]],
                    "required": True,
                }
                for relationship in relationships
                if relationship["target_status"] == "resolved" and relationship["required"]
            ]
            first_span = normalized_spans[0]
            evidence_relative = first_span["text_path"]
            evidence_sha256 = first_span["text_sha256"]
            if len(normalized_spans) > 1:
                evidence_relative = f"sources/logical/{record_id_by_logical_id[node['logical_id']]}.txt"
                evidence_path = staging.joinpath(*PurePosixPath(evidence_relative).parts)
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                evidence_path.write_text(assembled_text, encoding="utf-8", newline="\n")
                evidence_sha256 = _sha256(evidence_path.read_bytes())
                logical_sidecars.append(evidence_relative)
            review_status = {
                "agent_reviewed": "agent_reviewed",
                "human_reviewed": "human_verified",
                "human_reviewed_with_uncertainty": "human_verified_with_uncertainty",
            }[node["derivation"]["review_status"]]
            review_tool = review.get("tool")
            review_issues = list(review.get("unresolved_issues", []))
            if annotations["schema_version"] == "0.1.0":
                if review["reviewer_type"] == "agent":
                    review_tool = {
                        "name": "unrecorded_legacy_annotation_tool",
                        "version": "not_recorded",
                        "configuration_sha256": None,
                    }
                review_issues.append(
                    "Legacy structure annotation 0.1.0 did not record complete review method and tool provenance."
                )
            review_event = {
                "schema_version": "0.1.0",
                "status": review_status,
                "reviewed_content_sha256": node["content_sha256"],
                "scope": "structure_and_semantics" if semantics is not None else "structure_only",
                "reviewer": {
                    "id": review["reviewer_id"],
                    "type": review["reviewer_type"],
                },
                "reviewed_at": review["reviewed_at"],
                "method": review.get("method", node["derivation"]["method"]),
                "tool": review_tool,
                "unresolved_issues": review_issues,
                "attestation": "extraction_review_not_project_applicability_or_approval",
            }
            locator = (
                f"physical PDF page {first_span['physical_page']}; UTF-8 bytes "
                f"{first_span['start_byte']}:{first_span['end_byte']}"
            )
            if len(normalized_spans) > 1:
                locator = "ordered reviewed source spans: " + "; ".join(
                    f"page {span['physical_page']} UTF-8 bytes {span['start_byte']}:{span['end_byte']}"
                    for span in normalized_spans
                )
            records.append(
                {
                    "record_id": record_id_by_logical_id[node["logical_id"]],
                    "edition_id": document["edition_id"],
                    "kind": node["kind"],
                    "clause_reference": node["clause_reference"],
                    "heading": node["heading"],
                    "text": node["exact_text"],
                    "source": {
                        "path": pdf_relative,
                        "sha256": document["sha256"],
                        "text_path": evidence_relative,
                        "text_sha256": evidence_sha256,
                        "page": first_span["physical_page"],
                        "locator": locator,
                        "quote_sha256": quote_sha256,
                    },
                    "derivation": {
                        "statement_role": node["statement_role"],
                        "method": node["derivation"]["method"],
                        "review_status": node["derivation"]["review_status"],
                    },
                    "dependencies": dependencies,
                    "structure": {
                        "logical_id": node["logical_id"],
                        "content_sha256": node["content_sha256"],
                        "parent_logical_id": node.get("parent_logical_id"),
                        "ordinal": node["ordinal"],
                        "source_spans": normalized_spans,
                        "relationships": relationships,
                        "semantics": semantics,
                        "review": review_event,
                    },
                }
            )

        annotation_relative = "derivations/structure-annotations.json"
        annotation_target = staging.joinpath(*PurePosixPath(annotation_relative).parts)
        annotation_target.parent.mkdir(parents=True)
        _write_json(annotation_target, annotations)
        revision = document["revision"] or "base"
        revision_label = f"{revision} Change {document['change']}" if document["change"] else revision
        manifest = {
            "schema_version": "0.1.0",
            "pack_id": (
                f"structured.{source_page_pack.manifest['pack_id']}.{annotations['proposal_sha256'][:16]}"
                if source_page_pack is not None else
                f"structured.{document['document_family_id'].replace(':', '.')}.{document['document_date']}"
            ),
            "document_family_id": document["document_family_id"],
            "edition_id": document["edition_id"],
            "publisher": document["publisher"],
            "identifier": document["document_id"],
            "title": document["title"],
            "revision": revision_label,
            "publication_date": document["document_date"],
            "category": "reviewed_structural_section",
            "representation": "reviewed_structure",
            "inventory_path": "inventory.json",
            "rights_path": "rights.json",
            "records_path": "records.json",
            "coverage": {
                "corpus_scope": f"reviewed_structural_annotations_for_{len(pages)}_physical_pages",
                "edition_composition": (
                    source_page_pack.manifest["coverage"]["edition_composition"]
                    if source_page_pack is not None else "exact_catalog_edition"
                ),
                "parsed_source_coverage": "partial_reviewed_structural_section_only",
                "dependency_closure": "partial_out_of_scope_references_explicit",
                "enumeration_traversal": "classified_structural_records_only_not_document_complete",
                "output_budget_coverage": "computed_at_query_time",
            },
        }
        rights = {
            "rights_schema_version": "0.1.0",
            "content_class": source_page_pack.rights["content_class"] if source_page_pack is not None else "public_government_standard",
            "redistribution": source_page_pack.rights["redistribution"] if source_page_pack is not None else "not_asserted_for_generated_pack",
            "processing": list(source_page_pack.rights["processing"]) if source_page_pack is not None else ["local_text_layer_extraction", "reviewed_structural_annotation", "local_retrieval"],
            "model_use": source_page_pack.rights["model_use"] if source_page_pack is not None else "not_used",
            "statement": (
                "The complete source PDF is included for exact offline evidence. Its imported rights claims are preserved, not granted; structural review gives no new processing, access, model-use, or redistribution permission."
                if source_page_pack is not None else
                "The reviewed structure is a derivation over a locally verified source; it does not grant access or assert source redistribution rights."
            ),
        }
        report = {
            "schema_version": "0.1.0",
            "compiler": {
                "name": "standardsforge-reviewed-structure",
                "version": STRUCTURE_COMPILER_VERSION,
                "base_pdf_compiler_version": COMPILER_VERSION,
                "pypdf_version": PYPDF_VERSION,
                "extraction_mode": annotations["extraction_mode"],
                "parser_protocol": PROTOCOL_VERSION,
                "limit_policy": LIMIT_POLICY_VERSION,
                "limits": DEFAULT_LIMITS.to_dict(),
            },
            "document_id": document["document_id"],
            "edition_id": document["edition_id"],
            "source_pdf_sha256": document["sha256"],
            "source_page_pack_digest": source_page_pack.package_digest if source_page_pack is not None else None,
            "outline_package_digest": annotations.get("outline_package_digest"),
            "candidate_record_id": annotations.get("candidate_record_id"),
            "candidate_content_sha256": annotations.get("candidate_content_sha256"),
            "proposal_sha256": annotations.get("proposal_sha256"),
            "annotation_sha256": _sha256(annotation_target.read_bytes()),
            "review": annotations["review"],
            "physical_pages": sorted(pages),
            "node_count": len(records),
            "multi_span_node_count": sum(
                len(node["source_spans"]) > 1 for node in annotations["nodes"]
            ),
            "logical_text_assembly": "ordered_source_fragments_joined_with_one_lf",
            "unsupported_regions": annotations["unsupported_regions"],
            "limitations": {
                "scope": "only_explicitly_reviewed_nodes_are_structured",
                "geometry": "not_captured",
                "tables": "not_interpreted_unless_explicitly_annotated",
                "figures": "not_interpreted_unless_explicitly_annotated",
                "cross_edition_identity": "not_reconciled",
            },
        }
        _write_json(staging / "manifest.json", manifest)
        _write_json(staging / "rights.json", rights)
        _write_json(staging / "records.json", {"schema_version": "0.1.0", "records": records})
        _write_json(staging / "structure-report.json", report)
        inventoried = [
            annotation_relative,
            "manifest.json",
            "records.json",
            "rights.json",
            "structure-report.json",
            pdf_relative,
            *(relative for relative, _, _ in pages.values()),
            *logical_sidecars,
        ]
        _write_json(
            staging / "inventory.json",
            {
                "schema_version": "0.1.0",
                "algorithm": "sha256",
                "files": [_inventory_entry(staging, relative) for relative in sorted(inventoried)],
            },
        )
        validated = validate_pack_directory(staging)
        os.replace(staging, output)
        return {
            "operation": "compile_structured_page_pack_section" if source_page_pack is not None else "compile_structured_pdf_section",
            "status": "compiled",
            "document_id": document["document_id"],
            "edition_id": document["edition_id"],
            "package_digest": validated.package_digest,
            "physical_pages": sorted(pages),
            "structural_records": len(records),
            "output_directory": str(output),
            "limitations": report["limitations"],
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)
