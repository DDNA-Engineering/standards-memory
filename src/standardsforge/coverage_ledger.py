"""Administrative source coverage accounting; never grants semantic approval."""
from __future__ import annotations

import hashlib
import copy
import json
from pathlib import Path
from typing import Any

from .errors import require
from .models import ValidatedPack


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def page_ledger(pack: ValidatedPack) -> dict[str, Any]:
    """Include no-text pages as well as every extracted byte of a corpus pack."""
    require(pack.manifest.get("representation") == "page_text", "invalid_coverage_source", "Coverage requires a page-text corpus pack.")
    transcribed = pack.manifest.get("category") == "reviewed_visual_transcription"
    report_name = "transcription-report.json" if transcribed else "extraction-report.json"
    require(any(entry.path == report_name for entry in pack.inventory), "invalid_coverage_source", "The source report must be inventoried.")
    report = json.loads((pack.root / report_name).read_text(encoding="utf-8"))
    visual_review = "pending"
    if transcribed:
        visual_review = report["review"]["reviewer_type"] + "_reviewed"
        report = {"physical_pages": report["physical_pages"], "unavailable_component_count": 0,
                  "components": [{"source_pdf": report["source_pdf"], "pages": [
                      {"physical_page": p["physical_page"], "text_layer_status": "reviewed_blank" if p.get("disposition") == "reviewed_blank"
                       else "reviewed_visual_transcription"} for p in report["pages"]]}]}
    require(isinstance(report.get("components"), list), "invalid_coverage_source", "A component-level extraction report is required.")
    records = {(record["source"]["path"], record["source"]["page"]): record for record in pack.records}
    require(len(records) == len(pack.records), "invalid_coverage_source", "Each physical page must have one text record at most.")
    pages, consumed, keys = [], set(), set()
    for component in report["components"]:
        source = component["source_pdf"]
        require([p["physical_page"] for p in component["pages"]] == list(range(1, source["physical_pages"] + 1)), "invalid_coverage_source", "Physical pages must form a complete ordered inventory.")
        require(any(item.path == source["path"] and item.sha256 == source["sha256"] for item in pack.inventory), "invalid_coverage_source", "Page inventory source does not match pack inventory.")
        for page in component["pages"]:
            selector = (source["path"], page["physical_page"])
            require(selector not in keys, "invalid_coverage_source", "Duplicate physical page.")
            keys.add(selector)
            record = records.get(selector)
            if record is not None:
                consumed.add(selector)
                require(record["source"]["sha256"] == source["sha256"], "invalid_coverage_source", "Page source digest mismatch.")
            text = record["text"].encode("utf-8") if record else b""
            if page["text_layer_status"] == "reviewed_blank":
                require(record is None, "invalid_coverage_source", "A reviewed blank page cannot contain a text record.")
            identity = {"package_digest": pack.package_digest, "source_path": source["path"], "source_sha256": source["sha256"], "physical_page": page["physical_page"]}
            pages.append({**identity, "page_key": digest(identity), "record_id": record["record_id"] if record else None,
                          "text_sha256": hashlib.sha256(text).hexdigest(), "text_bytes": len(text),
                          "extraction_status": page["text_layer_status"], "dispositions": [], "undisposed_bytes": len(text),
                          "visual_review": visual_review, "semantic_review": "pending"})
    require(consumed == set(records), "invalid_coverage_source", "Some text records are absent from the physical page inventory.")
    require(len(pages) == report["physical_pages"], "invalid_coverage_source", "Physical page total mismatch.")
    body = {"package_digest": pack.package_digest, "edition_id": pack.manifest["edition_id"], "identifier": pack.manifest["identifier"],
            "pages": pages, "physical_pages": len(pages), "pages_without_text": sum(p["record_id"] is None for p in pages),
            "text_bytes": sum(p["text_bytes"] for p in pages), "unavailable_components": report["unavailable_component_count"],
            "semantic_qualification": "not_established", "approval": "not_granted"}
    return {"schema_version": "0.1.0", "ledger": body, "ledger_sha256": digest(body)}


