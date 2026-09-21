from __future__ import annotations

import hashlib
import json
import os
import tempfile
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


def write_pack_policy(
    source: str | Path,
    output_path: str | Path,
    principal_id: str,
    content_class: str,
) -> dict[str, Any]:
    """Write an exact one-pack policy after explicit operator classification."""

    from .pack import open_validated_pack

    require(
        isinstance(principal_id, str) and bool(principal_id.strip()),
        "invalid_policy",
        "principal_id must be a non-empty string.",
    )
    require(
        isinstance(content_class, str) and bool(content_class.strip()),
        "invalid_policy",
        "content_class must be a non-empty string.",
    )
    principal = principal_id.strip()
    expected_content_class = content_class.strip()
    destination = Path(output_path).resolve()
    require(not destination.exists(), "policy_output_exists", "The policy output already exists.", path=str(destination))
    require(destination.suffix.lower() == ".json", "invalid_policy_path", "The policy output must be JSON.")

    with open_validated_pack(source) as pack:
        actual_content_class = pack.rights["content_class"]
        require(
            actual_content_class == expected_content_class,
            "policy_content_class_mismatch",
            "The explicitly authorized content class does not match the validated pack claim.",
            expected=expected_content_class,
            actual=actual_content_class,
        )
        policy = {
            "policy_version": "0.1.0",
            "policy_id": f"local-pack-{pack.package_digest[:16]}",
            "principal_id": principal,
            "allow_admin_install": True,
            "allow_serve": True,
            "allowed_pack_ids": [pack.manifest["pack_id"]],
            "allowed_content_classes": [expected_content_class],
        }
        package_digest = pack.package_digest
        pack_id = pack.manifest["pack_id"]

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.", suffix=".json", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes((json.dumps(policy, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    written = load_policy(destination)
    return {
        "operation": "write_pack_policy",
        "status": "written",
        "policy": str(destination),
        "policy_id": written.policy_id,
        "principal_id": written.principal_id,
        "pack_id": pack_id,
        "package_digest": package_digest,
        "content_class": expected_content_class,
    }
