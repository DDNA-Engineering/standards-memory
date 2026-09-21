from __future__ import annotations

import re
import unicodedata

from .errors import StandardsForgeError


_SAFE_IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9 () ./_-]{1,127}$")


def normalize_identifier(value: str) -> str:
    """Normalize harmless presentation differences without dropping semantic marks."""

    if not isinstance(value, str) or not value.strip():
        raise StandardsForgeError("invalid_identifier", "A non-empty identifier is required.")
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise StandardsForgeError(
            "invalid_identifier",
            "The identifier contains unsupported characters or length.",
        )
    return normalized
