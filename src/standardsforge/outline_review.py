from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .compiler import PYPDF_VERSION, _write_json
from .errors import StandardsForgeError, require
from .pack import open_validated_pack
from .structure_compiler import load_structure_annotations


_DRAFT_KEYS = {
    "schema_version", "state", "outline_package_digest", "source_page_pack_digest",
    "candidate_record_id", "candidate_content_sha256", "candidate_parent_logical_id",
    "document_id", "edition_id", "source_pdf_sha256", "source_pdf_path",
    "source_text_sha256", "compiler", "extraction_mode", "text_encoding",
    "offset_convention", "proposed_node",
}
_DECISION_KEYS = {"schema_version", "draft_sha256", "review", "node"}
_REVIEW_NODE_KEYS = {
    "logical_id", "kind", "ordinal", "clause_reference", "heading", "statement_role",
    "exact_text", "source_spans", "content_sha256", "derivation", "parent_logical_id",
    "semantics",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_closed_json(path: str | Path, keys: set[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_outline_review", f"{label} is not valid UTF-8 JSON.") from exc
    require(isinstance(value, dict) and set(value) == keys, "invalid_outline_review", f"{label} fields are invalid.")
    return value


def _write_new_json(output: Path, value: dict[str, Any], *, validate_reviewed: bool = False) -> None:
    require(not output.exists(), "compiler_output_exists", "The review output already exists.", path=str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".standardsforge-review-", dir=output.parent) as temporary:
        staged = Path(temporary) / "document.json"
        _write_json(staged, value)
        if validate_reviewed:
            load_structure_annotations(staged)
        require(not output.exists(), "compiler_output_exists", "The review output already exists.", path=str(output))
        os.replace(staged, output)


def _page_for_span(base: Any, span: dict[str, Any], source_pdf_sha256: str) -> tuple[dict[str, Any], bytes, int, int]:
    matches = [
        record for record in base.records
        if record["kind"] == "page"
        and record["source"]["page"] == span["physical_page"]
        and record["source"]["path"] == span["path"]
        and record["source"]["sha256"] == source_pdf_sha256
        and record["source"].get("text_path") == span["text_path"]
        and record["source"].get("text_sha256") == span["text_sha256"]
    ]
    require(len(matches) == 1, "outline_source_mismatch", "The candidate has no unique matching verified physical page.")
    record = matches[0]
    source = record["source"]
    require("text_start_byte" in source and "text_end_byte" in source, "outline_source_mismatch", "The source page is not offset-backed.")
    start = span["start_byte"] - source["text_start_byte"]
    end = span["end_byte"] - source["text_start_byte"]
    page_bytes = record["text"].encode("utf-8")
    require(0 <= start < end <= len(page_bytes), "outline_source_mismatch", "The candidate span falls outside its physical page.")
    try:
        fragment = page_bytes[start:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StandardsForgeError("outline_source_mismatch", "The candidate span splits UTF-8 text.") from exc
    require(_sha256(fragment.encode("utf-8")) == span["quote_sha256"], "outline_source_mismatch", "The candidate quote digest changed.")
    return record, page_bytes, start, end


def export_outline_review_draft(
    outline_pack: str | Path,
    source_page_pack: str | Path,
    record_id: str,
    output_path: str | Path,
) -> dict[str, Any]:
    """Export one unreviewed candidate with exact source-pack coordinates and no review claim."""

    output = Path(output_path).resolve()
    require(not output.exists(), "compiler_output_exists", "The outline review draft already exists.", path=str(output))
    with open_validated_pack(source_page_pack) as base, open_validated_pack(outline_pack) as outline:
        require(base.manifest["representation"] == "page_text", "outline_source_mismatch", "The base package is not page text.")
        require(outline.manifest["representation"] == "derived_structure", "outline_source_mismatch", "The candidate package is not derived structure.")
        require(outline.manifest["edition_id"] == base.manifest["edition_id"], "outline_source_mismatch", "The candidate and source editions differ.")
        descriptor_path = outline.root / "derivations" / "base-pack.json"
        require(descriptor_path.is_file(), "outline_source_mismatch", "The outline has no inventoried base-package descriptor.")
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        require(
            descriptor.get("base_package_digest") == base.package_digest
            and descriptor.get("base_pack_id") == base.manifest["pack_id"]
            and descriptor.get("base_edition_id") == base.manifest["edition_id"],
            "outline_source_mismatch", "The outline is not derived from this exact page-text package.",
        )
        matches = [record for record in outline.records if record["record_id"] == record_id]
        require(len(matches) == 1, "outline_candidate_not_found", "Select exactly one existing outline record.")
        candidate = matches[0]
        require(candidate["kind"] not in {"unsupported_region", "page"}, "outline_candidate_unsupported", "An unsupported region cannot become a reviewed node without an explicit separate annotation.")
        require(candidate["derivation"]["review_status"] == "automated_unreviewed", "outline_source_mismatch", "The source candidate is not an automated unreviewed outline.")
        raw_spans = candidate["structure"]["source_spans"]
        require(raw_spans and len(raw_spans) <= 64, "outline_source_mismatch", "The candidate source spans are outside the review limit.")
        source_pdf_hashes = {span["sha256"] for span in raw_spans}
        source_pdf_paths = {span["path"] for span in raw_spans}
        source_text_hashes = {span["text_sha256"] for span in raw_spans}
        require(len(source_pdf_hashes) == len(source_pdf_paths) == len(source_text_hashes) == 1, "outline_source_mismatch", "Select one source component and text sidecar for a review draft.")
        source_pdf_sha256 = next(iter(source_pdf_hashes))
        fragments: list[str] = []
        rebased_spans: list[dict[str, Any]] = []
        for span in raw_spans:
            _, page_bytes, start, end = _page_for_span(base, span, source_pdf_sha256)
            fragments.append(page_bytes[start:end].decode("utf-8"))
            rebased_spans.append({
                "physical_page": span["physical_page"],
                "page_text_sha256": _sha256(page_bytes),
                "start_byte": start,
                "end_byte": end,
            })
        exact_text = "\n".join(fragments)
        require(exact_text == candidate["text"] and _sha256(exact_text.encode("utf-8")) == candidate["structure"]["content_sha256"], "outline_source_mismatch", "The candidate text and exact source spans differ.")
        first_source = candidate["source"]
        require(first_source["sha256"] == source_pdf_sha256 and first_source.get("text_sha256") == next(iter(source_text_hashes)), "outline_source_mismatch", "The candidate source identity changed.")
        proposed_node = {
            "logical_id": candidate["structure"]["logical_id"],
            "kind": candidate["kind"],
            "ordinal": max(1, candidate["structure"]["ordinal"]),
            "clause_reference": candidate["clause_reference"],
            "heading": candidate["heading"],
            "statement_role": "unclassified",
            "exact_text": exact_text,
            "source_spans": rebased_spans,
            "content_sha256": _sha256(exact_text.encode("utf-8")),
            "derivation": {"method": candidate["derivation"]["method"], "review_status": "proposed"},
        }
        draft = {
            "schema_version": "0.1.0",
            "state": "proposed_unreviewed",
            "outline_package_digest": outline.package_digest,
            "source_page_pack_digest": base.package_digest,
            "candidate_record_id": record_id,
            "candidate_content_sha256": candidate["structure"]["content_sha256"],
            "candidate_parent_logical_id": candidate["structure"].get("parent_logical_id"),
            "document_id": base.manifest["identifier"],
            "edition_id": base.manifest["edition_id"],
            "source_pdf_sha256": source_pdf_sha256,
            "source_pdf_path": next(iter(source_pdf_paths)),
            "source_text_sha256": next(iter(source_text_hashes)),
            "compiler": {"name": "pypdf", "version": PYPDF_VERSION},
            "extraction_mode": "layout_rotated_included",
            "text_encoding": "UTF-8",
            "offset_convention": "half_open_utf8_byte_offsets_per_physical_page",
            "proposed_node": proposed_node,
        }
        _write_new_json(output, draft)
        return {
            "operation": "export_outline_review_draft", "status": "proposed_unreviewed",
            "draft_sha256": _sha256(output.read_bytes()), "candidate_record_id": record_id,
            "source_page_pack_digest": base.package_digest, "output_path": str(output),
        }


def promote_outline_review(
    draft_path: str | Path,
    decision_path: str | Path,
    outline_pack: str | Path,
    source_page_pack: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Turn an explicit content-bound review decision into a checked annotation file."""

    output = Path(output_path).resolve()
    require(not output.exists(), "compiler_output_exists", "The reviewed annotation output already exists.", path=str(output))
    draft = _read_closed_json(draft_path, _DRAFT_KEYS, "Outline review draft")
    decision = _read_closed_json(decision_path, _DECISION_KEYS, "Outline review decision")
    require(draft["schema_version"] == decision["schema_version"] == "0.1.0" and draft["state"] == "proposed_unreviewed", "invalid_outline_review", "Unsupported review draft or decision version/state.")
    draft_digest = _sha256(Path(draft_path).read_bytes())
    require(decision["draft_sha256"] == draft_digest, "outline_review_stale", "The reviewer decision does not bind these exact draft bytes.")
    with tempfile.TemporaryDirectory(prefix="standardsforge-review-verify-") as temporary:
        replay = Path(temporary) / "draft.json"
        export_outline_review_draft(outline_pack, source_page_pack, draft["candidate_record_id"], replay)
        require(replay.read_bytes() == Path(draft_path).read_bytes(), "outline_review_stale", "The draft no longer matches the exact source outline candidate.")
    proposed = draft["proposed_node"]
    node = decision["node"]
    require(isinstance(proposed, dict) and isinstance(node, dict) and set(node) <= _REVIEW_NODE_KEYS, "invalid_outline_review", "The reviewed node fields are invalid.")
    require(node.get("logical_id") == proposed.get("logical_id"), "outline_review_stale", "The decision changed the candidate logical identity.")
    require(isinstance(decision["review"], dict), "invalid_outline_review", "Explicit review provenance is required.")
    with open_validated_pack(source_page_pack) as base:
        require(base.package_digest == draft["source_page_pack_digest"], "outline_review_stale", "The source page-text package changed after proposal.")
        require(base.manifest["identifier"] == draft["document_id"] and base.manifest["edition_id"] == draft["edition_id"], "outline_review_stale", "The source document identity changed.")
        page_records = [record for record in base.records if record["kind"] == "page"]
        source_paths = {record["source"]["path"] for record in page_records}
        source_hashes = {record["source"]["sha256"] for record in page_records}
        require(source_paths == {draft["source_pdf_path"]} and source_hashes == {draft["source_pdf_sha256"]}, "outline_review_stale", "The source component changed or is ambiguous.")
        by_page: dict[int, dict[str, Any]] = {}
        for record in page_records:
            page = record["source"]["page"]
            require(page not in by_page, "outline_review_stale", "The source has ambiguous physical pages.")
            by_page[page] = record
        fragments = []
        for span in node.get("source_spans", []):
            require(isinstance(span, dict), "invalid_outline_review", "Reviewed spans must be objects.")
            record = by_page.get(span.get("physical_page"))
            require(record is not None, "outline_review_stale", "A reviewed span has no matching source page.")
            page_bytes = record["text"].encode("utf-8")
            require(span.get("page_text_sha256") == _sha256(page_bytes), "outline_review_stale", "A reviewed page-text digest changed.")
            start, end = span.get("start_byte"), span.get("end_byte")
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(page_bytes), "invalid_outline_review", "A reviewed span falls outside its page.")
            try:
                fragments.append(page_bytes[start:end].decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise StandardsForgeError("invalid_outline_review", "A reviewed span splits UTF-8 text.") from exc
        require("\n".join(fragments) == node.get("exact_text"), "outline_review_stale", "The reviewed exact text is not the cited source text.")
        annotations = {
            "schema_version": "0.4.0",
            "document_id": draft["document_id"],
            "edition_id": draft["edition_id"],
            "source_pdf_sha256": draft["source_pdf_sha256"],
            "source_page_pack_digest": base.package_digest,
            "outline_package_digest": draft["outline_package_digest"],
            "candidate_record_id": draft["candidate_record_id"],
            "candidate_content_sha256": draft["candidate_content_sha256"],
            "proposal_sha256": draft_digest,
            "compiler": draft["compiler"],
            "extraction_mode": draft["extraction_mode"],
            "text_encoding": draft["text_encoding"],
            "offset_convention": draft["offset_convention"],
            "review": decision["review"],
            "nodes": [node],
            "relationships": [],
            "unsupported_regions": [],
        }
        _write_new_json(output, annotations, validate_reviewed=True)
        return {
            "operation": "promote_outline_review", "status": "reviewed_annotation_written",
            "annotation_sha256": _sha256(output.read_bytes()), "proposal_sha256": draft_digest,
            "source_page_pack_digest": base.package_digest, "output_path": str(output),
        }
