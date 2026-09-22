from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .errors import StandardsForgeError
from .pdf_protocol import (
    DEFAULT_LIMITS,
    LIMIT_POLICY_VERSION,
    PROTOCOL_VERSION,
    ParserLimits,
    WORKER_ERROR_BYTES,
    build_request,
    canonical_json_bytes,
    sha256_bytes,
)


@dataclass(frozen=True)
class ParsedPage:
    physical_page: int
    path: Path
    bytes: int
    sha256: str
    content_stream_bytes: int
    text_characters: int
    text_layer_status: str


@dataclass(frozen=True)
class ParsedPDF:
    page_count: int
    encryption_status: str
    pages: tuple[ParsedPage, ...]


_WORKER_ERROR_MESSAGES = {
    "compiler_dependency_missing": "PDF compilation requires the pinned compiler extra.",
    "unsupported_compiler_dependency": "PDF compilation requires the pinned compiler dependency versions.",
    "invalid_pdf": "The verified source could not be parsed as a strict PDF.",
    "encrypted_pdf": "The PDF encryption policy rejected the verified source.",
    "compiler_limit_exceeded": "The PDF metadata exceeds a compiler limit.",
    "pdf_page_count_mismatch": "The PDF page count does not match verified metadata.",
    "pdf_page_extraction_failed": "A PDF page text layer could not be extracted.",
    "parser_limits_unavailable": "Required parser process limits could not be installed.",
    "parser_protocol_error": "The parser worker protocol failed validation.",
    "parser_source_changed": "The PDF source changed before isolated parsing.",
    "parser_memory_limit_exceeded": "The parser worker exceeded its memory limit.",
    "parser_output_limit_exceeded": "The parser worker exceeded an output limit.",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_regular_unlinked(path: Path) -> bool:
    try:
        value = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISREG(value.st_mode) or path.is_symlink():
        return False
    attributes = getattr(value, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return not bool(attributes & reparse)


def _kill_process(process: subprocess.Popen[bytes], job: object | None) -> None:
    if os.name == "nt":
        if job is not None:
            job.terminate()
        else:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def _start_worker(
    request_path: Path,
    source_path: Path,
    output: Path,
    limits: ParserLimits,
) -> tuple[subprocess.Popen[bytes], object | None]:
    package_root = Path(__file__).resolve().parents[1]
    dependency_root = Path(sysconfig.get_path("purelib")).resolve()
    bootstrap = (
        "import runpy,sys;"
        "sys.path[:0]=[sys.argv.pop(1),sys.argv.pop(1)];"
        "runpy.run_module('standardsforge.pdf_worker',run_name='__main__')"
    )
    # Windows virtual-environment launchers may create a second interpreter
    # process. Start the base interpreter directly so the Job Object can retain
    # an active-process limit of one. ``-S`` plus the two explicit roots keeps
    # the worker independent of user site packages and .pth startup hooks.
    executable = (
        str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())
        if os.name == "nt"
        else sys.executable
    )
    command = [
        executable,
        "-I",
        "-S",
        "-c",
        bootstrap,
        str(package_root),
        str(dependency_root),
        "--request",
        str(request_path),
        "--source",
        str(source_path),
        "--output",
        str(output),
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    job = None
    try:
        if os.name == "nt":
            from ._windows_job import WindowsJob

            job = WindowsJob(limits.process_memory_bytes, limits.cpu_seconds)
            job.assign(process._handle)
        if process.stdin is None:
            raise OSError("worker stdin unavailable")
        process.stdin.write(b"1")
        process.stdin.close()
        return process, job
    except Exception as exc:
        _kill_process(process, job)
        if job is not None:
            job.close()
        raise StandardsForgeError(
            "parser_limits_unavailable",
            "Required parser process limits could not be installed.",
            {"stage": "startup", "limit_policy": LIMIT_POLICY_VERSION},
        ) from exc


def _load_error(output: Path) -> StandardsForgeError | None:
    error_path = output / "error.json"
    if not _is_regular_unlinked(error_path) or error_path.stat().st_size > WORKER_ERROR_BYTES:
        return None
    try:
        value = json.loads(error_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"protocol", "code", "stage", "details"}
        or value["protocol"] != PROTOCOL_VERSION
        or value["code"] not in _WORKER_ERROR_MESSAGES
        or not isinstance(value["stage"], str)
        or not isinstance(value["details"], dict)
    ):
        return None
    details = dict(value["details"])
    details.update({"stage": value["stage"], "protocol": PROTOCOL_VERSION, "limit_policy": LIMIT_POLICY_VERSION})
    return StandardsForgeError(value["code"], _WORKER_ERROR_MESSAGES[value["code"]], details)


def _validate_output(
    output: Path,
    request: dict[str, object],
    request_digest: str,
    limits: ParserLimits,
) -> ParsedPDF:
    result_path = output / "result.json"
    if not _is_regular_unlinked(result_path) or result_path.stat().st_size > limits.result_bytes:
        raise StandardsForgeError("parser_protocol_error", "The parser worker result is missing or oversized.")
    try:
        raw = result_path.read_bytes()
        result = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("parser_protocol_error", "The parser worker result is invalid JSON.") from exc
    if canonical_json_bytes(result) != raw or not isinstance(result, dict) or set(result) != {
        "protocol", "limit_policy", "request_sha256", "source_sha256", "page_count",
        "encryption_status", "normalization", "pages"
    }:
        raise StandardsForgeError("parser_protocol_error", "The parser worker result shape is invalid.")
    if (
        result["protocol"] != PROTOCOL_VERSION
        or result["limit_policy"] != LIMIT_POLICY_VERSION
        or result["request_sha256"] != request_digest
        or result["source_sha256"] != request["source"]["sha256"]
        or result["page_count"] != request["source"]["expected_pages"]
        or result["normalization"] != request["parser"]["normalization"]
        or not isinstance(result["pages"], list)
        or len(result["pages"]) != result["page_count"]
    ):
        raise StandardsForgeError("parser_protocol_error", "The parser worker result identity is inconsistent.")
    expected_names = {"result.json"}
    pages: list[ParsedPage] = []
    aggregate = 0
    for ordinal, item in enumerate(result["pages"], start=1):
        if not isinstance(item, dict) or set(item) != {
            "physical_page", "path", "bytes", "sha256", "content_stream_bytes",
            "text_characters", "text_layer_status"
        }:
            raise StandardsForgeError("parser_protocol_error", "A parser page result is malformed.")
        name = f"page-{ordinal:04d}.txt"
        if item["physical_page"] != ordinal or item["path"] != name or item["text_layer_status"] not in {"extracted", "no_text"}:
            raise StandardsForgeError("parser_protocol_error", "Parser page order or identity is invalid.")
        page_path = output / name
        if name in expected_names or not _is_regular_unlinked(page_path):
            raise StandardsForgeError("parser_protocol_error", "A parser page file is missing or unsafe.")
        expected_names.add(name)
        data = page_path.read_bytes()
        try:
            decoded = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StandardsForgeError("parser_protocol_error", "Parser page text is not UTF-8.") from exc
        if (
            len(data) != item["bytes"]
            or len(data) > limits.page_text_bytes
            or sha256_bytes(data) != item["sha256"]
            or len(decoded) != item["text_characters"]
            or (bool(data) != (item["text_layer_status"] == "extracted"))
            or not isinstance(item["content_stream_bytes"], int)
            or not 0 <= item["content_stream_bytes"] <= limits.page_content_bytes
        ):
            raise StandardsForgeError("parser_protocol_error", "Parser page bytes do not match their result record.")
        aggregate += len(data)
        pages.append(ParsedPage(ordinal, page_path, len(data), item["sha256"], item["content_stream_bytes"], item["text_characters"], item["text_layer_status"]))
    if aggregate > limits.aggregate_text_bytes:
        raise StandardsForgeError("parser_output_limit_exceeded", "The parser aggregate output exceeds its limit.")
    try:
        children = list(output.iterdir())
    except OSError as exc:
        raise StandardsForgeError("parser_protocol_error", "The parser output cannot be inventoried.") from exc
    if {item.name for item in children} != expected_names:
        raise StandardsForgeError("parser_protocol_error", "The parser output contains extra or missing files.")
    return ParsedPDF(result["page_count"], result["encryption_status"], tuple(pages))


@contextmanager
def isolated_pdf_pages(
    source_path: Path,
    *,
    source_sha256: str,
    source_bytes: int,
    expected_pages: int,
    extraction_mode: str,
    encryption_policy: str,
    limits: ParserLimits = DEFAULT_LIMITS,
) -> Iterator[ParsedPDF]:
    source_path = source_path.resolve()
    request = build_request(
        source_sha256=source_sha256,
        source_bytes=source_bytes,
        expected_pages=expected_pages,
        extraction_mode=extraction_mode,
        encryption_policy=encryption_policy,
        limits=limits,
    )
    request_bytes = canonical_json_bytes(request)
    request_digest = sha256_bytes(request_bytes)
    with tempfile.TemporaryDirectory(prefix="standardsforge-pdf-worker-") as temporary:
        root = Path(temporary)
        request_path = root / "request.json"
        output = root / "output"
        request_path.write_bytes(request_bytes)
        process, job = _start_worker(request_path, source_path, output, limits)
        try:
            try:
                return_code = process.wait(timeout=limits.wall_seconds)
            except subprocess.TimeoutExpired as exc:
                _kill_process(process, job)
                raise StandardsForgeError(
                    "parser_wall_time_exceeded",
                    "The parser worker exceeded its wall-time limit.",
                    {"limit_seconds": limits.wall_seconds, "limit_policy": LIMIT_POLICY_VERSION},
                ) from exc
            if return_code != 0:
                failure = _load_error(output)
                if failure is not None:
                    raise failure
                if os.name != "nt" and return_code == -getattr(signal, "SIGXCPU", 24):
                    raise StandardsForgeError("parser_cpu_limit_exceeded", "The parser worker exceeded its CPU limit.")
                raise StandardsForgeError(
                    "parser_worker_terminated",
                    "The parser worker terminated without a valid result.",
                    {"termination_reason": "resource_limit_or_crash", "limit_policy": LIMIT_POLICY_VERSION},
                )
            parsed = _validate_output(output, request, request_digest, limits)
            yield parsed
        finally:
            if process.poll() is None:
                _kill_process(process, job)
            if job is not None:
                job.close()
