from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlparse

from .errors import StandardsForgeError, require


MAX_CATALOG_BYTES = 1024 * 1024
MAX_DOCUMENTS = 256
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CATALOG_KEYS = {
    "schema_version",
    "catalog_id",
    "title",
    "purpose",
    "selection_basis",
    "documents",
}
_DOCUMENT_KEYS = {
    "document_id",
    "document_family_id",
    "edition_id",
    "title",
    "publisher",
    "status",
    "revision",
    "change",
    "document_date",
    "distribution_statement",
    "detail_url",
    "source_origin",
    "local_filename",
    "sha256",
    "byte_length",
    "page_count",
    "retrieved_at",
    "rights",
}
_RIGHTS_KEYS = {"access_basis", "repository_redistribution"}


def _strict_object(value: Any, allowed: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), "invalid_source_catalog", f"{label} must be a JSON object.")
    unknown = sorted(set(value) - allowed)
    require(not unknown, "invalid_source_catalog", f"{label} has unknown fields.", fields=unknown)
    return value


def _required_string(value: Any, field: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), "invalid_source_catalog", f"{field} is required.")
    return value


def _iso_date(value: Any, field: str) -> str:
    text = _required_string(value, field)
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise StandardsForgeError("invalid_source_catalog", f"{field} must be an ISO calendar date.") from exc
    return text


def _safe_pdf_filename(value: Any) -> str:
    text = _required_string(value, "local_filename")
    path = PurePosixPath(text.replace("\\", "/"))
    require(
        not path.is_absolute() and len(path.parts) == 1 and path.name not in {".", ".."},
        "invalid_source_path",
        "Source filenames must be single relative path components.",
        path=text,
    )
    require(path.suffix.lower() == ".pdf", "invalid_source_path", "Catalog source files must be PDFs.", path=text)
    return path.name


