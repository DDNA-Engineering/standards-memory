from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import StandardsForgeError, require
from .pack import validate_pack_directory
from .source_catalog import load_source_catalog, verify_source_set


COMPILER_VERSION = "0.3.1"
PYPDF_VERSION = "6.19.0"
FONTTOOLS_VERSION = "4.65.0"
MAX_PDF_BYTES = 256 * 1024 * 1024
MAX_PDF_PAGES = 5000
MAX_PAGE_CONTENT_BYTES = 64 * 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_json_bytes(value))


def _write_compact_json(path: Path, value: Any) -> None:
    path.write_bytes((json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))


def _normalize_page_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _load_pypdf() -> Any:
    try:
        import fontTools
        import pypdf
    except ImportError as exc:
        raise StandardsForgeError(
            "compiler_dependency_missing",
            'PDF compilation requires the pinned compiler extra: pip install -e ".[compiler]".',
        ) from exc
    require(
        pypdf.__version__ == PYPDF_VERSION,
        "unsupported_compiler_dependency",
        "PDF compilation requires the pinned pypdf version.",
        expected=PYPDF_VERSION,
        actual=pypdf.__version__,
    )
    require(
        fontTools.__version__ == FONTTOOLS_VERSION,
        "unsupported_compiler_dependency",
        "PDF compilation requires the pinned fontTools version.",
        expected=FONTTOOLS_VERSION,
        actual=fontTools.__version__,
    )
    return pypdf


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
    pypdf = _load_pypdf()

    source_path = Path(source_root).resolve() / document["local_filename"]
    require(source_path.stat().st_size <= MAX_PDF_BYTES, "compiler_limit_exceeded", "The PDF exceeds the compiler size limit.")

    output = Path(output_directory).resolve()
    require(not output.exists(), "compiler_output_exists", "The compiler output directory already exists.", path=str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".standardsforge-compile-", dir=output.parent))
    try:
        try:
            reader = pypdf.PdfReader(source_path, strict=True)
        except Exception as exc:
            raise StandardsForgeError("invalid_pdf", "The verified source could not be parsed as a strict PDF.") from exc
        require(not reader.is_encrypted, "encrypted_pdf", "Encrypted PDFs are not supported by the deterministic compiler.")
        page_count = len(reader.pages)
        require(1 <= page_count <= MAX_PDF_PAGES, "compiler_limit_exceeded", "The PDF page count is outside the compiler limit.")
        require(page_count == document["page_count"], "pdf_page_count_mismatch", "The PDF page count does not match catalog metadata.", expected=document["page_count"], actual=page_count)

        sources = staging / "sources"
        sources.mkdir()
        pdf_relative = f"sources/{document['local_filename']}"
        pdf_target = sources / document["local_filename"]
        shutil.copyfile(source_path, pdf_target)

        text_filename = f"{Path(document['local_filename']).stem}.extracted.txt"
        text_relative = f"sources/{text_filename}"
        extracted_pages: list[dict[str, Any]] = []
        report_pages: list[dict[str, Any]] = []
        for page_index, page in enumerate(reader.pages, start=1):
            try:
                contents = page.get_contents()
                content_bytes = 0 if contents is None else len(contents.get_data())
                require(
                    content_bytes <= MAX_PAGE_CONTENT_BYTES,
                    "compiler_limit_exceeded",
                    "A PDF page content stream exceeds the compiler limit.",
                    page=page_index,
                    bytes=content_bytes,
                )
                raw_text = ""
                if contents is not None:
                    raw_text = page.extract_text(
                        extraction_mode="layout",
                        layout_mode_space_vertically=False,
                        layout_mode_strip_rotated=False,
                    ) or ""
            except StandardsForgeError:
                raise
            except Exception as exc:
                raise StandardsForgeError("pdf_page_extraction_failed", "A PDF page text layer could not be extracted.", {"page": page_index}) from exc
            text = _normalize_page_text(raw_text)
            text_hash = _sha256(text.encode("utf-8")) if text else None
            report_pages.append(
                {
                    "physical_page": page_index,
                    "content_stream_bytes": content_bytes,
                    "text_characters": len(text),
                    "text_sha256": text_hash,
                    "text_layer_status": "extracted" if text else "no_text",
                    "visual_fidelity": "not_verified",
                    "tables": "not_interpreted",
                    "figures": "not_interpreted",
                    "ocr": "not_used",
                }
            )
            if not text:
                continue
            marker = f"[[PDF_PAGE_{page_index:04d}]]"
            extracted_pages.append(
                {
                    "physical_page": page_index,
                    "text": text,
                    "text_sha256": text_hash,
                    "marker": marker,
                }
            )

        require(extracted_pages, "pdf_text_layer_empty", "The PDF has no extractable text-layer pages; OCR is not implicit.")
        sidecar_builder = bytearray()
        for index, extracted in enumerate(extracted_pages):
            if index:
                sidecar_builder.extend(b"\n\n")
            marker_bytes = extracted["marker"].encode("utf-8")
            text_bytes = extracted["text"].encode("utf-8")
            sidecar_builder.extend(marker_bytes)
            sidecar_builder.extend(b"\n")
            extracted["text_start_byte"] = len(sidecar_builder)
            sidecar_builder.extend(text_bytes)
            extracted["text_end_byte"] = len(sidecar_builder)
            sidecar_builder.extend(f"\n[[END_PDF_PAGE_{extracted['physical_page']:04d}]]".encode("utf-8"))
        sidecar_builder.extend(b"\n")
        sidecar_bytes = bytes(sidecar_builder)
        (sources / text_filename).write_bytes(sidecar_bytes)
        text_sha256 = _sha256(sidecar_bytes)

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
