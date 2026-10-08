"""Select a measured lossless representation of one exact evidence closure."""
from __future__ import annotations

import copy
from typing import Any
from .errors import require
from .tokenization import canonical_json


def select_evidence(service: Any, package_digest: str, record_id: str, principal_id: str,
                    *, max_tokens: int | None = None, max_bytes: int | None = None) -> dict[str, Any]:
    counter = service.token_counter
    require(max_tokens is None or type(max_tokens) is int and max_tokens > 0, "invalid_budget", "Token budget must be a positive integer.")
    require(max_bytes is None or type(max_bytes) is int and max_bytes > 0, "invalid_budget", "Byte budget must be a positive integer.")
    require(max_tokens is None or counter is not None, "tokenizer_unavailable", "A token budget requires a pinned local tokenizer configured by the host.")
    state = service.store.cache_state(principal_id)
    detailed = service.get_clause(package_digest, principal_id=principal_id, record_id=record_id)
    detailed.pop("budget")
    candidates, metrics = [], []
    for profile in ("detailed_json_v1", "compact_evidence_v1", "concise_evidence_v1"):
        packet = service._render_response_profile(copy.deepcopy(detailed), profile)
        service._finalize_budget(packet, None)
        byte_count = len(canonical_json(packet))
        tokens = counter.count(packet) if counter else None
        metric = {"profile": profile, "utf8_bytes": byte_count, "tokens": tokens,
                  "fits": (max_bytes is None or byte_count <= max_bytes) and (max_tokens is None or tokens <= max_tokens)}
        metrics.append(metric)
        if metric["fits"]:
            candidates.append((tokens if tokens is not None else byte_count, byte_count, profile, packet))
    require(bool(candidates), "budget_too_small", "No lossless evidence profile fits the requested budget.", candidates=metrics)
    _, _, profile, packet = min(candidates, key=lambda item: item[:3])
    service.store.authorized_package(principal_id, package_digest)
    require(service.store.cache_state(principal_id) == state, "authorization_changed", "Authorization changed during evidence selection; retry.")
    return {"schema_version": "0.1.0", "operation": "select_evidence", "selected_profile": profile,
            "selection_basis": "tokens" if counter else "utf8_bytes", "tokenizer": counter.identity if counter else None,
            "measurement_scope": "canonical_evidence_packet_json_only_excludes_selection_wrapper_tool_schema_and_model_chat_framing",
            "limits": {"max_tokens": max_tokens, "max_bytes": max_bytes}, "candidates": metrics, "evidence": packet}
