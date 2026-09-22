from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import require
from .pack import validate_pack_directory
from .pdf_isolation import isolated_pdf_pages
from .pdf_protocol import (
    DEFAULT_LIMITS,
    FONTTOOLS_VERSION,
    LIMIT_POLICY_VERSION,
    PROTOCOL_VERSION,
    PYPDF_VERSION,
    normalize_page_text,
)
from .source_catalog import load_source_catalog, verify_source_set


COMPILER_VERSION = "0.4.0"
MAX_PDF_BYTES = DEFAULT_LIMITS.source_bytes
MAX_PDF_PAGES = DEFAULT_LIMITS.pages
MAX_PAGE_CONTENT_BYTES = DEFAULT_LIMITS.page_content_bytes


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_json_bytes(value))


def _write_compact_json(path: Path, value: Any) -> None:
    path.write_bytes((json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))


_normalize_page_text = normalize_page_text


def _source_document(catalog: dict[str, Any], document_id: str) -> dict[str, Any]:
    require(isinstance(document_id, str) and document_id.strip(), "invalid_document_id", "A document ID is required.")
    matches = [item for item in catalog["documents"] if item["document_id"] == document_id.strip()]
    require(len(matches) == 1, "source_document_not_found", "The catalog does not contain exactly one matching document.")
    return matches[0]


def _inventory_entry(root: Path, relative: str) -> dict[str, Any]:
    path = root.joinpath(*PurePosixPath(relative).parts)
    data = path.read_bytes()
    return {"path": relative, "sha256": _sha256(data), "bytes": len(data)}


