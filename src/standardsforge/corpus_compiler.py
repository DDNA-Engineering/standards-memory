from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .acquisition import verify_mil_std_acquisition
from .compiler import (
    COMPILER_VERSION,
    FONTTOOLS_VERSION,
    MAX_PDF_BYTES,
    PYPDF_VERSION,
)
from .errors import StandardsForgeError, require
from .pack import open_validated_pack, validate_pack_directory, write_pack_archive
from .pdf_isolation import isolated_pdf_pages
from .pdf_protocol import DEFAULT_LIMITS, LIMIT_POLICY_VERSION, PROTOCOL_VERSION


CORPUS_COMPILER_VERSION = "0.4.0"
MAX_ACQUISITION_MANIFEST_BYTES = 16 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[0-9]+\.[0-9]+$")


def _canonical_json_bytes(value: Any, *, compact: bool = False) -> bytes:
    if compact:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any, *, compact: bool = False) -> None:
    path.write_bytes(_canonical_json_bytes(value, compact=compact))


def _activate_compiled_directory(staging: Path, output: Path) -> None:
    for attempt in range(6):
        try:
            os.replace(staging, output)
            return
        except PermissionError as exc:
            require(
                not output.exists(),
                "compiler_output_exists",
                "The compiler output directory appeared during activation.",
                path=str(output),
            )
            if attempt == 5:
                raise StandardsForgeError(
                    "compiler_output_activation_failed",
                    "A compiled record directory could not be activated after bounded retries.",
                    {"path": str(output)},
                ) from exc
            time.sleep(0.05 * (2**attempt))


def _file_sha256(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        raise StandardsForgeError("source_read_failed", "A corpus source could not be read.", {"path": str(path)}) from exc


def _inventory_entry(root: Path, relative: str) -> dict[str, Any]:
    path = root.joinpath(*PurePosixPath(relative).parts)
    return {"path": relative, "sha256": _file_sha256(path), "bytes": path.stat().st_size}


def _required_string(value: Any, field: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), "invalid_acquisition_manifest", f"{field} is required.")
    return value.strip()


def _safe_relative_pdf(value: Any) -> str:
    text = _required_string(value, "component.local_path")
    path = PurePosixPath(text.replace("\\", "/"))
    require(
        not path.is_absolute() and ".." not in path.parts and path.suffix.lower() == ".pdf",
        "invalid_source_path",
        "A downloaded component path is unsafe.",
        path=text,
    )
    return path.as_posix()


def _load_acquisition_manifest(path: str | Path) -> tuple[dict[str, Any], str]:
    manifest_path = Path(path)
    require(manifest_path.is_file() and not manifest_path.is_symlink(), "acquisition_manifest_not_found", "The acquisition manifest does not exist.")
    require(
        manifest_path.stat().st_size <= MAX_ACQUISITION_MANIFEST_BYTES,
        "acquisition_manifest_limit_exceeded",
        "The acquisition manifest exceeds the compiler limit.",
    )
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_acquisition_manifest", "The acquisition manifest is not valid UTF-8 JSON.") from exc
    require(
        isinstance(manifest, dict)
        and manifest.get("schema_version") == "0.1.0"
        and manifest.get("catalog_id") == "dla-active-mil-std-current"
        and isinstance(manifest.get("records"), list),
        "invalid_acquisition_manifest",
        "The acquisition manifest has an unsupported identity or shape.",
    )
    return manifest, hashlib.sha256(raw).hexdigest()


