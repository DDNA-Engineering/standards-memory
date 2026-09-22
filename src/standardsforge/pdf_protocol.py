from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any


PROTOCOL_VERSION = "pdf-extraction-worker/0.1.0"
LIMIT_POLICY_VERSION = "pdf-limits/0.1.0"
PYPDF_VERSION = "6.19.0"
FONTTOOLS_VERSION = "4.65.0"


@dataclass(frozen=True)
class ParserLimits:
    source_bytes: int = 256 * 1024 * 1024
    pages: int = 5000
    page_content_bytes: int = 64 * 1024 * 1024
    page_text_bytes: int = 64 * 1024 * 1024
    aggregate_text_bytes: int = 256 * 1024 * 1024
    result_bytes: int = 4 * 1024 * 1024
    process_memory_bytes: int = 1024 * 1024 * 1024
    cpu_seconds: int = 300
    wall_seconds: int = 600

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


DEFAULT_LIMITS = ParserLimits()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_page_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def build_request(
    *,
    source_sha256: str,
    source_bytes: int,
    expected_pages: int,
    extraction_mode: str,
    encryption_policy: str,
    limits: ParserLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    if extraction_mode not in {"layout_rotated_included", "simple"}:
        raise ValueError("Unsupported PDF extraction mode.")
    if encryption_policy not in {"reject", "empty_password_only"}:
        raise ValueError("Unsupported PDF encryption policy.")
    if (
        re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        or type(source_bytes) is not int
        or type(expected_pages) is not int
        or not 1 <= source_bytes <= limits.source_bytes
        or not 1 <= expected_pages <= limits.pages
        or any(type(value) is not int or value <= 0 for value in limits.to_dict().values())
        or any(value > DEFAULT_LIMITS.to_dict()[name] for name, value in limits.to_dict().items())
    ):
        raise ValueError("PDF extraction request identity is invalid.")
    return {
        "protocol": PROTOCOL_VERSION,
        "limit_policy": LIMIT_POLICY_VERSION,
        "source": {
            "sha256": source_sha256,
            "bytes": source_bytes,
            "expected_pages": expected_pages,
        },
        "parser": {
            "pypdf": PYPDF_VERSION,
            "fonttools": FONTTOOLS_VERSION,
            "strict": True,
            "extraction_mode": extraction_mode,
            "encryption_policy": encryption_policy,
            "normalization": "unicode_nfc_lf_trim_outer_blank_lines_rstrip_lines",
        },
        "limits": limits.to_dict(),
    }
