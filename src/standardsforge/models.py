from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True, slots=True)
class ValidatedPack:
    root: Path
    package_digest: str
    manifest: dict[str, Any]
    rights: dict[str, Any]
    records: tuple[dict[str, Any], ...]
    inventory: tuple[InventoryEntry, ...]


@dataclass(frozen=True, slots=True)
class LocalPolicy:
    policy_id: str
    principal_id: str
    allow_admin_install: bool
    allow_serve: bool
    allowed_pack_ids: frozenset[str]
    allowed_content_classes: frozenset[str]
    fingerprint: str