def _component_descriptor(component: Any, ordinal: int) -> dict[str, Any]:
    require(isinstance(component, dict), "invalid_acquisition_manifest", "A current component must be an object.")
    status = _required_string(component.get("acquisition_status"), "component.acquisition_status")
    require(
        status in {"downloaded", "restricted_distribution"},
        "invalid_acquisition_manifest",
        "A current component has an unsupported acquisition status.",
        status=status,
    )
    token = component.get("token")
    require(
        token is None or (isinstance(token, str) and bool(_TOKEN.fullmatch(token))),
        "invalid_acquisition_manifest",
        "A component token is invalid.",
    )
    distribution_statement = _required_string(
        component.get("distribution_statement"), "component.distribution_statement"
    )
    require(
        (status == "downloaded" and distribution_statement == "A")
        or (status == "restricted_distribution" and distribution_statement != "A"),
        "invalid_acquisition_manifest",
        "A component acquisition status does not match its distribution statement.",
        status=status,
        distribution_statement=distribution_statement,
        token=token,
    )
    descriptor: dict[str, Any] = {
        "ordinal": ordinal,
        "token": token,
        "description": _required_string(component.get("description"), "component.description"),
        "document_date": _required_string(component.get("document_date"), "component.document_date"),
        "distribution_statement": distribution_statement,
        "acquisition_status": status,
    }
    if status == "downloaded":
        digest = component.get("sha256")
        require(
            isinstance(digest, str) and bool(_SHA256.fullmatch(digest)),
            "invalid_acquisition_manifest",
            "A downloaded component digest is invalid.",
        )
        byte_length = component.get("byte_length")
        page_count = component.get("page_count")
        require(type(byte_length) is int and byte_length > 0, "invalid_acquisition_manifest", "A downloaded component byte count is invalid.")
        require(type(page_count) is int and page_count > 0, "invalid_acquisition_manifest", "A downloaded component page count is invalid.")
        descriptor.update(
            {
                "local_path": _safe_relative_pdf(component.get("local_path")),
                "sha256": digest,
                "byte_length": byte_length,
                "page_count": page_count,
            }
        )
    return descriptor


def _record_descriptor(record: Any) -> dict[str, Any]:
    require(isinstance(record, dict), "invalid_acquisition_manifest", "A DLA record must be an object.")
    ident_number = _required_string(record.get("ident_number"), "record.ident_number")
    require(ident_number.isdigit(), "invalid_acquisition_manifest", "A DLA record identity must be numeric.")
    components = record.get("current_components")
    require(isinstance(components, list) and components, "invalid_acquisition_manifest", "A DLA record has no current components.")
    described = [_component_descriptor(component, ordinal) for ordinal, component in enumerate(components, start=1)]
    tokens = [component["token"] for component in described if component["token"] is not None]
    require(len(tokens) == len(set(tokens)), "invalid_acquisition_manifest", "A DLA record has duplicate component tokens.")
    return {
        "ident_number": ident_number,
        "document_id": _required_string(record.get("document_id"), "record.document_id"),
        "title": _required_string(record.get("title"), "record.title"),
        "document_date": _required_string(record.get("document_date"), "record.document_date"),
        "detail_url": _required_string(record.get("detail_url"), "record.detail_url"),
        "status": _required_string(record.get("status"), "record.status"),
        "fsc_area": record.get("fsc_area"),
        "components": described,
    }


def _composition_identity(record: dict[str, Any]) -> tuple[str, str, str, str]:
    identity_payload = {
        "ident_number": record["ident_number"],
        "ordered_current_components": [
            {
                key: component.get(key)
                for key in (
                    "ordinal",
                    "token",
                    "description",
                    "document_date",
                    "distribution_statement",
                    "acquisition_status",
                    "sha256",
                    "byte_length",
                    "page_count",
                )
            }
            for component in record["components"]
        ],
    }
    composition_sha256 = hashlib.sha256(_canonical_json_bytes(identity_payload, compact=True)).hexdigest()
    family_id = f"dla:mil-std-ident:{record['ident_number']}"
    edition_id = f"{family_id}:composition:{composition_sha256}"
    pack_id = f"compiled.dla.mil-std.ident-{record['ident_number']}.{composition_sha256}"
    return family_id, edition_id, pack_id, composition_sha256