def load_source_catalog(path: str | Path) -> dict[str, Any]:
    catalog_path = Path(path)
    require(not catalog_path.is_symlink(), "invalid_source_path", "The source catalog cannot be a symbolic link.")
    require(catalog_path.is_file(), "source_catalog_not_found", "The source catalog does not exist.")
    try:
        require(
            catalog_path.stat().st_size <= MAX_CATALOG_BYTES,
            "source_catalog_limit_exceeded",
            "The source catalog exceeds the size limit.",
        )
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except StandardsForgeError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_source_catalog", "The source catalog is not valid UTF-8 JSON.") from exc

    catalog = _strict_object(raw, _CATALOG_KEYS, "source catalog")
    require(catalog.get("schema_version") == "0.1.0", "unsupported_schema_version", "Unsupported source catalog schema.")
    for field in ("catalog_id", "title", "purpose", "selection_basis"):
        _required_string(catalog.get(field), field)

    documents = catalog.get("documents")
    require(
        isinstance(documents, list) and 1 <= len(documents) <= MAX_DOCUMENTS,
        "invalid_source_catalog",
        "documents must be a bounded non-empty list.",
    )
    seen_document_ids: set[str] = set()
    seen_edition_ids: set[str] = set()
    seen_filenames: set[str] = set()
    for item in documents:
        document = _strict_object(item, _DOCUMENT_KEYS, "source catalog document")
        require(set(document) == _DOCUMENT_KEYS, "invalid_source_catalog", "Every document field is required.")
        for field in (
            "document_id",
            "document_family_id",
            "edition_id",
            "title",
            "publisher",
            "status",
            "distribution_statement",
            "source_origin",
        ):
            _required_string(document.get(field), field)
        require(
            document["document_id"] not in seen_document_ids,
            "invalid_source_catalog",
            "Document IDs must be unique.",
            document_id=document["document_id"],
        )
        require(
            document["edition_id"] not in seen_edition_ids,
            "invalid_source_catalog",
            "Edition IDs must be unique.",
            edition_id=document["edition_id"],
        )
        revision = document.get("revision")
        require(revision is None or (isinstance(revision, str) and bool(revision)), "invalid_source_catalog", "revision must be a non-empty string or null.")
        require(type(document.get("change")) is int and document["change"] >= 0, "invalid_source_catalog", "change must be a non-negative integer.")
        _iso_date(document.get("document_date"), "document_date")
        _iso_date(document.get("retrieved_at"), "retrieved_at")

        parsed = urlparse(_required_string(document.get("detail_url"), "detail_url"))
        query = parse_qs(parsed.query)
        identifiers = query.get("ident_number", [])
        require(
            parsed.scheme == "https"
            and parsed.netloc == "quicksearch.dla.mil"
            and parsed.path == "/qsDocDetails.aspx"
            and len(query) == 1
            and len(identifiers) == 1
            and identifiers[0].isdigit()
            and not parsed.fragment,
            "invalid_source_catalog",
            "detail_url must be a stable DLA Quick Search HTTPS URL.",
        )
        require(
            document["source_origin"] == "official_dla_assist_quick_search",
            "invalid_source_catalog",
            "Unsupported source origin.",
        )

        filename = _safe_pdf_filename(document.get("local_filename"))
        require(filename not in seen_filenames, "invalid_source_catalog", "Source filenames must be unique.", path=filename)
        digest = document.get("sha256")
        require(isinstance(digest, str) and bool(_SHA256.fullmatch(digest)), "invalid_source_catalog", "sha256 must be a lowercase SHA-256 digest.", path=filename)
        require(type(document.get("byte_length")) is int and document["byte_length"] > 0, "invalid_source_catalog", "byte_length must be a positive integer.", path=filename)
        require(type(document.get("page_count")) is int and document["page_count"] > 0, "invalid_source_catalog", "page_count must be a positive integer.", path=filename)

        rights = _strict_object(document.get("rights"), _RIGHTS_KEYS, "source catalog rights")
        require(set(rights) == _RIGHTS_KEYS, "invalid_source_catalog", "Every rights field is required.")
        _required_string(rights.get("access_basis"), "rights.access_basis")
        require(
            rights.get("repository_redistribution") == "not_asserted",
            "invalid_source_catalog",
            "The seed catalog must not assert repository redistribution permission.",
        )

        seen_document_ids.add(document["document_id"])
        seen_edition_ids.add(document["edition_id"])
        seen_filenames.add(filename)
    return catalog


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source_set(catalog_path: str | Path, source_root: str | Path) -> dict[str, Any]:
    catalog = load_source_catalog(catalog_path)
    root_input = Path(source_root)
    require(not root_input.is_symlink(), "invalid_source_path", "The source root cannot be a symbolic link.")
    require(root_input.is_dir(), "source_root_not_found", "The source root directory does not exist.")
    root = root_input.resolve()

    expected_names = {document["local_filename"] for document in catalog["documents"]}
    actual_names = {path.name for path in root.iterdir()}
    require(
        actual_names == expected_names,
        "source_set_mismatch",
        "The source directory must contain exactly the cataloged files.",
        missing=sorted(expected_names - actual_names),
        unexpected=sorted(actual_names - expected_names),
    )

    verified: list[dict[str, Any]] = []
    total_bytes = 0
    for document in catalog["documents"]:
        filename = document["local_filename"]
        path = root / filename
        require(not path.is_symlink(), "invalid_source_path", "Catalog source files cannot be symbolic links.", path=filename)
        require(path.is_file(), "source_file_missing", "A catalog source file is missing.", path=filename)
        size = path.stat().st_size
        require(size == document["byte_length"], "source_size_mismatch", "A catalog source byte count does not match.", path=filename, expected=document["byte_length"], actual=size)
        try:
            with path.open("rb") as stream:
                signature = stream.read(5)
        except OSError as exc:
            raise StandardsForgeError("source_read_failed", "A catalog source file could not be read.", {"path": filename}) from exc
        require(signature == b"%PDF-", "invalid_source_format", "A catalog source does not have a PDF signature.", path=filename)
        actual_hash = _file_sha256(path)
        require(actual_hash == document["sha256"], "source_hash_mismatch", "A catalog source digest does not match.", path=filename, expected=document["sha256"], actual=actual_hash)
        total_bytes += size
        verified.append(
            {
                "document_id": document["document_id"],
                "edition_id": document["edition_id"],
                "local_filename": filename,
                "sha256": actual_hash,
                "byte_length": size,
                "declared_page_count": document["page_count"],
                "verified_dimensions": ["directory_closure", "regular_file", "pdf_signature", "byte_length", "sha256"],
            }
        )
    return {
        "catalog_id": catalog["catalog_id"],
        "document_count": len(verified),
        "total_bytes": total_bytes,
        "documents": verified,
        "network_access": "not_used",
        "page_count": "declared_metadata_not_recomputed",
    }
