from __future__ import annotations

import asyncio
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp import Client, StdioServerParameters  # noqa: E402
from mcp.server._otel import OpenTelemetryMiddleware  # noqa: E402

from standardsforge.mcp_server import MCP_TOOL_NAMES, create_mcp_server  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402


PACK_V1 = ROOT / "examples" / "packs" / "fictional-adapter-v1"
PACK_V2 = ROOT / "examples" / "packs" / "fictional-adapter-v2"
POLICY = ROOT / "examples" / "policies" / "local-synthetic.json"
MCP_CONTRACT = ROOT / "contracts" / "mcp-tools.json"
REAL_SOCKET = socket.socket


class _DeniedSocketMeta(type):
    def __instancecheck__(cls, instance) -> bool:
        return isinstance(instance, REAL_SOCKET)


class _DeniedSocket(metaclass=_DeniedSocketMeta):
    def __new__(cls, *args, **kwargs):
        raise AssertionError("network access attempted")


def _text_payload(result) -> dict:
    return json.loads(result.content[0].text)


def _run_with_socket_creation_denied(coroutine) -> None:
    loop = asyncio.new_event_loop()
    try:
        with patch.object(socket, "socket", _DeniedSocket):
            loop.run_until_complete(coroutine)
    finally:
        loop.close()


class MCPAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-mcp-test-")
        base = Path(self.temp.name)
        self.db_path = base / "memory.db"
        self.object_root = base / "objects"
        self.service = StandardsForgeService(self.db_path, self.object_root)
        self.first_digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        self.second_digest = self.service.install_pack(PACK_V2, POLICY)["package_digest"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_schema_is_exact_read_only_closed_world_and_principal_free(self) -> None:
        contract = json.loads(MCP_CONTRACT.read_text(encoding="utf-8"))
        expected_arguments = {item["name"]: set(item["arguments"]) for item in contract["tools"]}
        server = create_mcp_server(self.service, "local-user")
        self.assertFalse(
            any(isinstance(item, OpenTelemetryMiddleware) for item in server._lowlevel_server.middleware)
        )

        async def scenario() -> None:
            async with Client(server, raise_exceptions=True) as client:
                listed = await client.list_tools()
            self.assertEqual(list(MCP_TOOL_NAMES), [tool.name for tool in listed.tools])
            self.assertEqual(set(expected_arguments), {tool.name for tool in listed.tools})
            for tool in listed.tools:
                self.assertEqual(expected_arguments[tool.name], set(tool.input_schema["properties"]))
                self.assertNotIn("principal", tool.input_schema["properties"])
                self.assertNotIn("principal_id", tool.input_schema["properties"])
                self.assertTrue(tool.annotations.read_only_hint)
                self.assertFalse(tool.annotations.open_world_hint)

        _run_with_socket_creation_denied(scenario())

    def test_all_six_operations_match_core_results_with_networking_denied(self) -> None:
        server = create_mcp_server(self.service, "local-user")
        cases = [
            ("search", {"query": "axial load"}, self.service.search("axial load", "local-user")),
            (
                "resolve_document",
                {"identifier": "EXAMPLE-SPEC-100", "edition_id": "example:spec-100:2025-a"},
                self.service.resolve_document(
                    "EXAMPLE-SPEC-100", "local-user", "example:spec-100:2025-a"
                ),
            ),
            (
                "get_clause",
                {"package_digest": self.first_digest, "clause_reference": "4.2.1"},
                self.service.get_clause(self.first_digest, "4.2.1", "local-user"),
            ),
            (
                "build_context",
                {"package_digest": self.first_digest, "clause_references": ["4.2.1", "4.2.2"]},
                self.service.build_context(self.first_digest, ["4.2.1", "4.2.2"], "local-user"),
            ),
            (
                "enumerate_obligations",
                {"package_digest": self.first_digest, "scope_prefix": "4.2"},
                self.service.enumerate_obligations(self.first_digest, "local-user", "4.2"),
            ),
            (
                "diff_editions",
                {
                    "from_package_digest": self.first_digest,
                    "to_package_digest": self.second_digest,
                },
                self.service.diff_editions(self.first_digest, self.second_digest, "local-user"),
            ),
        ]

        async def scenario() -> None:
            async with Client(server, raise_exceptions=True) as client:
                for name, arguments, expected in cases:
                    result = await client.call_tool(name, arguments)
                    self.assertFalse(result.is_error, name)
                    self.assertEqual({"ok": True, "result": expected}, result.structured_content, name)
                    self.assertEqual(result.structured_content, _text_payload(result), name)

        _run_with_socket_creation_denied(scenario())

    def test_bound_principal_cannot_be_selected_by_the_caller(self) -> None:
        secret_principal = "principal-that-must-not-leak"
        server = create_mcp_server(self.service, secret_principal)

        async def scenario() -> None:
            async with Client(server, raise_exceptions=True) as client:
                search_result = await client.call_tool(
                    "search",
                    {"query": "axial load", "principal_id": "local-user"},
                )
                if search_result.is_error:
                    self.assertNotIn(secret_principal, search_result.content[0].text)
                else:
                    self.assertEqual([], search_result.structured_content["result"]["results"])

                denied = await client.call_tool(
                    "get_clause",
                    {"package_digest": self.first_digest, "clause_reference": "4.2.1"},
                )
                self.assertTrue(denied.is_error)
                payload = _text_payload(denied)
                self.assertEqual("not_found", payload["error"]["code"])
                self.assertNotIn(secret_principal, denied.content[0].text)

        asyncio.run(scenario())

    def test_stdio_subprocess_round_trip(self) -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "standardsforge.mcp_server",
                "--db",
                str(self.db_path),
                "--store",
                str(self.object_root),
                "--principal",
                "local-user",
            ],
        )

        async def scenario() -> None:
            async with Client(parameters) as client:
                listed = await client.list_tools()
                result = await client.call_tool("search", {"query": "axial load"})
            self.assertEqual(list(MCP_TOOL_NAMES), [tool.name for tool in listed.tools])
            self.assertFalse(result.is_error)
            self.assertEqual("search", result.structured_content["result"]["operation"])
            self.assertEqual(self.first_digest, result.structured_content["result"]["results"][0]["package_digest"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
