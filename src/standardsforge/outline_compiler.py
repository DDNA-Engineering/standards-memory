from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import StandardsForgeError, require
from .pack import open_validated_pack, validate_pack_directory


OUTLINE_COMPILER_VERSION = "0.2.0"
_METHOD = re.compile(
    r"(?mi)^[^\S\r\n]*(?P<label>M\s*E\s*T\s*H\s*O\s*D\s+(?P<method_number>\d+(?:\.\d+)*))[^\S\r\n]*(?:\r?\n|$)"
)
_APPENDIX = re.compile(r"(?mi)^[^\S\r\n]*(?P<label>APPENDIX\s+[A-Z])[^\S\r\n]*(?:\r?\n|$)")
_NUMBERED = re.compile(
    r"(?m)^[^\S\r\n]*(?P<label>(?:[A-Z]\.)?\d+(?:\.\d+){0,7})[ \t]{2,}(?P<body>\S[^\r\n]*)"
)
_LIST_ITEM = re.compile(r"(?m)^[^\S\r\n]+(?P<label>[a-z])\.[ \t]+(?P<body>\S[^\r\n]*)")
_NOTE = re.compile(r"(?mi)^[^\S\r\n]*(?P<label>NOTE(?:\s+\d+)?)[.:]?[ \t]+(?P<body>\S[^\r\n]*)")
_CAPTION_DESIGNATOR = r"(?:\d+(?:\.\d+)*(?:[A-Z])?(?:[ \t]*-[ \t]*(?:[IVXLCDM]+|\d+[A-Z]?))?|[IVXLCDM]+|[A-Z])"
_CAPTION = re.compile(
    rf"(?mi)^[^\S\r\n]*(?P<label>(?:TABLE|FIGURE)[ \t]+{_CAPTION_DESIGNATOR})(?:[.:][ \t]+|[ \t]{{2,}})(?P<body>\S[^\r\n]*)"
)
_TOC_LEADERS = re.compile(r"\.{3,}|…{2,}")
_NUMERIC_TOKEN = re.compile(r"^[+\-±<>~]?[([]?\d")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_json_bytes(value))


def _inventory_entry(root: Path, relative: str) -> dict[str, Any]:
    path = root.joinpath(*PurePosixPath(relative).parts)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": relative, "sha256": digest, "bytes": path.stat().st_size}


def _activate(staging: Path, output: Path) -> None:
    for attempt in range(6):
        try:
            os.replace(staging, output)
            return
        except PermissionError as exc:
            require(
                not output.exists(),
                "compiler_output_exists",
                "The derived-outline output appeared during activation.",
                path=str(output),
            )
            if attempt == 5:
                raise StandardsForgeError(
                    "compiler_output_activation_failed",
                    "The derived-outline pack could not be activated after bounded retries.",
                    {"path": str(output)},
                ) from exc
            time.sleep(0.05 * (2**attempt))


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _heading(body: str | None, label: str) -> str:
    if not body:
        return label.strip()
    normalized = " ".join(body.split())
    sentence = re.match(r"^(.{1,180}?)[.]\s+", normalized)
    if sentence:
        normalized = sentence.group(1)
    return normalized[:240].rstrip(" .") or label.strip()


def _looks_like_table_row(body: str) -> bool:
    tokens = body.split()
    if not tokens:
        return False
    numeric_tokens = sum(1 for token in tokens[:24] if _NUMERIC_TOKEN.match(token))
    starts_numeric = bool(_NUMERIC_TOKEN.match(tokens[0]))
    return numeric_tokens >= 4 or (starts_numeric and numeric_tokens >= 2)