def apply_dispositions(pack: ValidatedPack, review: dict[str, Any]) -> dict[str, Any]:
    """Replay page-local dispositions without turning reviewer claims into approval.

    Every byte must be explicitly dispositioned on submitted pages, including
    whitespace; unsubmitted pages and visual interpretation remain pending.
    """
    artifact = page_ledger(pack)
    require(isinstance(review, dict) and set(review) == {"ledger_sha256", "reviewer", "pages"}, "invalid_coverage_review", "Review fields are closed.")
    require(review["ledger_sha256"] == artifact["ledger_sha256"], "stale_coverage_review", "Review is bound to a different source ledger.")
    reviewer = review["reviewer"]
    require(isinstance(reviewer, dict) and set(reviewer) == {"kind", "identity", "reviewed_at"} and reviewer["kind"] in {"human", "agent"}
            and all(isinstance(reviewer[k], str) and reviewer[k].strip() for k in reviewer), "invalid_coverage_review", "Explicit reviewer provenance is required.")
    require(isinstance(review["pages"], list), "invalid_coverage_review", "Review pages must be an array.")
    by_key = {p["page_key"]: p for p in artifact["ledger"]["pages"]}
    texts = {record["record_id"]: record["text"].encode("utf-8") for record in pack.records}
    seen = set()
    for item in review["pages"]:
        require(isinstance(item, dict) and set(item) == {"page_key", "text_sha256", "segments"}, "invalid_coverage_review", "Page review fields are closed.")
        key = item["page_key"]
        require(isinstance(key, str) and key in by_key and key not in seen, "invalid_coverage_review", "Unknown or repeated page review.")
        seen.add(key)
        page = by_key[key]
        require(item["text_sha256"] == page["text_sha256"] and page["record_id"] is not None, "invalid_coverage_review", "Missing or stale page text cannot receive text dispositions.")
        text = texts[page["record_id"]]
        require(isinstance(item["segments"], list) and item["segments"], "invalid_coverage_review", "A complete page partition is required.")
        end = 0
        for segment in item["segments"]:
            require(isinstance(segment, dict) and set(segment) == {"start_byte", "end_byte", "disposition", "rationale"}, "invalid_coverage_review", "Disposition fields are closed.")
            require(type(segment["start_byte"]) is int and type(segment["end_byte"]) is int
                    and segment["start_byte"] == end and end < segment["end_byte"] <= len(text), "invalid_coverage_review", "Dispositions must partition exact page bytes without gaps or overlaps.")
            require(segment["disposition"] in {"requires_semantic_extraction", "non_normative", "unresolved"}
                    and isinstance(segment["rationale"], str) and segment["rationale"].strip(), "invalid_coverage_review", "Every disposition needs an explicit rationale.")
            fragment = text[end:segment["end_byte"]]
            try:
                fragment.decode("utf-8")
            except UnicodeDecodeError:
                require(False, "invalid_coverage_review", "Disposition splits a UTF-8 character.")
            end = segment["end_byte"]
        require(end == len(text), "invalid_coverage_review", "Page review leaves undispositioned text.")
        page["dispositions"] = item["segments"]
        page["undisposed_bytes"] = 0
        page["review_provenance"] = reviewer
    artifact["ledger"]["review_sha256"] = digest(review)
    artifact["ledger_sha256"] = digest(artifact["ledger"])
    return artifact


def link_semantic_evidence(pack: ValidatedPack, reviewed: ValidatedPack, artifact: dict[str, Any]) -> dict[str, Any]:
    """Link exact reviewed spans, without equating linked bytes with recall."""
    require(artifact["ledger"]["package_digest"] == pack.package_digest and artifact["ledger_sha256"] == digest(artifact["ledger"]),
            "invalid_coverage_source", "Ledger identity or digest differs from its source pack.")
    require(reviewed.manifest.get("representation") == "reviewed_structure" and
            any(i.path == "structure-report.json" for i in reviewed.inventory), "invalid_semantic_link", "An inventoried reviewed-structure report is required.")
    report = json.loads((reviewed.root / "structure-report.json").read_text(encoding="utf-8"))
    require(report.get("source_page_pack_digest") == pack.package_digest and reviewed.manifest["edition_id"] == pack.manifest["edition_id"],
            "invalid_semantic_link", "Semantic review must bind the exact source page package and edition.")
    result = copy.deepcopy(artifact)
    pages = {(p["source_sha256"], p["physical_page"]): p for p in result["ledger"]["pages"]}
    texts = {r["record_id"]: r["text"].encode("utf-8") for r in pack.records}
    for page in pages.values():
        page["semantic_links"] = []
    for record in reviewed.records:
        structure = record.get("structure")
        require(isinstance(structure, dict), "invalid_semantic_link", "Each linked record needs reviewed source spans.")
        semantics = structure.get("semantics")
        if semantics is None:
            continue
        for span in structure["source_spans"]:
            page = pages.get((span["sha256"], span["physical_page"]))
            require(page is not None and page["record_id"] is not None, "invalid_semantic_link", "Reviewed span is absent from the source ledger.")
            text = texts[page["record_id"]]
            require(span["text_sha256"] == hashlib.sha256(text).hexdigest() and span["end_byte"] <= len(text)
                    and hashlib.sha256(text[span["start_byte"]:span["end_byte"]]).hexdigest() == span["quote_sha256"],
                    "invalid_semantic_link", "Reviewed span does not match the exact page bytes.")
            page["semantic_links"].append({"package_digest": reviewed.package_digest, "record_id": record["record_id"],
                "start_byte": span["start_byte"], "end_byte": span["end_byte"], "quote_sha256": span["quote_sha256"],
                "content_role": semantics["content_role"], "reviewer_type": structure["review"]["reviewer"]["type"]})
    for page in pages.values():
        end, total = 0, 0
        for link in sorted(page["semantic_links"], key=lambda value: (value["start_byte"], value["end_byte"])):
            total += max(0, link["end_byte"] - max(end, link["start_byte"]))
            end = max(end, link["end_byte"])
        page["semantically_linked_bytes"] = total
        page["semantically_unlinked_bytes"] = page["text_bytes"] - total
    result["ledger_sha256"] = digest(result["ledger"])
    return result


def write_artifact(path: str | Path, artifact: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(artifact, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
