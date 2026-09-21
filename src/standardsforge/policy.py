from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import StandardsForgeError, require
from .models import LocalPolicy, ValidatedPack


_POLICY_KEYS = {
    "policy_version",
    "policy_id",
    "principal_id",
    "allow_admin_install",
    "allow_serve",
    "allowed_pack_ids",
    "allowed_content_classes",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def load_policy(path: str | Path) -> LocalPolicy:
    policy_path = Path(path)
    try:
        raw = policy_path.read_bytes()
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_policy", "The local policy could not be read as JSON.") from exc

    require(isinstance(data, dict), "invalid_policy", "The local policy must be a JSON object.")
    unknown = sorted(set(data) - _POLICY_KEYS)
    require(not unknown, "invalid_policy", "The local policy has unknown fields.", fields=unknown)
    require(data.get("policy_version") == "0.1.0", "unsupported_policy_version", "Unsupported policy version.")

    for key in ("policy_id", "principal_id"):
        require(isinstance(data.get(key), str) and bool(data[key].strip()), "invalid_policy", f"{key} is required.")
    for key in ("allow_admin_install", "allow_serve"):
        require(type(data.get(key)) is bool, "invalid_policy", f"{key} must be boolean.")
    for key in ("allowed_pack_ids", "allowed_content_classes"):
        value = data.get(key)
        require(
            isinstance(value, list) and all(isinstance(item, str) and item for item in value),
            "invalid_policy",
            f"{key} must be a list of non-empty strings.",
        )
        require(len(value) == len(set(value)), "invalid_policy", f"{key} must not contain duplicates.")

    return LocalPolicy(
        policy_id=data["policy_id"],
        principal_id=data["principal_id"],
        allow_admin_install=data["allow_admin_install"],
        allow_serve=data["allow_serve"],
        allowed_pack_ids=frozenset(data["allowed_pack_ids"]),
        allowed_content_classes=frozenset(data["allowed_content_classes"]),
        fingerprint=hashlib.sha256(_canonical_json(data)).hexdigest(),
    )


def authorize_install(policy: LocalPolicy, pack: ValidatedPack) -> None:
    require(policy.allow_admin_install, "policy_denied", "The local policy does not allow pack installation.")
    require(
        pack.manifest["pack_id"] in policy.allowed_pack_ids,
        "policy_denied",
        "The local policy does not authorize this pack.",
    )
    require(
        pack.rights["content_class"] in policy.allowed_content_classes,
        "policy_denied",
        "The local policy does not authorize this content class.",
    )