def _source_path(root: Path, relative: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    require(not candidate.is_symlink(), "invalid_source_path", "Corpus source PDFs cannot be symbolic links.", path=relative)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise StandardsForgeError("invalid_source_path", "A corpus source escaped the acquisition root.", {"path": relative}) from exc
    require(resolved.is_file(), "source_file_missing", "A downloaded corpus source is missing.", path=relative)
    return resolved


def _component_key(component: dict[str, Any]) -> str:
    token = component["token"]
    require(token is not None, "invalid_acquisition_manifest", "A downloaded component requires a DLA token.")
    return f"{token.replace('.', '-')}-{component['sha256'][:12]}"


def _expected_composition_manifest(record: dict[str, Any], composition_sha256: str) -> dict[str, Any]:
    unavailable = [component for component in record["components"] if component["acquisition_status"] != "downloaded"]
    return {
        "schema_version": "0.1.0",
        "selection": "ordered current components recorded by the verified DLA active MIL-STD acquisition manifest",
        "ident_number": record["ident_number"],
        "document_id": record["document_id"],
        "composition_sha256": composition_sha256,
        "complete": not unavailable,
        "components": record["components"],
    }


def _expected_report_compiler() -> dict[str, Any]:
    return {
        "name": "standardsforge-dla-corpus-pdf-text-layer",
        "version": CORPUS_COMPILER_VERSION,
        "page_compiler_version": COMPILER_VERSION,
        "pypdf_version": PYPDF_VERSION,
        "fonttools_version": FONTTOOLS_VERSION,
        "extraction_mode": "layout",
        "rotated_text": "included",
        "parser_protocol": PROTOCOL_VERSION,
        "limit_policy": LIMIT_POLICY_VERSION,
        "limits": DEFAULT_LIMITS.to_dict(),
    }


def _compile_component(
    source_root: Path,
    staging: Path,
    component: dict[str, Any],
    edition_id: str,
) -> dict[str, Any]:
    source_path = _source_path(source_root, component["local_path"])
    require(source_path.stat().st_size == component["byte_length"], "source_size_mismatch", "A corpus source byte count changed.")
    require(component["byte_length"] <= MAX_PDF_BYTES, "compiler_limit_exceeded", "A corpus PDF exceeds the compiler size limit.")
    require(_file_sha256(source_path) == component["sha256"], "source_hash_mismatch", "A corpus source digest changed.")
    token = component["token"]
    component_key = _component_key(component)
    pdf_relative = f"sources/{component_key}.pdf"
    text_relative = f"sources/{component_key}.extracted.txt"
    pdf_target = staging.joinpath(*PurePosixPath(pdf_relative).parts)
    pdf_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, pdf_target)
    require(_file_sha256(pdf_target) == component["sha256"], "source_hash_mismatch", "A copied corpus source digest changed.")

    with isolated_pdf_pages(
        source_path,
        source_sha256=component["sha256"],
        source_bytes=component["byte_length"],
        expected_pages=component["page_count"],
        extraction_mode="layout_rotated_included",
        encryption_policy="empty_password_only",
    ) as parsed:
        page_count = parsed.page_count
        encryption_status = parsed.encryption_status
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
                        "marker": f"[[PDF_COMPONENT_{component_key}_PAGE_{page.physical_page:04d}]]",
                    }
                )

        sidecar_path = staging.joinpath(*PurePosixPath(text_relative).parts)
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
                sidecar.write(
                    f"\n[[END_PDF_COMPONENT_{component_key}_PAGE_{extracted['physical_page']:04d}]]".encode("utf-8")
                )
            sidecar.write(b"\n")
        text_sha256 = _file_sha256(sidecar_path)

    records = []
    for extracted in extracted_pages:
        page_index = extracted["physical_page"]
        records.append(
            {
                "record_id": f"pdf-{component_key}-page-{page_index:04d}-{extracted['text_sha256'][:12]}",
                "edition_id": edition_id,
                "kind": "page",
                "clause_reference": f"pdf-component:{component_key}:page:{page_index:04d}",
                "heading": f"{component['description']} - physical PDF page {page_index}",
                "source": {
                    "path": pdf_relative,
                    "sha256": component["sha256"],
                    "text_path": text_relative,
                    "text_sha256": text_sha256,
                    "text_start_byte": extracted["text_start_byte"],
                    "text_end_byte": extracted["text_end_byte"],
                    "page": page_index,
                    "locator": f"DLA component {token}; physical PDF page {page_index}; marker {extracted['marker']}",
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
    return {
        "component_key": component_key,
        "pdf_relative": pdf_relative,
        "text_relative": text_relative,
        "physical_pages": page_count,
        "records": records,
        "pages_without_text_records": page_count - len(records),
        "encryption_status": encryption_status,
        "report_pages": report_pages,
    }


def _compile_record_pack(record: dict[str, Any], source_root: Path, output_directory: Path) -> dict[str, Any]:
    downloaded = [component for component in record["components"] if component["acquisition_status"] == "downloaded"]
    require(downloaded, "no_downloaded_components", "A record without downloaded components cannot produce an evidence pack.")
    family_id, edition_id, pack_id, composition_sha256 = _composition_identity(record)
    output = output_directory.resolve()
    require(not output.exists(), "compiler_output_exists", "The compiler output directory already exists.", path=str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".standardsforge-corpus-compile-", dir=output.parent))
    try:
        component_results = [
            _compile_component(source_root, staging, component, edition_id) for component in downloaded
        ]
        records = [record_item for component in component_results for record_item in component["records"]]
        require(records, "pdf_text_layer_empty", "The DLA record has no extractable text-layer pages; OCR is not implicit.")
        unavailable = [component for component in record["components"] if component["acquisition_status"] != "downloaded"]
        unavailable_labels = [component["token"] or f"ordinal-{component['ordinal']}" for component in unavailable]
        edition_coverage = "complete" if not unavailable else (
            f"partial_current_component_set_{len(downloaded)}_of_{len(record['components'])};"
            f"unavailable={','.join(unavailable_labels)}"
        )
        page_count = sum(component["physical_pages"] for component in component_results)
        page_record_count = len(records)
        manifest = {
            "schema_version": "0.1.0",
            "pack_id": pack_id,
            "document_family_id": family_id,
            "edition_id": edition_id,
            "publisher": "United States Department of Defense",
            "identifier": record["document_id"],
            "title": record["title"],
            "revision": f"DLA current composition {composition_sha256[:16]}",
            "publication_date": record["document_date"],
            "category": "official_dla_current_pdf_text_layer",
            "representation": "page_text",
            "inventory_path": "inventory.json",
            "rights_path": "rights.json",
            "records_path": "records.json",
            "coverage": {
                "corpus_scope": "one_dla_active_mil_std_record_ordered_current_component_set",
                "edition_composition": edition_coverage,
                "parsed_source_coverage": f"text_layer_extracted_for_{page_record_count}_of_{page_count}_physical_pages_across_{len(downloaded)}_downloaded_components",
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
            "statement": "DLA distribution statements are preserved as provenance; this pack contains only downloaded public components and does not grant operational access or assert repository redistribution rights.",
        }
        composition = _expected_composition_manifest(record, composition_sha256)
        report = {
            "schema_version": "0.1.0",
            "compiler": _expected_report_compiler(),
            "document_id": record["document_id"],
            "edition_id": edition_id,
            "composition_sha256": composition_sha256,
            "downloaded_component_count": len(downloaded),
            "unavailable_component_count": len(unavailable),
            "physical_pages": page_count,
            "extracted_page_records": page_record_count,
            "pages_without_text_records": page_count - page_record_count,
            "fidelity": {
                "text_layer": "extracted_not_visually_verified",
                "ocr": "not_used",
                "tables": "not_interpreted",
                "figures": "not_interpreted",
                "clause_boundaries": "not_derived",
                "obligations": "not_classified",
            },
            "components": [
                {
                    "component_key": result["component_key"],
                    "token": component["token"],
                    "description": component["description"],
                    "source_pdf": {
                        "path": result["pdf_relative"],
                        "sha256": component["sha256"],
                        "byte_length": component["byte_length"],
                        "physical_pages": result["physical_pages"],
                    },
                    "extracted_page_records": len(result["records"]),
                    "pages_without_text_records": result["pages_without_text_records"],
                    "encryption_status": result["encryption_status"],
                    "pages": result["report_pages"],
                }
                for component, result in zip(downloaded, component_results, strict=True)
            ],
        }
        _write_json(staging / "manifest.json", manifest)
        _write_json(staging / "rights.json", rights)
        _write_json(staging / "records.json", {"schema_version": "0.2.0", "records": records}, compact=True)
        _write_json(staging / "component-manifest.json", composition)
        _write_json(staging / "extraction-report.json", report)
        inventoried = [
            "component-manifest.json",
            "extraction-report.json",
            "manifest.json",
            "records.json",
            "rights.json",
            *[result["pdf_relative"] for result in component_results],
            *[result["text_relative"] for result in component_results],
        ]
        inventory = {
            "schema_version": "0.1.0",
            "algorithm": "sha256",
            "files": [_inventory_entry(staging, relative) for relative in sorted(inventoried)],
        }
        _write_json(staging / "inventory.json", inventory)
        validated = validate_pack_directory(staging)
        _activate_compiled_directory(staging, output)
        return {
            "ident_number": record["ident_number"],
            "document_id": record["document_id"],
            "pack_id": pack_id,
            "edition_id": edition_id,
            "composition_sha256": composition_sha256,
            "package_digest": validated.package_digest,
            "component_count": len(record["components"]),
            "downloaded_component_count": len(downloaded),
            "unavailable_component_count": len(unavailable),
            "physical_pages": page_count,
            "page_records": page_record_count,
            "pages_without_text_records": page_count - page_record_count,
            "edition_composition_complete": not unavailable,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _checkpoint(path: Path, index: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_json_bytes(index))
    os.replace(temporary, path)


def _load_index(path: Path, manifest_sha256: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": "0.1.0",
            "corpus_id": "dla-active-mil-std-current-page-text",
            "acquisition_manifest_sha256": manifest_sha256,
            "compiler_version": CORPUS_COMPILER_VERSION,
            "entries": [],
            "failures": [],
            "summary": {},
        }
    require(path.is_file() and not path.is_symlink(), "invalid_corpus_index", "The corpus index is not a regular file.")
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_corpus_index", "The corpus index is not valid UTF-8 JSON.") from exc
    require(
        isinstance(index, dict)
        and index.get("schema_version") == "0.1.0"
        and index.get("corpus_id") == "dla-active-mil-std-current-page-text"
        and index.get("compiler_version") == CORPUS_COMPILER_VERSION
        and index.get("acquisition_manifest_sha256") == manifest_sha256
        and isinstance(index.get("entries"), list)
        and isinstance(index.get("failures"), list),
        "corpus_index_mismatch",
        "The existing corpus index does not match this acquisition snapshot and compiler.",
    )
    return index


def _validated_archive_entry(
    archive_path: Path,
    record: dict[str, Any],
    expected_pack_id: str,
    expected_edition_id: str,
    expected_composition_sha256: str,
) -> dict[str, Any]:
    require(archive_path.is_file() and not archive_path.is_symlink(), "corpus_archive_missing", "A corpus archive is missing.")
    with open_validated_pack(archive_path) as pack:
        require(pack.manifest["pack_id"] == expected_pack_id, "corpus_archive_mismatch", "A corpus archive has the wrong pack identity.")
        require(pack.manifest["edition_id"] == expected_edition_id, "corpus_archive_mismatch", "A corpus archive has the wrong edition identity.")
        composition = json.loads((pack.root / "component-manifest.json").read_text(encoding="utf-8"))
        require(
            composition == _expected_composition_manifest(record, expected_composition_sha256),
            "corpus_archive_mismatch",
            "A corpus archive does not match the complete ordered component composition.",
        )
        report = json.loads((pack.root / "extraction-report.json").read_text(encoding="utf-8"))
        downloaded = [component for component in record["components"] if component["acquisition_status"] == "downloaded"]
        unavailable = [component for component in record["components"] if component["acquisition_status"] != "downloaded"]
        physical_pages = sum(component["page_count"] for component in downloaded)
        require(
            isinstance(report, dict)
            and report.get("schema_version") == "0.1.0"
            and report.get("compiler") == _expected_report_compiler()
            and report.get("document_id") == record["document_id"]
            and report.get("edition_id") == expected_edition_id
            and report.get("composition_sha256") == expected_composition_sha256,
            "corpus_archive_mismatch",
            "A corpus archive extraction report has stale or mismatched compiler provenance.",
        )
        report_components = report.get("components")
        require(
            isinstance(report_components, list) and len(report_components) == len(downloaded),
            "corpus_archive_mismatch",
            "A corpus archive extraction report has the wrong component set.",
        )
        extracted_page_records = 0
        pages_without_text_records = 0
        expected_source_pages: dict[str, int] = {}
        for component, reported in zip(downloaded, report_components, strict=True):
            component_key = _component_key(component)
            source_path = f"sources/{component_key}.pdf"
            expected_source_pages[source_path] = component["page_count"]
            expected_source = {
                "path": source_path,
                "sha256": component["sha256"],
                "byte_length": component["byte_length"],
                "physical_pages": component["page_count"],
            }
            require(
                isinstance(reported, dict)
                and reported.get("component_key") == component_key
                and reported.get("token") == component["token"]
                and reported.get("description") == component["description"]
                and reported.get("source_pdf") == expected_source
                and reported.get("encryption_status") in {
                    "not_encrypted",
                    "empty_password_decrypted_for_extraction",
                },
                "corpus_archive_mismatch",
                "A corpus archive extraction report component does not match the acquisition manifest.",
            )
            component_records = reported.get("extracted_page_records")
            component_missing = reported.get("pages_without_text_records")
            pages = reported.get("pages")
            require(
                type(component_records) is int
                and component_records >= 0
                and type(component_missing) is int
                and component_missing >= 0
                and component_records + component_missing == component["page_count"]
                and isinstance(pages, list)
                and len(pages) == component["page_count"]
                and [page.get("physical_page") for page in pages if isinstance(page, dict)]
                == list(range(1, component["page_count"] + 1)),
                "corpus_archive_mismatch",
                "A corpus archive extraction report has inconsistent page counters.",
            )
            extracted_page_records += component_records
            pages_without_text_records += component_missing
        require(
            len(pack.records) == extracted_page_records
            and all(
                record_item.get("edition_id") == expected_edition_id
                and record_item.get("derivation", {}).get("statement_role") == "unclassified"
                and record_item.get("source", {}).get("path") in expected_source_pages
                and type(record_item.get("source", {}).get("page")) is int
                and 1 <= record_item["source"]["page"] <= expected_source_pages[record_item["source"]["path"]]
                for record_item in pack.records
            ),
            "corpus_archive_mismatch",
            "A corpus archive has records inconsistent with the current unclassified page representation.",
        )
        require(
            report.get("downloaded_component_count") == len(downloaded)
            and report.get("unavailable_component_count") == len(unavailable)
            and report.get("physical_pages") == physical_pages
            and report.get("extracted_page_records") == extracted_page_records
            and report.get("pages_without_text_records") == pages_without_text_records,
            "corpus_archive_mismatch",
            "A corpus archive extraction report has inconsistent aggregate counters.",
        )
        return {
            "ident_number": record["ident_number"],
            "document_id": record["document_id"],
            "pack_id": expected_pack_id,
            "edition_id": expected_edition_id,
            "composition_sha256": expected_composition_sha256,
            "package_digest": pack.package_digest,
            "archive_path": f"packs/{archive_path.name}",
            "archive_sha256": _file_sha256(archive_path),
            "archive_bytes": archive_path.stat().st_size,
            "component_count": len(record["components"]),
            "downloaded_component_count": len(downloaded),
            "unavailable_component_count": len(unavailable),
            "physical_pages": physical_pages,
            "page_records": extracted_page_records,
            "pages_without_text_records": pages_without_text_records,
            "edition_composition_complete": not unavailable,
        }


def compile_mil_std_corpus(
    manifest_path: str | Path,
    source_root: str | Path,
    output_root: str | Path,
    *,
    compresslevel: int = 6,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Compile and checkpoint one deterministic compressed page-text pack per readable DLA record."""

    require(type(compresslevel) is int and 1 <= compresslevel <= 9, "invalid_compression_level", "ZIP compression level must be 1 through 9.")
    verification = verify_mil_std_acquisition(manifest_path, source_root)
    manifest, manifest_sha256 = _load_acquisition_manifest(manifest_path)
    source = Path(source_root).resolve()
    destination = Path(output_root).resolve()
    require(
        source != destination and source not in destination.parents and destination not in source.parents,
        "invalid_corpus_output",
        "The corpus output and acquisition source root cannot contain one another.",
    )
    require(not destination.is_symlink(), "invalid_corpus_output", "The corpus output cannot be a symbolic link.")
    packs_root = destination / "packs"
    packs_root.mkdir(parents=True, exist_ok=True)
    index_path = destination / "corpus.json"
    index = _load_index(index_path, manifest_sha256)
    emit = progress or (lambda _: None)

    records = [_record_descriptor(record) for record in manifest["records"]]
    ident_numbers = [record["ident_number"] for record in records]
    require(len(ident_numbers) == len(set(ident_numbers)), "invalid_acquisition_manifest", "DLA record identities must be unique.")
    records.sort(key=lambda item: int(item["ident_number"]))
    compilable = [
        record for record in records if any(component["acquisition_status"] == "downloaded" for component in record["components"])
    ]
    existing_entries = {entry.get("ident_number"): entry for entry in index["entries"] if isinstance(entry, dict)}
    entries: list[dict[str, Any]] = []
    failures_by_ident = {
        failure.get("ident_number"): failure for failure in index["failures"] if isinstance(failure, dict)
    }

    for position, record in enumerate(compilable, start=1):
        family_id, edition_id, pack_id, composition_sha256 = _composition_identity(record)
        del family_id
        archive_path = packs_root / f"{record['ident_number']}-{composition_sha256[:16]}.zip"
        prior = existing_entries.get(record["ident_number"])
        try:
            if prior is not None:
                require(
                    prior.get("pack_id") == pack_id
                    and prior.get("edition_id") == edition_id
                    and prior.get("composition_sha256") == composition_sha256
                    and prior.get("archive_path") == f"packs/{archive_path.name}",
                    "corpus_index_mismatch",
                    "A checkpoint entry does not match the current DLA composition.",
                )
            if archive_path.exists():
                entry = _validated_archive_entry(archive_path, record, pack_id, edition_id, composition_sha256)
            else:
                with tempfile.TemporaryDirectory(prefix="standardsforge-record-pack-", dir=destination) as temporary:
                    pack_directory = Path(temporary) / "pack"
                    compiled = _compile_record_pack(record, source, pack_directory)
                    archived = write_pack_archive(pack_directory, archive_path, compresslevel=compresslevel)
                    entry = {
                        **compiled,
                        "archive_path": f"packs/{archive_path.name}",
                        "archive_sha256": _file_sha256(archive_path),
                        "archive_bytes": archived["archive_bytes"],
                    }
            if prior is not None:
                require(
                    prior.get("package_digest") == entry["package_digest"]
                    and prior.get("archive_sha256") == entry["archive_sha256"],
                    "corpus_archive_mismatch",
                    "A previously checkpointed archive changed.",
                )
            entries.append(entry)
            failures_by_ident.pop(record["ident_number"], None)
        except StandardsForgeError as exc:
            failures_by_ident[record["ident_number"]] = {
                "ident_number": record["ident_number"],
                "document_id": record["document_id"],
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        except Exception as exc:
            failures_by_ident[record["ident_number"]] = {
                "ident_number": record["ident_number"],
                "document_id": record["document_id"],
                "code": "internal_error",
                "message": "The record failed unexpectedly; no compiled result is asserted.",
                "details": {"type": type(exc).__name__},
            }
        index["entries"] = sorted(entries, key=lambda item: int(item["ident_number"]))
        index["failures"] = sorted(failures_by_ident.values(), key=lambda item: int(item["ident_number"]))
        index["summary"] = {
            "status": "incomplete" if index["failures"] or len(index["entries"]) != len(compilable) else "complete",
            "manifest_record_count": len(records),
            "compilable_record_count": len(compilable),
            "compiled_record_count": len(index["entries"]),
            "failed_record_count": len(index["failures"]),
            "restricted_only_record_count": len(records) - len(compilable),
            "verified_pdf_count": verification["verified_pdf_count"],
            "compiled_component_count": sum(entry["downloaded_component_count"] for entry in index["entries"]),
            "physical_pages": sum(entry["physical_pages"] for entry in index["entries"]),
            "page_records": sum(entry["page_records"] for entry in index["entries"]),
            "pages_without_text_records": sum(entry["pages_without_text_records"] for entry in index["entries"]),
            "archive_bytes": sum(entry["archive_bytes"] for entry in index["entries"]),
        }
        _checkpoint(index_path, index)
        if position % 10 == 0 or position == len(compilable):
            emit(
                f"Prepared {position}/{len(compilable)} DLA record packs "
                f"({len(index['entries'])} compiled, {len(index['failures'])} failed)"
            )

    if index["failures"]:
        raise StandardsForgeError(
            "corpus_compile_incomplete",
            "One or more DLA records could not be compiled; no complete-corpus claim is made.",
            {"index": str(index_path), **index["summary"]},
        )
    return {
        "operation": "compile_mil_std_corpus",
        "status": "compiled",
        "index": str(index_path),
        **index["summary"],
    }


def _load_complete_corpus_index(path: str | Path) -> tuple[Path, dict[str, Any]]:
    index_path = Path(path).resolve()
    require(index_path.is_file() and not index_path.is_symlink(), "invalid_corpus_index", "The corpus index is not a regular file.")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_corpus_index", "The corpus index is not valid UTF-8 JSON.") from exc
    require(
        isinstance(index, dict)
        and index.get("schema_version") == "0.1.0"
        and index.get("corpus_id") == "dla-active-mil-std-current-page-text"
        and index.get("compiler_version") == CORPUS_COMPILER_VERSION
        and isinstance(index.get("entries"), list)
        and isinstance(index.get("failures"), list)
        and isinstance(index.get("summary"), dict),
        "invalid_corpus_index",
        "The corpus index has an unsupported identity or shape.",
    )
    require(
        index["summary"].get("status") == "complete"
        and not index["failures"]
        and len(index["entries"]) == index["summary"].get("compilable_record_count"),
        "corpus_index_incomplete",
        "Only a complete failure-free corpus index can be authorized or installed.",
    )
    return index_path, index


def write_corpus_policy(index_path: str | Path, output_path: str | Path, principal_id: str) -> dict[str, Any]:
    """Write an explicit exact-pack allowlist for one completed local corpus."""

    _, index = _load_complete_corpus_index(index_path)
    principal = _required_string(principal_id, "principal_id")
    pack_ids = [entry.get("pack_id") for entry in index["entries"]]
    require(
        all(isinstance(pack_id, str) and pack_id for pack_id in pack_ids)
        and len(pack_ids) == len(set(pack_ids)),
        "invalid_corpus_index",
        "Corpus pack identities must be unique non-empty strings.",
    )
    destination = Path(output_path).resolve()
    require(not destination.exists(), "policy_output_exists", "The corpus policy output already exists.", path=str(destination))
    require(destination.suffix.lower() == ".json", "invalid_policy_path", "The corpus policy output must be JSON.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    policy = {
        "policy_version": "0.1.0",
        "policy_id": f"dla-active-mil-std-current-{index['acquisition_manifest_sha256'][:16]}",
        "principal_id": principal,
        "allow_admin_install": True,
        "allow_serve": True,
        "allowed_pack_ids": pack_ids,
        "allowed_content_classes": ["public_government_standard"],
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.stem}.", suffix=".json", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(_canonical_json_bytes(policy))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "operation": "write_corpus_policy",
        "status": "written",
        "policy": str(destination),
        "policy_id": policy["policy_id"],
        "principal_id": principal,
        "allowed_pack_count": len(pack_ids),
    }


def install_compiled_corpus(
    index_path: str | Path,
    policy_path: str | Path,
    db_path: str | Path,
    store_path: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Install every archive from a completed corpus through the existing policy boundary."""

    from .service import StandardsForgeService

    resolved_index, index = _load_complete_corpus_index(index_path)
    service = StandardsForgeService(db_path, store_path)
    emit = progress or (lambda _: None)
    installed = 0
    principals: set[str] = set()
    expected_digests_by_pack: dict[str, str] = {}
    for position, entry in enumerate(index["entries"], start=1):
        require(isinstance(entry, dict), "invalid_corpus_index", "A corpus entry must be an object.")
        relative = entry.get("archive_path")
        require(isinstance(relative, str) and relative.startswith("packs/"), "invalid_corpus_index", "A corpus archive path is invalid.")
        rel = PurePosixPath(relative)
        require(not rel.is_absolute() and ".." not in rel.parts and rel.suffix.lower() == ".zip", "invalid_corpus_index", "A corpus archive path is unsafe.")
        archive_path = resolved_index.parent.joinpath(*rel.parts)
        require(archive_path.is_file() and not archive_path.is_symlink(), "corpus_archive_missing", "A corpus archive is missing.", path=relative)
        require(
            _file_sha256(archive_path) == entry.get("archive_sha256"),
            "corpus_archive_mismatch",
            "A corpus archive digest changed after compilation.",
            path=relative,
        )
        result = service.install_pack(archive_path, policy_path)
        require(
            result["package_digest"] == entry.get("package_digest") and result["pack_id"] == entry.get("pack_id"),
            "corpus_archive_mismatch",
            "An installed corpus package identity does not match its index.",
        )
        principals.add(result["principal_id"])
        expected_digests_by_pack[result["pack_id"]] = result["package_digest"]
        installed += 1
        if position % 10 == 0 or position == len(index["entries"]):
            emit(f"Installed {position}/{len(index['entries'])} DLA record packs")
    require(len(principals) == 1, "invalid_policy", "The corpus installation did not bind one trusted principal.")
    principal_id = next(iter(principals))
    obsolete = [
        grant
        for grant in service.store.active_grants_for_pack_ids(principal_id, list(expected_digests_by_pack))
        if expected_digests_by_pack[grant["pack_id"]] != grant["package_digest"]
    ]
    revoked = sum(
        service.store.revoke(principal_id, grant["package_digest"])
        for grant in obsolete
    )
    return {
        "operation": "install_corpus",
        "status": "installed",
        "index": str(resolved_index),
        "installed_pack_count": installed,
        "principal_id": principal_id,
        "record_count": index["summary"]["page_records"],
        "component_count": index["summary"]["compiled_component_count"],
        "revoked_obsolete_pack_count": revoked,
    }
