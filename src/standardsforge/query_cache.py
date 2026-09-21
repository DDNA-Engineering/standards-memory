from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any


def canonical_cache_key(namespace: str, version: str, material: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"namespace": namespace, "version": version, "material": material},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class VersionedLRUCache:
    """Small in-process cache with closed JSON values and verified envelopes."""

    def __init__(self, namespace: str, version: str, *, max_entries: int = 128, max_bytes: int = 8_388_608) -> None:
        if not namespace or not version or max_entries < 1 or max_bytes < 1:
            raise ValueError("Cache configuration is invalid.")
        self.namespace = namespace
        self.version = version
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def key(self, material: dict[str, Any]) -> str:
        return canonical_cache_key(self.namespace, self.version, material)

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            payload, checksum = entry
            if hashlib.sha256(payload).hexdigest() != checksum:
                self._bytes -= len(payload)
                del self._entries[key]
                self.misses += 1
                return None
            try:
                value = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._bytes -= len(payload)
                del self._entries[key]
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return value

    def put(self, key: str, value: Any) -> None:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(payload) > self.max_bytes:
            return
        checksum = hashlib.sha256(payload).hexdigest()
        with self._lock:
            existing = self._entries.pop(key, None)
            if existing is not None:
                self._bytes -= len(existing[0])
            self._entries[key] = (payload, checksum)
            self._bytes += len(payload)
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                _, (removed, _) = self._entries.popitem(last=False)
                self._bytes -= len(removed)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    def discard(self, key: str) -> None:
        with self._lock:
            existing = self._entries.pop(key, None)
            if existing is not None:
                self._bytes -= len(existing[0])

    def stats(self) -> dict[str, int | str]:
        with self._lock:
            return {
                "namespace": self.namespace,
                "version": self.version,
                "entries": len(self._entries),
                "bytes": self._bytes,
                "hits": self.hits,
                "misses": self.misses,
            }