def compile_pdf_to_pack(
    catalog_path: str | Path,
    document_id: str,
    source_root: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Compile one verified text-layer PDF into a deterministic, installable page-record pack."""

    verify_source_set(catalog_path, source_root)
    catalog = load_source_catalog(catalog_path)
    document = _source_document(catalog, document_id)
    source_path = Path(source_root).resolve() / document["local_filename"]
    require(source_path.stat().st_size <= MAX_PDF_BYTES, "compiler_limit_exceeded", "The PDF exceeds the compiler size limit.")

    output = Path(output_directory).resolve()
    require(not output.exists(), "compiler_output_exists", "The compiler output directory already exists.", path=str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".standardsforge-compile-", dir=output.parent))
    try:
        with isolated_pdf_pages(
            source_path,
            source_sha256=document["sha256"],
            source_bytes=document["byte_length"],
            expected_pages=document["page_count"],
            extraction_mode="layout_rotated_included",
            encryption_policy="reject",
        ) as parsed:
            page_count = parsed.page_count
            sources = staging / "sources"
            sources.mkdir()
            pdf_relative = f"sources/{document['local_filename']}"
            pdf_target = sources / document["local_filename"]
            shutil.copyfile(source_path, pdf_target)

            text_filename = f"{Path(document['local_filename']).stem}.extracted.txt"
            text_relative = f"sources/{text_filename}"
            extracted_pages: list[dict[str, Any]] = []
            report_pages: list[dict[str, Any]] = []
            for page in parsed.pages:
                text_hash = page.sha256 if page.text_layer_status == "extracted" else None
                report_pages.append(
                    {
                        "physical_page": page.physical_page,
                        "content_stream_bytes": page.content_stream_bytes,
                        "text_characters": page.text_characters,
                        "text_sha256": text_hash,
                        "text_layer_status": page.text_layer_status,
                        "visual_fidelity": "not_verified",
                        "tables": "not_interpreted",
                        "figures": "not_interpreted",
                        "ocr": "not_used",
                    }
                )
                if page.text_layer_status == "extracted":
                    extracted_pages.append(
                        {
                            "physical_page": page.physical_page,
                            "text_path": page.path,
                            "text_sha256": page.sha256,
                            "marker": f"[[PDF_PAGE_{page.physical_page:04d}]]",
                        }
                    )

            require(extracted_pages, "pdf_text_layer_empty", "The PDF has no extractable text-layer pages; OCR is not implicit.")
            sidecar_path = sources / text_filename
            with sidecar_path.open("wb") as sidecar:
                for index, extracted in enumerate(extracted_pages):
                    if index:
                        sidecar.write(b"\n\n")
                    sidecar.write(extracted["marker"].encode("utf-8"))
                    sidecar.write(b"\n")
                    extracted["text_start_byte"] = sidecar.tell()
                    with extracted["text_path"].open("rb") as page_text:
                        shutil.copyfileobj(page_text, sidecar, 1024 * 1024)
                    extracted["text_end_byte"] = sidecar.tell()
                    sidecar.write(f"\n[[END_PDF_PAGE_{extracted['physical_page']:04d}]]".encode("utf-8"))
                sidecar.write(b"\n")
            text_sha256 = _file_sha256(sidecar_path)

        records = []
        for extracted in extracted_pages:
            page_index = extracted["physical_page"]
            records.append(
                {
                    "record_id": f"pdf-page-{page_index:04d}-{extracted['text_sha256'][:12]}",
                    "edition_id": document["edition_id"],
                    "kind": "page",
                    "clause_reference": f"pdf-page:{page_index:04d}",
                    "heading": f"Physical PDF page {page_index}",
                    "source": {
                        "path": pdf_relative,
                        "sha256": document["sha256"],
                        "text_path": text_relative,
                        "text_sha256": text_sha256,
                        "text_start_byte": extracted["text_start_byte"],
                        "text_end_byte": extracted["text_end_byte"],
                        "page": page_index,
                        "locator": f"physical PDF page {page_index}; marker {extracted['marker']}",
                        "quote_sha256": extracted["text_sha256"],
                    },
                    "derivation": {
                        "statement_role": "unclassified",
                        "method": f"standardsforge-pdf-text-layer/{COMPILER_VERSION};pypdf/{PYPDF_VERSION};fonttools/{FONTTOOLS_VERSION};layout;rotated-text-included",
                        "review_status": "unreviewed",
                    },
                    "dependencies": [],
                }
            )

        revision = document["revision"] or "base"
        revision_label = f"{revision} Change {document['change']}" if document["change"] else revision
        manifest = {
            "schema_version": "0.1.0",
            "pack_id": f"compiled.{document['document_family_id'].replace(':', '.')}.{document['document_date']}",
            "document_family_id": document["document_family_id"],
            "edition_id": document["edition_id"],
            "publisher": document["publisher"],
            "identifier": document["document_id"],
            "title": document["title"],
            "revision": revision_label,
            "publication_date": document["document_date"],
            "category": "official_pdf_text_layer",
            "representation": "page_text",
            "inventory_path": "inventory.json",
            "rights_path": "rights.json",
            "records_path": "records.json",
            "coverage": {
                "corpus_scope": "single_catalog_pinned_official_pdf",
                "edition_composition": "exact_catalog_edition",
                "parsed_source_coverage": f"text_layer_extracted_for_{len(records)}_of_{page_count}_physical_pages",
                "dependency_closure": "not_derived_for_page_records",
                "enumeration_traversal": "page_records_only_not_clause_or_obligation_complete",
                "output_budget_coverage": "computed_at_query_time",
            },
        }
        rights = {
            "rights_schema_version": "0.1.0",
            "content_class": "public_government_standard",
            "redistribution": "not_asserted_for_generated_pack",
            "processing": ["local_text_layer_extraction", "local_indexing", "local_retrieval"],
            "model_use": "not_used",
            "statement": "Cataloged Distribution Statement A is preserved as provenance; this pack does not grant operational access or assert repository redistribution rights.",
        }
        report = {
            "schema_version": "0.1.0",
            "compiler": {
                "name": "standardsforge-pdf-text-layer",
                "version": COMPILER_VERSION,
                "pypdf_version": PYPDF_VERSION,
                "fonttools_version": FONTTOOLS_VERSION,
                "extraction_mode": "layout",
                "rotated_text": "included",
                "parser_protocol": PROTOCOL_VERSION,
                "limit_policy": LIMIT_POLICY_VERSION,
                "limits": DEFAULT_LIMITS.to_dict(),
            },
            "document_id": document["document_id"],
            "edition_id": document["edition_id"],
            "source_pdf": {
                "path": pdf_relative,
                "sha256": document["sha256"],
                "byte_length": document["byte_length"],
                "physical_pages": page_count,
            },
            "extracted_page_records": len(records),
            "pages_without_text_records": page_count - len(records),
            "fidelity": {
                "text_layer": "extracted_not_visually_verified",
                "ocr": "not_used",
                "tables": "not_interpreted",
                "figures": "not_interpreted",
                "clause_boundaries": "not_derived",
                "obligations": "not_classified",
            },
            "pages": report_pages,
        }
        _write_json(staging / "manifest.json", manifest)
        _write_json(staging / "rights.json", rights)
        # Page text is already preserved exactly in the inventoried UTF-8
        # sidecar. Records schema 0.2.0 stores only the verified half-open
        # byte range; pack validation reconstructs the in-memory record text.
        _write_compact_json(staging / "records.json", {"schema_version": "0.2.0", "records": records})
        _write_json(staging / "extraction-report.json", report)

        inventoried = [
            "extraction-report.json",
            "manifest.json",
            "records.json",
            "rights.json",
            pdf_relative,
            text_relative,
        ]
        inventory = {
            "schema_version": "0.1.0",
            "algorithm": "sha256",
            "files": [_inventory_entry(staging, relative) for relative in sorted(inventoried)],
        }
        _write_json(staging / "inventory.json", inventory)
        validated = validate_pack_directory(staging)
        os.replace(staging, output)
        return {
            "operation": "compile_pdf",
            "status": "compiled",
            "document_id": document["document_id"],
            "edition_id": document["edition_id"],
            "package_digest": validated.package_digest,
            "physical_pages": page_count,
            "page_records": len(records),
            "pages_without_text_records": page_count - len(records),
            "output_directory": str(output),
            "limitations": report["fidelity"],
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)
