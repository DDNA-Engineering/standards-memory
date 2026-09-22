from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .compiler import PYPDF_VERSION, _write_json
from .errors import StandardsForgeError, require
from .outline_review import (
    _DECISION_KEYS, _DRAFT_KEYS, _REVIEW_NODE_KEYS, _export_outline_review_draft,
    _read_closed_json, _validate_reviewed_node, _write_new_json,
)
from .pack import open_validated_pack


MAX_SHARD_CANDIDATES = 256
MAX_SHARD_REVIEW_BYTES = 32 * 1024 * 1024
_SHARD_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_selection(path: str | Path) -> dict[str, Any]:
    try:
        with Path(path).open("rb") as source:
            raw = source.read(128 * 1024 + 1)
        require(len(raw) <= 128 * 1024, "invalid_review_shard", "A shard selection is too large.")
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_review_shard", "The shard selection is not valid UTF-8 JSON.") from exc
    require(isinstance(value, dict) and set(value) == {"schema_version", "shard_id", "record_ids"}, "invalid_review_shard", "Shard selection fields are invalid.")
    require(value["schema_version"] == "0.1.0", "unsupported_schema_version", "Unsupported shard selection version.")
    require(isinstance(value["shard_id"], str) and _SHARD_ID.fullmatch(value["shard_id"]), "invalid_review_shard", "Use a short lowercase shard ID without paths.")
    ids = value["record_ids"]
    require(isinstance(ids, list) and 1 <= len(ids) <= MAX_SHARD_CANDIDATES and all(isinstance(item, str) and item for item in ids) and len(ids) == len(set(ids)), "invalid_review_shard", "Select one to 256 unique exact candidate record IDs.")
    return value


