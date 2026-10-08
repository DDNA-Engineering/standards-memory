"""Explicit administrative import of reviewed page transcriptions.

Rendering/OCR and reviewer assertions are inputs, never query-time fallbacks.
The importer verifies evidence identity, not the truth of a reviewer's claim.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .compiler import _inventory_entry, _write_json
from .coverage_ledger import digest
from .errors import require
from .pack import open_validated_pack, validate_pack_directory
from .pdf_isolation import _is_regular_unlinked


def _closed(value: Any, keys: set[str]) -> None:
    require(isinstance(value, dict) and set(value) == keys, "invalid_transcription", "Transcription fields are closed.")


def _hash(value: Any) -> None:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            "invalid_transcription", "Expected a SHA-256 identity.")


def validate_transcription(document: dict[str, Any]) -> dict[str, Any]:
    _closed(document, {"schema_version", "transcription", "review"})
    require(document["schema_version"] in {"0.1.0", "0.2.0"}, "invalid_transcription", "Unsupported transcription version.")
    body, review = document["transcription"], document["review"]
    _closed(body, {"source_package_digest", "source_pdf_sha256", "renderer", "text_method", "pages"})
    for key in ("source_package_digest", "source_pdf_sha256"):
        _hash(body[key])
    for key in ("renderer", "text_method"):
        require(isinstance(body[key], str) and 0 < len(body[key]) <= 4096, "invalid_transcription", "Rendering and transcription methods must be explicit.")
    _closed(review, {"transcription_sha256", "reviewer_type", "reviewer_id", "reviewed_at", "attestation"})
    require(review["transcription_sha256"] == digest(body), "stale_transcription_review", "Review must bind exact text, source, methods, and rendered page identities.")
    require(review["reviewer_type"] in {"agent", "human"} and all(isinstance(review[k], str) and review[k].strip() for k in review),
            "invalid_transcription", "Explicit agent or human review provenance is required.")
    pages = body["pages"]
    require(isinstance(pages, list) and 1 <= len(pages) <= 5000, "invalid_transcription", "A bounded complete physical-page sequence is required.")
    total = 0
    for i, page in enumerate(pages, 1):
        _closed(page, {"physical_page", "text", "raster_sha256", "review_notes"}
                | ({"disposition"} if document["schema_version"] == "0.2.0" else set()))
        require(type(page["physical_page"]) is int and page["physical_page"] == i,
                "invalid_transcription", "Pages must be consecutive and unique, starting at one.")
        _hash(page["raster_sha256"])
        disposition = page.get("disposition", "transcribed_text")
        require(disposition in {"transcribed_text", "reviewed_blank"}, "invalid_transcription", "Explicit text or reviewed-blank disposition is required.")
        require(isinstance(page["text"], str) and "\r" not in page["text"]
                and (page["text"] == "" if disposition == "reviewed_blank" else bool(page["text"].strip())),
                "invalid_transcription", "Reviewed blank pages must have exactly empty text; transcribed pages require nonempty text with LF newlines.")
        require(isinstance(page["review_notes"], str) and page["review_notes"].strip(), "invalid_transcription", "Each page needs explicit visual-review notes.")
        total += len(page["text"].encode("utf-8"))
    require(total <= 64 * 1024 * 1024, "invalid_transcription", "Transcription exceeds the text bound.")
    require(total > 0, "invalid_transcription", "A queryable pack needs at least one text page; an entirely blank component has no retrievable text.")
    return body


def compile_page_transcription(source_pack: str | Path, transcription_path: str | Path,
                               raster_directory: str | Path, output_directory: str | Path) -> dict[str, Any]:
    path = Path(transcription_path)
    require(_is_regular_unlinked(path) and path.stat().st_size <= 128 * 1024 * 1024,
            "invalid_transcription", "A bounded regular transcription file is required.")
    document = json.loads(path.read_text(encoding="utf-8"))
    body = validate_transcription(document)
    output = Path(output_directory).resolve()
    require(not output.exists(), "compiler_output_exists", "The transcription output already exists.")
    rasters = Path(raster_directory)
    with open_validated_pack(source_pack) as base:
        require(base.manifest.get("representation") == "page_text" and base.package_digest == body["source_package_digest"],
                "transcription_source_mismatch", "Transcription must bind the exact page-text source package.")
        require(any(e.path == "extraction-report.json" for e in base.inventory), "invalid_transcription", "An inventoried physical-page extraction report is required.")
        report = json.loads((base.root / "extraction-report.json").read_text(encoding="utf-8"))
        components = report.get("components", [report])
        require(len(components) == 1, "invalid_transcription", "Transcribe one complete source component per pack.")
        source = components[0]["source_pdf"]
        require(source["sha256"] == body["source_pdf_sha256"] and source["physical_pages"] == len(body["pages"]),
                "transcription_source_mismatch", "Source PDF identity or physical-page coverage differs.")
        require(any(e.path == source["path"] and e.sha256 == source["sha256"] for e in base.inventory),
                "transcription_source_mismatch", "Source PDF must match the validated inventory.")
        require(report.get("unavailable_component_count", 0) == 0, "invalid_transcription", "Source composition must have no unavailable components.")
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".transcription-", dir=output.parent))
        try:
            (staging / "sources").mkdir()
            (staging / "evidence").mkdir()
            pdf_relative = "sources/original.pdf"
            shutil.copyfile(base.root / source["path"], staging / pdf_relative)
            require(hashlib.sha256((staging / pdf_relative).read_bytes()).hexdigest() == source["sha256"],
                    "transcription_source_mismatch", "Source changed during copying.")
            records, page_report = [], []
            total_rasters = 0
            for page in body["pages"]:
                n, text = page["physical_page"], page["text"].encode("utf-8")
                raster_name = f"page-{n:04d}.png"
                raster = rasters / raster_name
                require(_is_regular_unlinked(raster) and raster.stat().st_size <= 32 * 1024 * 1024,
                        "invalid_transcription", "Each reviewed page needs its bounded regular PNG evidence.", page=n)
                total_rasters += raster.stat().st_size
                require(total_rasters <= 1024 * 1024 * 1024, "invalid_transcription", "Rendered evidence exceeds the aggregate bound.")
                raster_bytes = raster.read_bytes()
                require(raster_bytes.startswith(b"\x89PNG\r\n\x1a\n") and hashlib.sha256(raster_bytes).hexdigest() == page["raster_sha256"],
                        "transcription_raster_mismatch", "Rendered evidence differs from the reviewed page.", page=n)
                (staging / "evidence" / raster_name).write_bytes(raster_bytes)
                text_relative = f"sources/page-{n:04d}.txt"
                (staging / text_relative).write_bytes(text)
                text_hash = hashlib.sha256(text).hexdigest()
                page_report.append({"physical_page": n, "text_sha256": text_hash, "text_bytes": len(text), "raster_path": f"evidence/{raster_name}",
                                    "raster_sha256": page["raster_sha256"], "review_notes": page["review_notes"],
                                    **({"disposition": page["disposition"]} if "disposition" in page else {})})
                if page.get("disposition") == "reviewed_blank":
                    continue
                records.append({"record_id": f"transcribed-page-{n:04d}-{text_hash[:12]}", "edition_id": base.manifest["edition_id"],
                                "kind": "page", "clause_reference": f"pdf-page:{n:04d}", "heading": f"Transcribed physical PDF page {n}",
                                "source": {"path": pdf_relative, "sha256": source["sha256"], "page": n,
                                           "locator": f"physical PDF page {n}; reviewed visual transcription; evidence/{raster_name}",
                                           "text_path": text_relative, "text_sha256": text_hash,
                                           "text_start_byte": 0, "text_end_byte": len(text), "quote_sha256": text_hash},
                                "derivation": {"statement_role": "unclassified", "method": "standardsforge-reviewed-visual-transcription/" + document["schema_version"] + "; " + body["text_method"],
                                               "review_status": document["review"]["reviewer_type"] + "_reviewed_transcription_semantics_unclassified"}, "dependencies": []})
            manifest = copy.deepcopy(base.manifest)
            manifest.update(pack_id=manifest["pack_id"] + ".transcription." + digest(document)[:16], category="reviewed_visual_transcription")
            manifest["coverage"].update(parsed_source_coverage=f"reviewed_visual_transcription_for_{len(page_report)}_of_{len(page_report)}_physical_pages",
                                        dependency_closure="not_derived_for_page_records", enumeration_traversal="page_records_only_not_clause_or_obligation_complete")
            manifest["records_path"], manifest["rights_path"], manifest["inventory_path"] = "records.json", "rights.json", "inventory.json"
            _write_json(staging / "manifest.json", manifest)
            rights = copy.deepcopy(base.rights)
            rights["processing"] = ["reviewed_visual_transcription", "local_indexing", "local_retrieval"]
            rights["model_use"] = "agent_review_declared" if document["review"]["reviewer_type"] == "agent" else "not_asserted"
            _write_json(staging / "rights.json", rights)
            _write_json(staging / "records.json", {"schema_version": "0.2.0", "records": records})
            _write_json(staging / "transcription.json", document)
            _write_json(staging / "transcription-report.json", {"schema_version": document["schema_version"], "source_package_digest": base.package_digest,
                        "source_pdf": {**source, "path": pdf_relative}, "physical_pages": len(page_report), "pages": page_report,
                        "review": document["review"], "semantic_qualification": "not_established", "approval": "not_granted",
                        "limitations": ["Raster-to-PDF correspondence and visual fidelity are reviewer claims, not authenticated by this importer.",
                                        "Transcription is derived evidence and does not replace the original PDF."]})
            _write_json(staging / "inventory.json", {"schema_version": "0.1.0", "algorithm": "sha256",
                        "files": [_inventory_entry(staging, p.relative_to(staging).as_posix()) for p in sorted(staging.rglob("*")) if p.is_file()]})
            validated = validate_pack_directory(staging)
            os.replace(staging, output)
            return {"operation": "compile_page_transcription", "package_digest": validated.package_digest, "physical_pages": len(page_report),
                    "reviewer_type": document["review"]["reviewer_type"], "semantic_qualification": "not_established", "output_directory": str(output)}
        finally:
            if staging.exists():
                shutil.rmtree(staging)
