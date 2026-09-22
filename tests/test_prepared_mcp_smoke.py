from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "prepared_distribution"))

import smoke_mcp  # noqa: E402


class _FakeClient:
    def __init__(self, *, documents: list[dict], results: list[dict]) -> None:
        self.documents = documents
        self.results = results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def list_tools(self):
        return SimpleNamespace(
            tools=[SimpleNamespace(name=name) for name in smoke_mcp.EXPECTED_TOOLS]
        )

    async def call_tool(self, name, arguments):
        if name == "list_documents":
            return SimpleNamespace(
                is_error=False,
                structured_content={
                    "ok": True,
                    "result": {
                        "documents": self.documents,
                        "page": {"matching_authorized_package_count": len(self.documents)},
                    },
                },
            )
        return SimpleNamespace(
            is_error=False,
            structured_content={"ok": True, "result": {"results": self.results}},
        )


class PreparedMCPSmokeTests(unittest.TestCase):
    def _run(self, documents: list[dict], results: list[dict]) -> None:
        fake = _FakeClient(documents=documents, results=results)
        with patch.object(smoke_mcp, "Client", return_value=fake):
            asyncio.run(smoke_mcp._smoke("db", "store", "local-user", "query"))

    def test_requires_authorized_document_and_search_results(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no authorized installed documents"):
            self._run([], [{"record_id": "record"}])
        with self.assertRaisesRegex(RuntimeError, "returned no authorized evidence"):
            self._run([{"package_digest": "a" * 64}], [])

    def test_accepts_nonempty_authorized_discovery_and_search(self) -> None:
        self._run(
            [{"package_digest": "a" * 64}],
            [{"record_id": "record"}],
        )


if __name__ == "__main__":
    unittest.main()
