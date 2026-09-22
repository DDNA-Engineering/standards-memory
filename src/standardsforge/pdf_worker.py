from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from .pdf_protocol import (
    DEFAULT_LIMITS,
    FONTTOOLS_VERSION,
    LIMIT_POLICY_VERSION,
    PROTOCOL_VERSION,
    PYPDF_VERSION,
    ParserLimits,
    canonical_json_bytes,
    normalize_page_text,
    sha256_bytes,
)


class WorkerFailure(Exception):
    def __init__(self, code: str, stage: str, **details: object) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.details = details


def _apply_posix_limits(limits: ParserLimits) -> None:
    if os.name == "nt":
        return
    try:
        import resource

        required = ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_CORE")
        if any(not hasattr(resource, name) for name in required):
            raise RuntimeError("required limit missing")
        resource.setrlimit(resource.RLIMIT_AS, (limits.process_memory_bytes, limits.process_memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.page_text_bytes, limits.page_text_bytes))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception as exc:
        raise WorkerFailure("parser_limits_unavailable", "startup") from exc


def _load_request(path: Path) -> tuple[dict[str, Any], ParserLimits, str]:
    try:
        raw = path.read_bytes()
        request = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerFailure("parser_protocol_error", "startup") from exc
    if not isinstance(request, dict) or canonical_json_bytes(request) != raw:
        raise WorkerFailure("parser_protocol_error", "startup")
    if (
        set(request) != {"protocol", "limit_policy", "source", "parser", "limits"}
        or not isinstance(request.get("source"), dict)
        or set(request["source"]) != {"sha256", "bytes", "expected_pages"}
        or not isinstance(request.get("parser"), dict)
        or set(request["parser"]) != {
            "pypdf", "fonttools", "strict", "extraction_mode", "encryption_policy", "normalization"
        }
        or not isinstance(request.get("limits"), dict)
        or set(request["limits"]) != set(ParserLimits().to_dict())
    ):
        raise WorkerFailure("parser_protocol_error", "startup")
    try:
        limits = ParserLimits(**request["limits"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkerFailure("parser_protocol_error", "startup") from exc
    if (
        request.get("protocol") != PROTOCOL_VERSION
        or request.get("limit_policy") != LIMIT_POLICY_VERSION
        or request.get("parser", {}).get("pypdf") != PYPDF_VERSION
        or request.get("parser", {}).get("fonttools") != FONTTOOLS_VERSION
        or request.get("parser", {}).get("strict") is not True
        or request["parser"].get("extraction_mode") not in {"layout_rotated_included", "simple"}
        or request["parser"].get("encryption_policy") not in {"reject", "empty_password_only"}
        or request["parser"].get("normalization") != "unicode_nfc_lf_trim_outer_blank_lines_rstrip_lines"
        or not isinstance(request["source"].get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", request["source"]["sha256"]) is None
        or type(request["source"].get("bytes")) is not int
        or type(request["source"].get("expected_pages")) is not int
        or any(type(value) is not int for value in limits.to_dict().values())
        or any(value <= 0 for value in limits.to_dict().values())
    ):
        raise WorkerFailure("parser_protocol_error", "startup")
    return request, limits, sha256_bytes(raw)


def _source_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_error(output: Path, failure: WorkerFailure) -> None:
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir()
    value = {
        "protocol": PROTOCOL_VERSION,
        "code": failure.code,
        "stage": failure.stage,
        "details": failure.details,
    }
    partial = output / ".error.json.partial"
    partial.write_bytes(canonical_json_bytes(value))
    partial.replace(output / "error.json")


def _extract(request_path: Path, source_path: Path, output: Path) -> None:
    _apply_posix_limits(DEFAULT_LIMITS)
    request, limits, request_digest = _load_request(request_path)
    if any(
        value > DEFAULT_LIMITS.to_dict()[name]
        for name, value in limits.to_dict().items()
    ):
        raise WorkerFailure("parser_protocol_error", "startup")
    _apply_posix_limits(limits)
    source = request["source"]
    try:
        stat = source_path.stat()
    except OSError as exc:
        raise WorkerFailure("parser_source_changed", "source_verify") from exc
    if (
        not source_path.is_file()
        or source_path.is_symlink()
        or stat.st_size != source["bytes"]
        or stat.st_size > limits.source_bytes
        or _source_digest(source_path) != source["sha256"]
    ):
        raise WorkerFailure("parser_source_changed", "source_verify")

    try:
        import fontTools
        import pypdf
    except ImportError as exc:
        raise WorkerFailure("compiler_dependency_missing", "startup") from exc
    if pypdf.__version__ != PYPDF_VERSION or fontTools.__version__ != FONTTOOLS_VERSION:
        raise WorkerFailure("unsupported_compiler_dependency", "startup")
    try:
        reader = pypdf.PdfReader(source_path, strict=True)
    except Exception as exc:
        raise WorkerFailure("invalid_pdf", "reader") from exc
    encryption_status = "not_encrypted"
    if reader.is_encrypted:
        if request["parser"]["encryption_policy"] == "reject":
            raise WorkerFailure("encrypted_pdf", "reader")
        try:
            decrypted = reader.decrypt("")
        except Exception as exc:
            raise WorkerFailure("encrypted_pdf", "reader") from exc
        if not decrypted:
            raise WorkerFailure("encrypted_pdf", "reader")
        encryption_status = "empty_password_decrypted_for_extraction"
    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise WorkerFailure("invalid_pdf", "metadata") from exc
    if page_count < 1 or page_count > limits.pages:
        raise WorkerFailure("compiler_limit_exceeded", "metadata", limit="pages", observed=page_count)
    if page_count != source["expected_pages"]:
        raise WorkerFailure(
            "pdf_page_count_mismatch",
            "metadata",
            expected=source["expected_pages"],
            actual=page_count,
        )

    output.mkdir()
    pages: list[dict[str, object]] = []
    aggregate = 0
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            contents = page.get_contents()
            content_bytes = 0 if contents is None else len(contents.get_data())
            if content_bytes > limits.page_content_bytes:
                raise WorkerFailure(
                    "parser_output_limit_exceeded",
                    "page",
                    page=page_index,
                    limit="page_content_bytes",
                    observed=content_bytes,
                )
            raw_text = ""
            if contents is not None:
                if request["parser"]["extraction_mode"] == "layout_rotated_included":
                    raw_text = page.extract_text(
                        extraction_mode="layout",
                        layout_mode_space_vertically=False,
                        layout_mode_strip_rotated=False,
                    ) or ""
                else:
                    raw_text = page.extract_text() or ""
        except WorkerFailure:
            raise
        except MemoryError as exc:
            raise WorkerFailure("parser_memory_limit_exceeded", "page", page=page_index) from exc
        except Exception as exc:
            raise WorkerFailure("pdf_page_extraction_failed", "page", page=page_index) from exc
        text_bytes = normalize_page_text(raw_text).encode("utf-8")
        if len(text_bytes) > limits.page_text_bytes:
            raise WorkerFailure(
                "parser_output_limit_exceeded",
                "page",
                page=page_index,
                limit="page_text_bytes",
                observed=len(text_bytes),
            )
        aggregate += len(text_bytes)
        if aggregate > limits.aggregate_text_bytes:
            raise WorkerFailure(
                "parser_output_limit_exceeded",
                "page",
                page=page_index,
                limit="aggregate_text_bytes",
                observed=aggregate,
            )
        filename = f"page-{page_index:04d}.txt"
        target = output / filename
        target.write_bytes(text_bytes)
        pages.append(
            {
                "physical_page": page_index,
                "path": filename,
                "bytes": len(text_bytes),
                "sha256": sha256_bytes(text_bytes),
                "content_stream_bytes": content_bytes,
                "text_characters": len(text_bytes.decode("utf-8")),
                "text_layer_status": "extracted" if text_bytes else "no_text",
            }
        )
    result = {
        "protocol": PROTOCOL_VERSION,
        "limit_policy": LIMIT_POLICY_VERSION,
        "request_sha256": request_digest,
        "source_sha256": source["sha256"],
        "page_count": page_count,
        "encryption_status": encryption_status,
        "normalization": request["parser"]["normalization"],
        "pages": pages,
    }
    result_bytes = canonical_json_bytes(result)
    if len(result_bytes) > limits.result_bytes:
        raise WorkerFailure(
            "parser_output_limit_exceeded",
            "result",
            limit="result_bytes",
            observed=len(result_bytes),
        )
    partial = output / ".result.json.partial"
    partial.write_bytes(result_bytes)
    partial.replace(output / "result.json")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if sys.stdin.buffer.read(1) != b"1":
        return 3
    try:
        _extract(args.request, args.source, args.output)
        return 0
    except WorkerFailure as failure:
        try:
            _write_error(args.output, failure)
        except Exception:
            pass
        return 2
    except BaseException:
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
