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
    MAX_PDF_PAGES,
    PYPDF_VERSION,
    _inventory_entry,
    _load_pypdf,
    _normalize_page_text,
    _source_document,
    _write_json,
)
from .errors import StandardsForgeError, require
from .pack import validate_pack_directory
from .source_catalog import load_source_catalog, verify_source_set


STRUCTURE_COMPILER_VERSION = "0.1.0"
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
    "header_for",
    "illustrates",
    "continues_on",
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
_COMPILER_KEYS = {"name", "version"}
_REVIEW_KEYS = {"reviewer_id", "reviewer_type", "reviewed_at"}
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


def load_structure_annotations(path: str | Path) -> dict[str, Any]:
    annotation_path = Path(path).resolve()
    require(annotation_path.is_file(), "structure_annotations_not_found", "The structure annotation file does not exist.")
    try:
        raw = json.loads(annotation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_structure_annotations", "The structure annotation file is invalid JSON.") from exc
    annotations = _strict_object(raw, _ANNOTATION_KEYS, "structure annotations")
    require(annotations["schema_version"] == "0.1.0", "unsupported_schema_version", "Unsupported structure annotation schema.")
    for key in ("document_id", "edition_id", "source_pdf_sha256"):
        require(isinstance(annotations[key], str) and annotations[key], "invalid_structure_annotations", f"{key} is required.")
    require(len(annotations["source_pdf_sha256"]) == 64, "invalid_structure_annotations", "The source PDF digest is invalid.")
    compiler = _strict_object(annotations["compiler"], _COMPILER_KEYS, "compiler")
    require(compiler == {"name": "pypdf", "version": PYPDF_VERSION}, "invalid_structure_annotations", "Structure annotations must bind the pinned PDF compiler.")
    require(annotations["extraction_mode"] == "simple", "invalid_structure_annotations", "The structural compiler currently supports only simple text extraction.")
    require(annotations["text_encoding"] == "UTF-8", "invalid_structure_annotations", "Structural annotations require UTF-8 page text.")
    require(annotations["offset_convention"] == "half_open_utf8_byte_offsets_per_physical_page", "invalid_structure_annotations", "Unsupported structural offset convention.")
    review = _strict_object(annotations["review"], _REVIEW_KEYS, "review")
    require(all(isinstance(review[key], str) and review[key] for key in _REVIEW_KEYS), "invalid_structure_annotations", "Review provenance is required.")
    require(review["reviewer_type"] in {"agent", "human"}, "invalid_structure_annotations", "Reviewer type is invalid.")
    nodes = annotations["nodes"]
    require(isinstance(nodes, list) and nodes, "invalid_structure_annotations", "At least one structural node is required.")
    require(len(nodes) <= 4096, "invalid_structure_annotations", "The structural annotation node limit was exceeded.")
    logical_ids: set[str] = set()
    clause_references: set[str] = set()
    for value in nodes:
        node = _bounded_object(value, _NODE_KEYS - {"parent_logical_id"}, {"parent_logical_id"}, "structural node")
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
        require(isinstance(node["source_spans"], list) and len(node["source_spans"]) == 1, "invalid_structure_annotations", "Structural compiler v0.1 requires exactly one source span per node.")
        _validate_span(node["source_spans"][0], "node source span")
        require(node["content_sha256"] == _sha256(node["exact_text"].encode("utf-8")), "invalid_structure_annotations", "Structural content digest does not match exact text.", logical_id=node["logical_id"])
        require(node["statement_role"] in STATEMENT_ROLES, "invalid_structure_annotations", "Unsupported structural statement role.")
        _validate_derivation(node["derivation"], "node derivation", review["reviewer_type"])
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
    require(annotations["document_id"] == document["document_id"], "structure_identity_mismatch", "Structure annotations belong to a different document.")
    require(annotations["edition_id"] == document["edition_id"], "structure_identity_mismatch", "Structure annotations belong to a different edition.")
    require(annotations["source_pdf_sha256"] == document["sha256"], "structure_identity_mismatch", "Structure annotations bind a different source PDF.")

    pypdf = _load_pypdf()
    source_path = Path(source_root).resolve() / document["local_filename"]
    require(source_path.stat().st_size <= MAX_PDF_BYTES, "compiler_limit_exceeded", "The PDF exceeds the compiler size limit.")
    output = Path(output_directory).resolve()
    require(not output.exists(), "compiler_output_exists", "The compiler output directory already exists.", path=str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".standardsforge-structure-", dir=output.parent))
    try:
        try:
            reader = pypdf.PdfReader(source_path, strict=True)
        except Exception as exc:
            raise StandardsForgeError("invalid_pdf", "The verified source could not be parsed as a strict PDF.") from exc
        require(not reader.is_encrypted, "encrypted_pdf", "Encrypted PDFs are not supported by the structural compiler.")
        page_count = len(reader.pages)
        require(1 <= page_count <= MAX_PDF_PAGES, "compiler_limit_exceeded", "The PDF page count is outside the compiler limit.")
        require(page_count == document["page_count"], "pdf_page_count_mismatch", "The PDF page count does not match catalog metadata.")

        sources = staging / "sources"
        page_sources = sources / "pages"
        page_sources.mkdir(parents=True)
        pdf_relative = f"sources/{document['local_filename']}"
        shutil.copyfile(source_path, sources / document["local_filename"])

        all_annotation_spans = [span for node in annotations["nodes"] for span in node["source_spans"]]
        all_annotation_spans.extend(
            span for relationship in annotations["relationships"] for span in relationship["evidence_spans"]
        )
        all_annotation_spans.extend(
            span for region in annotations["unsupported_regions"] for span in region["source_spans"]
        )
        pages: dict[int, tuple[str, str, bytes]] = {}
        for physical_page in sorted({span["physical_page"] for span in all_annotation_spans}):
            require(physical_page <= page_count, "invalid_structure_annotations", "A structural node references a page outside the source PDF.", physical_page=physical_page)
            try:
                text = _normalize_page_text(reader.pages[physical_page - 1].extract_text() or "")
            except Exception as exc:
                raise StandardsForgeError("pdf_page_extraction_failed", "A structural source page could not be extracted.", {"page": physical_page}) from exc
            require(text, "pdf_text_layer_empty", "A structural source page has no extractable text layer.", page=physical_page)
            page_bytes = text.encode("utf-8")
            relative = f"sources/pages/physical-{physical_page:04d}.txt"
            staging.joinpath(*PurePosixPath(relative).parts).write_bytes(page_bytes)
            pages[physical_page] = (relative, _sha256(page_bytes), page_bytes)
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
        for node in sorted(annotations["nodes"], key=lambda item: (item["ordinal"], item["logical_id"])):
            node_span = node["source_spans"][0]
            physical_page = node_span["physical_page"]
            start_byte = node_span["start_byte"]
            end_byte = node_span["end_byte"]
            text_relative, text_sha256, page_bytes = pages[physical_page]
            quote_bytes = page_bytes[start_byte:end_byte]
            try:
                quote = quote_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise StandardsForgeError("invalid_structure_annotations", "A structural span splits UTF-8 text.", {"logical_id": node["logical_id"]}) from exc
            require(quote == node["exact_text"], "structure_span_mismatch", "A structural span does not match the reviewed exact text.", logical_id=node["logical_id"])
            quote_sha256 = _sha256(quote_bytes)
            require(quote_sha256 == node["content_sha256"], "structure_span_mismatch", "A structural span digest changed.", logical_id=node["logical_id"])
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
            span = {
                "path": pdf_relative,
                "sha256": document["sha256"],
                "text_path": text_relative,
                "text_sha256": text_sha256,
                "physical_page": physical_page,
                "start_byte": start_byte,
                "end_byte": end_byte,
                "quote_sha256": quote_sha256,
            }
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
                        "text_path": text_relative,
                        "text_sha256": text_sha256,
                        "page": physical_page,
                        "locator": f"physical PDF page {physical_page}; UTF-8 bytes {start_byte}:{end_byte}",
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
                        "source_spans": [span],
                        "relationships": relationships,
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
            "pack_id": f"structured.{document['document_family_id'].replace(':', '.')}.{document['document_date']}",
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
                "edition_composition": "exact_catalog_edition",
                "parsed_source_coverage": "partial_reviewed_structural_section_only",
                "dependency_closure": "partial_out_of_scope_references_explicit",
                "enumeration_traversal": "classified_structural_records_only_not_document_complete",
                "output_budget_coverage": "computed_at_query_time",
            },
        }
        rights = {
            "rights_schema_version": "0.1.0",
            "content_class": "public_government_standard",
            "redistribution": "not_asserted_for_generated_pack",
            "processing": ["local_text_layer_extraction", "reviewed_structural_annotation", "local_retrieval"],
            "model_use": "not_used",
            "statement": "The reviewed structure is a derivation over a locally verified source; it does not grant access or assert source redistribution rights.",
        }
        report = {
            "schema_version": "0.1.0",
            "compiler": {
                "name": "standardsforge-reviewed-structure",
                "version": STRUCTURE_COMPILER_VERSION,
                "base_pdf_compiler_version": COMPILER_VERSION,
                "pypdf_version": PYPDF_VERSION,
                "extraction_mode": annotations["extraction_mode"],
            },
            "document_id": document["document_id"],
            "edition_id": document["edition_id"],
            "source_pdf_sha256": document["sha256"],
            "annotation_sha256": _sha256(annotation_target.read_bytes()),
            "review": annotations["review"],
            "physical_pages": sorted(pages),
            "node_count": len(records),
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
            "operation": "compile_structured_pdf_section",
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
