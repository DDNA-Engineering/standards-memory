from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from .errors import StandardsMemoryError, require
from .identity import normalize_identifier
from .models import InventoryEntry, ValidatedPack


MAX_FILES = 512
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
ALLOWED_SUFFIXES = {".json", ".txt", ".md"}
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
}
_SOURCE_KEYS = {"path", "sha256", "page", "locator", "quote_sha256"}
_DEPENDENCY_KEYS = {"relationship", "target_record_id", "required"}
_DERIVATION_KEYS = {"statement_role", "method", "review_status"}
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
    except StandardsMemoryError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsMemoryError("invalid_pack_json", "A required pack JSON file is invalid.", {"path": path.name}) from exc


def _strict_object(value: Any, allowed: set[str], code: str, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), code, f"{label} must be a JSON object.")
    unknown = sorted(set(value) - allowed)
    require(not unknown, code, f"{label} has unknown fields.", fields=unknown)
    return value


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
        data = disk_path.read_bytes()
        require(len(data) == expected_size, "pack_size_mismatch", "An inventoried byte count does not match.", path=rel_text)
        require(_sha256(data) == expected_hash, "pack_hash_mismatch", "An inventoried digest does not match.", path=rel_text)
        total += len(data)
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
        raise StandardsMemoryError("invalid_manifest", "publication_date must be an ISO calendar date.") from exc
    require(manifest["inventory_path"] == "inventory.json", "invalid_manifest", "The inventory path must be inventory.json.")
    require(manifest["rights_path"] == "rights.json", "invalid_manifest", "The rights path must be rights.json.")
    require(manifest["records_path"] == "records.json", "invalid_manifest", "The records path must be records.json.")
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
    require(raw_records.get("schema_version") == "0.1.0", "unsupported_schema_version", "Unsupported records schema.")
    require(isinstance(raw_records.get("records"), list) and raw_records["records"], "invalid_records", "At least one record is required.")

    inventory_by_path = {entry.path: entry for entry in inventory}
    records: list[dict[str, Any]] = []
    record_ids: set[str] = set()
    for record in raw_records["records"]:
        record = _strict_object(record, _RECORD_KEYS, "invalid_record", "record")
        for key in ("record_id", "edition_id", "kind", "clause_reference", "heading", "text"):
            require(isinstance(record.get(key), str) and bool(record[key]), "invalid_record", f"{key} is required.")
        require(record["edition_id"] == manifest["edition_id"], "edition_mismatch", "A record belongs to a different edition.", record_id=record["record_id"])
        require(record["kind"] in {"clause", "note"}, "invalid_record", "Unsupported record kind.", record_id=record["record_id"])
        require(record["record_id"] not in record_ids, "invalid_record", "Record IDs must be unique.", record_id=record["record_id"])
        record_ids.add(record["record_id"])

        source = _strict_object(record.get("source"), _SOURCE_KEYS, "invalid_record", "record source")
        require(set(source) == _SOURCE_KEYS, "invalid_record", "Every source locator field is required.")
        rel = _safe_relative_path(source["path"]).as_posix()
        require(rel.startswith("sources/"), "invalid_record", "Record sources must be under sources/.", record_id=record["record_id"])
        require(rel in inventory_by_path, "invalid_record", "The record source is not inventoried.", record_id=record["record_id"])
        require(source["sha256"] == inventory_by_path[rel].sha256, "invalid_record", "The record source digest does not match the inventory.", record_id=record["record_id"])
        require(type(source["page"]) is int and source["page"] >= 1, "invalid_record", "Source page must be a positive integer.")
        require(isinstance(source["locator"], str) and source["locator"], "invalid_record", "Source locator is required.")
        require(source["quote_sha256"] == _sha256(record["text"].encode("utf-8")), "invalid_record", "Quote digest does not match exact record text.", record_id=record["record_id"])
        source_text = (pack_root / Path(rel)).read_text(encoding="utf-8")
        require(record["text"] in source_text, "source_quote_missing", "Exact record text is absent from its source.", record_id=record["record_id"])

        derivation = _strict_object(record.get("derivation"), _DERIVATION_KEYS, "invalid_record", "record derivation")
        require(set(derivation) == _DERIVATION_KEYS, "invalid_record", "Every derivation field is required.")
        require(
            derivation["statement_role"] in {"obligation", "governing_note", "informative"},
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


@contextmanager
def open_validated_pack(source: str | Path) -> Iterator[ValidatedPack]:
    source_path = Path(source).resolve()
    if source_path.is_dir():
        yield validate_pack_directory(source_path)
        return
    require(source_path.is_file() and source_path.suffix.lower() == ".zip", "pack_not_found", "Pack source must be a directory or .zip file.")

    with tempfile.TemporaryDirectory(prefix="standards-memory-pack-") as temp:
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
            raise StandardsMemoryError("invalid_pack_archive", "The pack archive is invalid.") from exc
        yield validate_pack_directory(target)