def _candidate_matches(text: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    patterns = (
        (0, "method", _METHOD),
        (0, "appendix", _APPENDIX),
        (1, "numbered", _NUMBERED),
        (2, "note", _NOTE),
        (3, "caption", _CAPTION),
        (4, "list_item", _LIST_ITEM),
    )
    for priority, match_type, pattern in patterns:
        for match in pattern.finditer(text):
            candidate_type = match_type
            body = match.groupdict().get("body")
            if candidate_type in {"numbered", "caption"} and body:
                if _TOC_LEADERS.search(body):
                    if candidate_type == "numbered":
                        continue
                    candidate_type = "toc_caption"
                if candidate_type == "numbered" and _looks_like_table_row(body):
                    candidate_type = "ambiguous_numbered"
            label_start = match.start("label")
            label = match.group("label").strip()
            if candidate_type == "method":
                label = f"METHOD {match.group('method_number')}"
            matches.append(
                {
                    "start": label_start,
                    "line_end": match.end(),
                    "priority": priority,
                    "type": candidate_type,
                    "label": label,
                    "body": body,
                }
            )
    selected: list[dict[str, Any]] = []
    occupied: set[int] = set()
    for candidate in sorted(matches, key=lambda item: (item["start"], item["priority"], -item["line_end"])):
        line_key = text.count("\n", 0, candidate["start"])
        if line_key in occupied:
            continue
        occupied.add(line_key)
        selected.append(candidate)
    selected.sort(key=lambda item: item["start"])
    pending_table_footnotes: list[dict[str, Any]] = []
    after_table_caption = False
    for candidate in [*selected, {"type": "boundary"}]:
        if candidate["type"] == "caption" and candidate["label"].upper().startswith("TABLE"):
            if len(pending_table_footnotes) >= 2:
                for footnote in pending_table_footnotes:
                    footnote["type"] = "ambiguous_numbered"
            pending_table_footnotes = []
            after_table_caption = True
            continue
        if after_table_caption and candidate["type"] == "numbered" and "." not in candidate["label"]:
            pending_table_footnotes.append(candidate)
            continue
        if after_table_caption and candidate["type"] in {"ambiguous_numbered", "list_item", "note"}:
            continue
        if len(pending_table_footnotes) >= 2:
            for footnote in pending_table_footnotes:
                footnote["type"] = "ambiguous_numbered"
        pending_table_footnotes = []
        after_table_caption = False
    return selected


def _byte_offset(text: str, character_offset: int) -> int:
    return len(text[:character_offset].encode("utf-8"))


def _component_context(record: dict[str, Any]) -> str:
    source_name = PurePosixPath(record["source"]["path"]).stem
    return re.sub(r"[^a-z0-9.-]+", "-", source_name.lower()).strip("-") or "component"


def _logical_suffix(value: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "-", value.lower()).strip("-") or "node"


def _copy_source(pack_root: Path, staging: Path, relative: str) -> None:
    source = pack_root.joinpath(*PurePosixPath(relative).parts)
    target = staging.joinpath(*PurePosixPath(relative).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def compile_derived_outline_pack(source_pack: str | Path, output_directory: str | Path) -> dict[str, Any]:
    """Compile deterministic, unreviewed outline candidates from a verified page-text pack."""

    output = Path(output_directory).resolve()
    require(not output.exists(), "compiler_output_exists", "The derived-outline output already exists.", path=str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".standardsforge-outline-", dir=output.parent))
    try:
        with open_validated_pack(source_pack) as base:
            require(
                base.manifest.get("representation") == "page_text",
                "outline_source_not_page_text",
                "Derived-outline compilation requires a verified page_text pack.",
            )
            page_records = list(base.records)
            require(
                page_records and all(record.get("kind") == "page" for record in page_records),
                "outline_source_not_page_text",
                "Derived-outline compilation accepts only page records.",
            )
            page_records.sort(key=lambda record: (record["source"]["path"], record["source"]["page"], record["record_id"]))

            source_paths = sorted(
                {
                    relative
                    for record in page_records
                    for relative in (record["source"]["path"], record["source"].get("text_path"))
                    if relative
                }
            )
            for relative in source_paths:
                _copy_source(base.root, staging, relative)

            method = f"standardsforge-deterministic-outline/{OUTLINE_COMPILER_VERSION}"
            derived_records: list[dict[str, Any]] = []
            node_by_scoped_reference: dict[tuple[str, str, str], str] = {}
            occurrence_by_scope: dict[tuple[str, str, str], int] = {}
            current_context_by_component: dict[str, str] = {}
            current_parent_by_component: dict[str, str | None] = {}
            unsupported_pages = 0
            unsupported_regions = 0
            detected = {key: 0 for key in ("method", "appendix", "section", "clause", "list_item", "note", "table", "figure")}

            def add_record(
                page_record: dict[str, Any],
                *,
                start: int,
                end: int,
                kind: str,
                local_reference: str,
                heading: str,
                parent_logical_id: str | None,
                ordinal: int,
                context: str,
            ) -> str:
                text = page_record["text"]
                exact_text = text[start:end]
                source = page_record["source"]
                require(
                    "text_start_byte" in source and "text_end_byte" in source,
                    "outline_source_not_offset_backed",
                    "Derived-outline compilation requires offset-backed page evidence.",
                    record_id=page_record["record_id"],
                )
                component = _component_context(page_record)
                scope_key = (component, context, local_reference)
                occurrence = occurrence_by_scope.get(scope_key, 0) + 1
                occurrence_by_scope[scope_key] = occurrence
                identity_reference = local_reference if occurrence == 1 else f"{local_reference}:occurrence-{occurrence}"
                logical_id = (
                    f"{base.manifest['edition_id']}:derived-outline:{component}:"
                    f"{_logical_suffix(context)}:{_logical_suffix(identity_reference)}"
                )
                record_id = f"outline-{hashlib.sha256(logical_id.encode('utf-8')).hexdigest()[:24]}"
                local_start = _byte_offset(text, start)
                local_end = _byte_offset(text, end)
                global_start = source["text_start_byte"] + local_start
                global_end = source["text_start_byte"] + local_end
                quote_sha256 = _sha256(exact_text.encode("utf-8"))
                span = {
                    "path": source["path"],
                    "sha256": source["sha256"],
                    "text_path": source["text_path"],
                    "text_sha256": source["text_sha256"],
                    "physical_page": source["page"],
                    "start_byte": global_start,
                    "end_byte": global_end,
                    "quote_sha256": quote_sha256,
                }
                clause_reference = f"derived:{component}:{context}:{identity_reference}"
                derived_records.append(
                    {
                        "record_id": record_id,
                        "edition_id": base.manifest["edition_id"],
                        "kind": kind,
                        "clause_reference": clause_reference,
                        "heading": heading,
                        "text": exact_text,
                        "source": {
                            "path": source["path"],
                            "sha256": source["sha256"],
                            "text_path": source["text_path"],
                            "text_sha256": source["text_sha256"],
                            "page": source["page"],
                            "locator": f"physical PDF page {source['page']}; UTF-8 bytes {global_start}:{global_end}",
                            "quote_sha256": quote_sha256,
                        },
                        "derivation": {
                            "statement_role": "unclassified",
                            "method": method,
                            "review_status": "automated_unreviewed",
                        },
                        "dependencies": [],
                        "structure": {
                            "logical_id": logical_id,
                            "content_sha256": quote_sha256,
                            "parent_logical_id": parent_logical_id,
                            "ordinal": ordinal,
                            "source_spans": [span],
                            "relationships": [],
                        },
                    }
                )
                node_by_scoped_reference[scope_key] = logical_id
                return logical_id

            for page_record in page_records:
                text = page_record["text"]
                component = _component_context(page_record)
                context = current_context_by_component.get(component, "document")
                current_parent = current_parent_by_component.get(component)
                candidates = _candidate_matches(text)
                if not candidates:
                    span = _trimmed_span(text, 0, len(text))
                    if span is not None:
                        add_record(
                            page_record,
                            start=span[0],
                            end=span[1],
                            kind="unsupported_region",
                            local_reference=f"page-{page_record['source']['page']:04d}-unparsed",
                            heading="Unparsed page text",
                            parent_logical_id=None,
                            ordinal=page_record["source"]["page"],
                            context=context,
                        )
                        unsupported_regions += 1
                    unsupported_pages += 1
                    continue

                prefix = _trimmed_span(text, 0, candidates[0]["start"])
                if prefix is not None:
                    add_record(
                        page_record,
                        start=prefix[0],
                        end=prefix[1],
                        kind="unsupported_region",
                        local_reference=f"page-{page_record['source']['page']:04d}-prefix",
                        heading="Unparsed page prefix",
                        parent_logical_id=None,
                        ordinal=0,
                        context=context,
                    )
                    unsupported_regions += 1

                for index, candidate in enumerate(candidates):
                    end = candidates[index + 1]["start"] if index + 1 < len(candidates) else len(text)
                    span = _trimmed_span(text, candidate["start"], end)
                    if span is None:
                        continue
                    match_type = candidate["type"]
                    label = candidate["label"]
                    body = candidate["body"]
                    kind = "clause"
                    parent = current_parent
                    local_reference = label
                    if match_type == "method":
                        next_context = label.upper().replace(" ", "-")
                        if next_context == context:
                            kind = "unsupported_region"
                            local_reference = f"page-{page_record['source']['page']:04d}-repeated-method-header"
                            parent = None
                            unsupported_regions += 1
                        else:
                            context = next_context
                            current_context_by_component[component] = context
                            kind = "section"
                            parent = None
                            detected["method"] += 1
                    elif match_type == "appendix":
                        context = label.upper().replace(" ", "-")
                        current_context_by_component[component] = context
                        kind = "section"
                        parent = None
                        detected["appendix"] += 1
                    elif match_type == "ambiguous_numbered":
                        kind = "unsupported_region"
                        local_reference = f"page-{page_record['source']['page']:04d}-ambiguous-numbered-{index + 1}"
                        parent = None
                        unsupported_regions += 1
                    elif match_type == "toc_caption":
                        kind = "unsupported_region"
                        local_reference = f"page-{page_record['source']['page']:04d}-toc-caption-{index + 1}"
                        parent = None
                        unsupported_regions += 1
                    elif match_type == "numbered":
                        parts = label.split(".")
                        parent_reference = ".".join(parts[:-1])
                        parent = node_by_scoped_reference.get((component, context, parent_reference)) if parent_reference else current_parent
                        kind = "section" if len(parts) == 1 else "clause"
                        detected[kind] += 1
                    elif match_type == "list_item":
                        kind = "list_item"
                        local_reference = f"{label.lower()}-item"
                        detected[kind] += 1
                    elif match_type == "note":
                        kind = "note"
                        local_reference = label.upper().replace(" ", "-")
                        detected[kind] += 1
                    elif match_type == "caption":
                        is_table = label.upper().startswith("TABLE")
                        kind = "table" if is_table else "figure"
                        normalized_label = re.sub(r"\s*([.-])\s*", r"\1", label.upper())
                        local_reference = re.sub(r"\s+", "-", normalized_label)
                        detected[kind] += 1
                    logical_id = add_record(
                        page_record,
                        start=span[0],
                        end=span[1],
                        kind=kind,
                        local_reference=local_reference,
                        heading=_heading(body, label),
                        parent_logical_id=parent,
                        ordinal=index + 1,
                        context=context,
                    )
                    if match_type in {"appendix", "numbered"} or match_type == "method" and kind == "section":
                        current_parent = logical_id
                        current_parent_by_component[component] = logical_id

            require(derived_records, "outline_no_records", "The page-text pack produced no derived outline records.")
            base_descriptor = {
                "schema_version": "0.1.0",
                "base_package_digest": base.package_digest,
                "base_pack_id": base.manifest["pack_id"],
                "base_edition_id": base.manifest["edition_id"],
                "base_representation": base.manifest["representation"],
                "base_coverage": base.manifest["coverage"],
            }
            report = {
                "schema_version": "0.1.0",
                "compiler": {
                    "name": "standardsforge-deterministic-outline",
                    "version": OUTLINE_COMPILER_VERSION,
                    "network": "not_used",
                    "model": "not_used",
                },
                "base_package_digest": base.package_digest,
                "page_record_count": len(page_records),
                "derived_record_count": len(derived_records),
                "unsupported_page_count": unsupported_pages,
                "unsupported_region_count": unsupported_regions,
                "detected_kinds": detected,
                "classification": "all_records_unclassified_automated_unreviewed",
                "limitations": {
                    "semantic_correctness": "not_reviewed",
                    "obligations": "not_classified",
                    "tables": "captions_only_cells_not_interpreted",
                    "figures": "captions_only_visuals_not_interpreted",
                    "cross_page_continuity": "not_inferred",
                    "references": "not_resolved",
                },
            }
            manifest = {
                "schema_version": "0.1.0",
                "pack_id": f"derived.{base.manifest['pack_id']}.outline-v2",
                "document_family_id": base.manifest["document_family_id"],
                "edition_id": base.manifest["edition_id"],
                "publisher": base.manifest["publisher"],
                "identifier": base.manifest["identifier"],
                "title": base.manifest["title"],
                "revision": base.manifest["revision"],
                "publication_date": base.manifest["publication_date"],
                "category": "automated_derived_outline_candidate",
                "representation": "derived_structure",
                "inventory_path": "inventory.json",
                "rights_path": "rights.json",
                "records_path": "records.json",
                "coverage": {
                    "corpus_scope": "one_verified_page_text_pack",
                    "edition_composition": base.manifest["coverage"]["edition_composition"],
                    "parsed_source_coverage": (
                        f"automated_outline_candidates_from_{len(page_records)}_page_records;"
                        f"unsupported_pages={unsupported_pages};unsupported_regions={unsupported_regions}"
                    ),
                    "dependency_closure": "not_derived_for_automated_outline_candidates",
                    "enumeration_traversal": "confirmed_obligations_not_classified",
                    "output_budget_coverage": "computed_at_query_time",
                },
            }
            rights = {
                "rights_schema_version": "0.1.0",
                "content_class": base.rights["content_class"],
                "redistribution": base.rights["redistribution"],
                "processing": sorted(set(base.rights["processing"]) | {"local_deterministic_outline_derivation"}),
                "model_use": base.rights["model_use"],
                "statement": "This automated, unreviewed outline is derived locally from an authorized page-text pack; it grants no new source, model, or redistribution permission.",
            }
            derivation_relative = "derivations/base-pack.json"
            report_relative = "derived-outline-report.json"
            derivation_path = staging.joinpath(*PurePosixPath(derivation_relative).parts)
            derivation_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(derivation_path, base_descriptor)
            _write_json(staging / report_relative, report)
            _write_json(staging / "manifest.json", manifest)
            _write_json(staging / "rights.json", rights)
            _write_json(staging / "records.json", {"schema_version": "0.1.0", "records": derived_records})
            inventoried = sorted(
                {
                    "manifest.json",
                    "rights.json",
                    "records.json",
                    derivation_relative,
                    report_relative,
                    *source_paths,
                }
            )
            _write_json(
                staging / "inventory.json",
                {
                    "schema_version": "0.1.0",
                    "algorithm": "sha256",
                    "files": [_inventory_entry(staging, relative) for relative in inventoried],
                },
            )
            validated = validate_pack_directory(staging)
        _activate(staging, output)
        return {
            "operation": "compile_derived_outline_pack",
            "status": "compiled",
            "package_digest": validated.package_digest,
            "pack_id": validated.manifest["pack_id"],
            "edition_id": validated.manifest["edition_id"],
            "page_records": len(page_records),
            "derived_records": len(derived_records),
            "unsupported_pages": unsupported_pages,
            "unsupported_regions": unsupported_regions,
            "detected_kinds": detected,
            "output_directory": str(output),
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)
