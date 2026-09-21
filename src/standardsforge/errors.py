from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StandardsForgeError(Exception):
    """Typed failure safe for a structured CLI or adapter response."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


def require(condition: bool, code: str, message: str, **details: Any) -> None:
    if not condition:
        raise StandardsForgeError(code, message, details)