def export_outline_review_shard(
    outline_pack: str | Path,
    source_page_pack: str | Path,
    selection_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Export a deterministic partial review bundle without promoting any candidate."""

    selection = _read_selection(selection_path)
    output = Path(output_directory).resolve()
    require(not output.exists(), "compiler_output_exists", "The review shard output already exists.", path=str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with open_validated_pack(source_page_pack) as base, open_validated_pack(outline_pack) as outline:
        outline_candidate_count = sum(record["kind"] not in {"page", "unsupported_region"} for record in outline.records)
        unsupported_region_count = sum(record["kind"] == "unsupported_region" for record in outline.records)
        with tempfile.TemporaryDirectory(prefix=".standardsforge-shard-", dir=output.parent) as temporary:
            staging = Path(temporary)
            drafts = staging / "drafts"
            drafts.mkdir()
            candidates = []
            source_pdf_hashes: set[str] = set()
            source_pdf_paths: set[str] = set()
            for record_id in sorted(selection["record_ids"]):
                relative = f"drafts/{_sha256(record_id.encode('utf-8'))}.json"
                draft_path = staging / relative
                exported = _export_outline_review_draft(
                    outline_pack, source_page_pack, record_id, draft_path,
                    validated_base=base, validated_outline=outline,
                )
                draft = json.loads(draft_path.read_text(encoding="utf-8"))
                source_pdf_hashes.add(draft["source_pdf_sha256"])
                source_pdf_paths.add(draft["source_pdf_path"])
                candidates.append({
                    "candidate_record_id": record_id,
                    "candidate_logical_id": draft["proposed_node"]["logical_id"],
                    "candidate_content_sha256": draft["candidate_content_sha256"],
                    "draft_sha256": exported["draft_sha256"],
                    "draft_path": relative,
                })
            require(len(source_pdf_hashes) == len(source_pdf_paths) == 1, "invalid_review_shard", "A review shard must select one exact source component.")
            manifest = {
                "schema_version": "0.1.0",
                "state": "proposed_unreviewed",
                "shard_id": selection["shard_id"],
                "source_page_pack_digest": base.package_digest,
                "outline_package_digest": outline.package_digest,
                "edition_id": base.manifest["edition_id"],
                "document_id": base.manifest["identifier"],
                "source_pdf_sha256": next(iter(source_pdf_hashes)),
                "source_pdf_path": next(iter(source_pdf_paths)),
                "candidate_count": len(candidates),
                "outline_candidate_count": outline_candidate_count,
                "unselected_candidate_count": outline_candidate_count - len(candidates),
                "unsupported_region_count": unsupported_region_count,
                "candidates": candidates,
                "coverage": "explicit_selected_candidates_only_not_document_complete",
            }
            _write_json(staging / "manifest.json", manifest)
            require(not output.exists(), "compiler_output_exists", "The review shard output already exists.", path=str(output))
            os.replace(staging, output)
    return {
        "operation": "export_outline_review_shard",
        "status": "proposed_unreviewed",
        "shard_id": selection["shard_id"],
        "candidate_count": len(candidates),
        "manifest_sha256": _sha256((output / "manifest.json").read_bytes()),
        "output_directory": str(output),
        "coverage": "explicit_selected_candidates_only_not_document_complete",
    }


def merge_outline_review_shard(
    shard_directory: str | Path,
    decisions_directory: str | Path,
    outline_pack: str | Path,
    source_page_pack: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Replay every selected proposal and bind one explicit review per node."""

    shard = Path(shard_directory).resolve()
    decisions = Path(decisions_directory).resolve()
    output = Path(output_path).resolve()
    require(not output.exists(), "compiler_output_exists", "The reviewed annotation output already exists.")
    require(shard.is_dir() and decisions.is_dir() and (shard / "drafts").is_dir(), "invalid_review_shard", "The shard and decision directories are required.")
    manifest_path = shard / "manifest.json"
    require(not manifest_path.is_symlink() and not (shard / "drafts").is_symlink(), "invalid_review_shard", "Review shard inputs cannot be symbolic links.")
    manifest_keys = {
        "schema_version", "state", "shard_id", "source_page_pack_digest",
        "outline_package_digest", "edition_id", "document_id", "source_pdf_sha256",
        "source_pdf_path", "candidate_count", "outline_candidate_count",
        "unselected_candidate_count", "unsupported_region_count", "candidates", "coverage",
    }
    manifest = _read_closed_json(manifest_path, manifest_keys, "Review shard manifest")
    require(
        manifest["schema_version"] == "0.1.0"
        and manifest["state"] == "proposed_unreviewed"
        and manifest["coverage"] == "explicit_selected_candidates_only_not_document_complete"
        and isinstance(manifest["shard_id"], str)
        and _SHARD_ID.fullmatch(manifest["shard_id"]),
        "invalid_review_shard", "Unsupported review shard identity or state.",
    )
    entries = manifest["candidates"]
    require(
        isinstance(entries, list) and 1 <= len(entries) <= MAX_SHARD_CANDIDATES
        and type(manifest["candidate_count"]) is int and manifest["candidate_count"] == len(entries),
        "invalid_review_shard", "Review shard candidate count is invalid.",
    )
    expected_drafts: set[str] = set()
    expected_decisions: set[str] = set()
    nodes: list[dict[str, Any]] = []
    input_bytes = len(manifest_path.read_bytes())
    with open_validated_pack(source_page_pack) as base, open_validated_pack(outline_pack) as outline:
        require(
            manifest["source_page_pack_digest"] == base.package_digest
            and manifest["outline_package_digest"] == outline.package_digest
            and manifest["edition_id"] == base.manifest["edition_id"]
            and manifest["document_id"] == base.manifest["identifier"],
            "outline_review_stale", "The review shard binds different source packages.",
        )
        outline_candidate_count = sum(record["kind"] not in {"page", "unsupported_region"} for record in outline.records)
        require(
            type(manifest["outline_candidate_count"]) is int
            and type(manifest["unselected_candidate_count"]) is int
            and type(manifest["unsupported_region_count"]) is int
            and manifest["outline_candidate_count"] == outline_candidate_count
            and manifest["unselected_candidate_count"] == outline_candidate_count - len(entries)
            and manifest["unsupported_region_count"] == sum(record["kind"] == "unsupported_region" for record in outline.records),
            "outline_review_stale", "The shard selection summary differs from the exact outline.",
        )
        with tempfile.TemporaryDirectory(prefix="standardsforge-shard-replay-") as temporary:
            prior_record_id = ""
            for entry in entries:
                require(
                    isinstance(entry, dict)
                    and set(entry) == {"candidate_record_id", "candidate_logical_id", "candidate_content_sha256", "draft_sha256", "draft_path"},
                    "invalid_review_shard", "A shard candidate entry is invalid.",
                )
                record_id = entry["candidate_record_id"]
                require(isinstance(record_id, str) and record_id > prior_record_id, "invalid_review_shard", "Shard candidate IDs must be unique and sorted.")
                prior_record_id = record_id
                stem = _sha256(record_id.encode("utf-8"))
                relative = f"drafts/{stem}.json"
                require(entry["draft_path"] == relative, "invalid_review_shard", "A shard draft path is invalid.")
                expected_drafts.add(f"{stem}.json")
                expected_decisions.add(f"{stem}.json")
                draft_path = shard / relative
                decision_path = decisions / f"{stem}.json"
                require(not draft_path.is_symlink() and not decision_path.is_symlink(), "invalid_review_shard", "Review shard inputs cannot be symbolic links.")
                try:
                    input_bytes += draft_path.stat().st_size + decision_path.stat().st_size
                except OSError as exc:
                    raise StandardsForgeError("invalid_review_shard", "A selected draft or decision is missing.") from exc
                require(input_bytes <= MAX_SHARD_REVIEW_BYTES, "invalid_review_shard", "The shard review inputs exceed the aggregate size limit.")
                draft = _read_closed_json(draft_path, _DRAFT_KEYS, "Review shard draft")
                replay_path = Path(temporary) / f"{stem}.json"
                _export_outline_review_draft(
                    outline_pack, source_page_pack, record_id, replay_path,
                    validated_base=base, validated_outline=outline,
                )
                draft_bytes = draft_path.read_bytes()
                require(draft_bytes == replay_path.read_bytes(), "outline_review_stale", "The shard draft no longer matches its source candidate.")
                draft_digest = _sha256(draft_bytes)
                require(
                    entry["draft_sha256"] == draft_digest
                    and entry["candidate_logical_id"] == draft["proposed_node"]["logical_id"]
                    and entry["candidate_content_sha256"] == draft["candidate_content_sha256"]
                    and manifest["source_pdf_sha256"] == draft["source_pdf_sha256"]
                    and manifest["source_pdf_path"] == draft["source_pdf_path"],
                    "outline_review_stale", "The shard manifest disagrees with an exact candidate proposal.",
                )
                decision = _read_closed_json(decision_path, _DECISION_KEYS, "Review shard decision")
                require(
                    decision["schema_version"] == "0.1.0"
                    and decision["draft_sha256"] == draft_digest
                    and isinstance(decision["review"], dict),
                    "outline_review_stale", "A review decision does not bind its exact draft.",
                )
                node = decision["node"]
                require(
                    isinstance(node, dict) and set(node) <= _REVIEW_NODE_KEYS
                    and node.get("logical_id") == draft["proposed_node"]["logical_id"],
                    "outline_review_stale", "A review decision changed its candidate logical identity.",
                )
                _validate_reviewed_node(base, draft, node)
                nodes.append({
                    **node,
                    "candidate_record_id": record_id,
                    "candidate_content_sha256": draft["candidate_content_sha256"],
                    "proposal_sha256": draft_digest,
                    "decision_sha256": _sha256(decision_path.read_bytes()),
                    "review": decision["review"],
                })
    require(
        shard.is_dir() and {item.name for item in shard.iterdir()} == {"manifest.json", "drafts"}
        and (shard / "drafts").is_dir()
        and {item.name for item in (shard / "drafts").iterdir() if item.is_file()} == expected_drafts
        and all(item.is_file() for item in (shard / "drafts").iterdir())
        and decisions.is_dir()
        and {item.name for item in decisions.iterdir() if item.is_file()} == expected_decisions
        and all(item.is_file() for item in decisions.iterdir()),
        "invalid_review_shard", "Shard drafts and review decisions must match the selected candidate set exactly.",
    )
    annotations = {
        "schema_version": "0.5.0",
        "document_id": manifest["document_id"],
        "edition_id": manifest["edition_id"],
        "source_pdf_sha256": manifest["source_pdf_sha256"],
        "source_page_pack_digest": manifest["source_page_pack_digest"],
        "outline_package_digest": manifest["outline_package_digest"],
        "shard_id": manifest["shard_id"],
        "shard_manifest_sha256": _sha256(manifest_path.read_bytes()),
        "review_mode": "per_node",
        "compiler": {"name": "pypdf", "version": PYPDF_VERSION},
        "extraction_mode": "layout_rotated_included",
        "text_encoding": "UTF-8",
        "offset_convention": "half_open_utf8_byte_offsets_per_physical_page",
        "nodes": nodes,
        "relationships": [],
        "unsupported_regions": [],
    }
    _write_new_json(output, annotations, validate_reviewed=True)
    return {
        "operation": "merge_outline_review_shard",
        "status": "reviewed_annotation_written",
        "shard_id": manifest["shard_id"],
        "node_count": len(nodes),
        "annotation_sha256": _sha256(output.read_bytes()),
        "output_path": str(output),
        "coverage": manifest["coverage"],
    }
