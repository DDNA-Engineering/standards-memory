"""Explicit administrative tokenizer acquisition and pinned offline counting."""
from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

from .errors import StandardsForgeError, require


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _tiktoken():
    try:
        import tiktoken
        return tiktoken
    except ImportError as exc:
        raise StandardsForgeError("tokenizer_unavailable", "Install the optional tokens extra and explicitly prepare a local tokenizer artifact.") from exc


def export_tokenizer(encoding_name: str, destination: str | Path) -> dict[str, Any]:
    require(encoding_name in {"cl100k_base", "o200k_base"}, "invalid_tokenizer", "Unsupported tokenizer name.")
    target = Path(destination)
    require(not target.exists(), "tokenizer_exists", "Tokenizer output already exists.")
    # This explicitly invoked administrative operation may acquire public
    # tokenizer data. Query-time counting never calls get_encoding.
    encoding = _tiktoken().get_encoding(encoding_name)
    payload = {"schema_version": "0.1.0", "name": encoding_name, "pat_str": encoding._pat_str,
               "special_tokens": encoding._special_tokens,
               "mergeable_ranks": [[base64.b64encode(token).decode("ascii"), rank]
                                   for token, rank in sorted(encoding._mergeable_ranks.items(), key=lambda item: item[1])]}
    data = canonical_json(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as writer:
        writer.write(data)
    return {"operation": "export_tokenizer", "path": str(target), "sha256": hashlib.sha256(data).hexdigest(),
            "encoding": encoding_name, "bytes": len(data)}


class TokenCounter:
    def __init__(self, source: str | Path, sha256: str):
        path = Path(source)
        require(path.is_file() and path.stat().st_size <= 64 * 1024 * 1024, "invalid_tokenizer", "Missing or oversized tokenizer artifact.")
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == sha256, "tokenizer_integrity_failure", "Tokenizer artifact does not match the configured SHA-256.")
        try:
            payload = json.loads(data)
            require(isinstance(payload, dict) and set(payload) == {"schema_version", "name", "pat_str", "special_tokens", "mergeable_ranks"}
                    and payload["schema_version"] == "0.1.0", "invalid_tokenizer", "Unsupported tokenizer artifact.")
            rows = payload["mergeable_ranks"]
            require(isinstance(rows, list) and 256 <= len(rows) <= 500000, "invalid_tokenizer", "Invalid tokenizer vocabulary size.")
            ranks = {}
            for token, rank in rows:
                decoded = base64.b64decode(token, validate=True)
                require(decoded and type(rank) is int and rank >= 0 and decoded not in ranks, "invalid_tokenizer", "Invalid vocabulary entry.")
                ranks[decoded] = rank
            require(len(set(ranks.values())) == len(ranks), "invalid_tokenizer", "Duplicate vocabulary rank.")
            self.encoding = _tiktoken().Encoding(name=payload["name"], pat_str=payload["pat_str"],
                mergeable_ranks=ranks, special_tokens=payload["special_tokens"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StandardsForgeError("invalid_tokenizer", "Tokenizer artifact is malformed.") from exc
        self.identity = {"encoding": payload["name"], "artifact_sha256": sha256,
                         "implementation": "tiktoken", "implementation_version": importlib.metadata.version("tiktoken")}

    def count(self, value: Any) -> int:
        # Evidence containing strings resembling special tokens remains text.
        return len(self.encoding.encode(canonical_json(value).decode("utf-8"), disallowed_special=()))
