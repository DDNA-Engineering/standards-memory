from __future__ import annotations

import asyncio
import copy
import io
import json
import os
import socket
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from mcp import Client, StdioServerParameters  # noqa: E402
from mcp.server._otel import OpenTelemetryMiddleware  # noqa: E402

from standardsforge.cli import _parser as cli_parser, _run as cli_run  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.mcp_server import (  # noqa: E402
    MCP_SERVER_INSTRUCTIONS,
    MCP_TOOL_DESCRIPTIONS,
    MCP_TOOL_NAMES,
    MCP_TOOL_TITLES,
    create_mcp_server,
    main as mcp_main,
)
from standardsforge.service import StandardsForgeService  # noqa: E402
import validate_contracts  # noqa: E402
from validate_contracts import check_schema_documents, load_schemas, validate_with_schema  # noqa: E402


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


class QuerySelectorAdapterTests(unittest.TestCase):
    def test_cli_keeps_clause_reference_compatibility_and_forwards_record_id(self) -> None:
        legacy_args = cli_parser().parse_args(
            ["get-clause", "a" * 64, "4.2.1", "--principal", "local-user"]
        )
        record_args = cli_parser().parse_args(
            ["get-clause", "a" * 64, "--record-id", "record-421", "--principal", "local-user"]
        )
        service = Mock()
        service.get_clause.side_effect = [{"selector": "clause"}, {"selector": "record"}]

        with patch("standardsforge.cli.StandardsForgeService.open_read_only", return_value=service):
            self.assertEqual({"selector": "clause"}, cli_run(legacy_args))
            self.assertEqual({"selector": "record"}, cli_run(record_args))

        self.assertEqual(
            [
                unittest.mock.call(
                    "a" * 64,
                    "4.2.1",
                    "local-user",
                    max_bytes=None,
                    response_profile=None,
                    record_id=None,
                ),
                unittest.mock.call(
                    "a" * 64,
                    None,
                    "local-user",
                    max_bytes=None,
                    response_profile=None,
                    record_id="record-421",
                ),
            ],
            service.get_clause.call_args_list,
        )

    def test_cli_rejects_missing_or_blank_selectors(self) -> None:
        for argv in (
            ["get-clause", "a" * 64, "--principal", "local-user"],
            ["get-clause", "a" * 64, "--record-id", " ", "--principal", "local-user"],
        ):
            with self.subTest(argv=argv), patch("standardsforge.cli.StandardsForgeService"):
                with self.assertRaises(StandardsForgeError) as raised:
                    cli_run(cli_parser().parse_args(argv))
                self.assertEqual("invalid_selector", raised.exception.code)

    def test_mcp_record_selector_preserves_structured_and_text_envelopes(self) -> None:
        service = Mock()
        expected = {
            "schema_version": "0.1.0",
            "operation": "get_clause",
            "retrieval_mode": "exact_pinned_clause",
            "package": {},
            "evidence": [],
            "limitations": [],
            "budget": {},
        }
        service.get_clause.return_value = expected
        server = create_mcp_server(service, "local-user")

        async def scenario() -> None:
            async with Client(server, raise_exceptions=True) as client:
                success = await client.call_tool(
                    "get_clause",
                    {"package_digest": "a" * 64, "record_id": "record-421"},
                )
                missing = await client.call_tool("get_clause", {"package_digest": "a" * 64})

            self.assertFalse(success.is_error)
            self.assertEqual({"ok": True, "result": expected}, success.structured_content)
            self.assertEqual(success.structured_content, _text_payload(success))
            self.assertTrue(missing.is_error)
            self.assertEqual("invalid_selector", _text_payload(missing)["error"]["code"])

        _run_with_socket_creation_denied(scenario())
        service.get_clause.assert_called_once_with(
            "a" * 64,
            None,
            "local-user",
            max_bytes=None,
            response_profile=None,
            record_id="record-421",
        )


class StrictArgumentAdapterTests(unittest.TestCase):
    DIGEST = "a" * 64

    def _call_all(self, server, cases):
        results = []

        async def scenario() -> None:
            async with Client(server, raise_exceptions=True) as client:
                for name, arguments in cases:
                    results.append(await client.call_tool(name, arguments))

        _run_with_socket_creation_denied(scenario())
        return results

    def test_type_violations_and_extra_arguments_return_typed_envelope_without_service_calls(self) -> None:
        service = Mock()
        cases = [
            ("search", {"query": "x", "limit": True}, ["limit"]),
            ("search", {"query": "x", "limit": "5"}, ["limit"]),
            ("search", {"query": "x", "limit": 5.0}, ["limit"]),
            ("search", {"query": 5}, ["query"]),
            ("search", {"query": "x", "query_mode": "fuzzy"}, ["query_mode"]),
            ("search", {"query": "x", "principal_id": "admin", "principal": "admin"}, ["principal", "principal_id"]),
            ("search", {}, ["query"]),
            ("list_documents", {"limit": False}, ["limit"]),
            ("list_documents", {"result_mode": "structured_only"}, ["result_mode"]),
            ("resolve_document", {"identifier": ["EXAMPLE-SPEC-100"]}, ["identifier"]),
            ("get_clause", {"package_digest": self.DIGEST, "record_id": "r", "max_bytes": True}, ["max_bytes"]),
            ("get_clause", {"package_digest": 123, "record_id": "r"}, ["package_digest"]),
            ("build_context", {"package_digest": self.DIGEST, "clause_references": "4.2"}, ["clause_references"]),
            ("build_context", {"package_digest": self.DIGEST, "clause_references": '["4.2.1"]'}, ["clause_references"]),
            ("enumerate_obligations", {"package_digest": self.DIGEST, "limit": "50"}, ["limit"]),
            ("diff_editions", {"from_package_digest": self.DIGEST, "to_package_digest": self.DIGEST, "max_bytes": 1.5}, ["max_bytes"]),
            ("browse_records", {"package_digest": self.DIGEST, "limit": True}, ["limit"]),
            ("browse_records", {"package_digest": self.DIGEST, "relation": "siblings"}, ["relation"]),
            ("select_evidence", {"package_digest": self.DIGEST, "record_id": "r", "max_tokens": 10.0}, ["max_tokens"]),
            ("follow_references", {"package_digest": self.DIGEST, "record_id": "r", "principal_id": "admin"}, ["principal_id"]),
            ("get_source_pdfs", {"package_digest": self.DIGEST, "path": "/etc/passwd"}, ["path"]),
        ]
        envelopes = []
        for result_mode in ("text_and_structured", "structured_only"):
            server = create_mcp_server(service, "local-user", result_mode=result_mode)
            results = self._call_all(server, [(name, arguments) for name, arguments, _ in cases])
            for (name, arguments, fields), result in zip(cases, results):
                with self.subTest(result_mode=result_mode, tool=name, arguments=arguments):
                    self.assertTrue(result.is_error)
                    self.assertIsNone(result.structured_content)
                    payload = _text_payload(result)
                    self.assertEqual({"ok", "error"}, set(payload))
                    self.assertFalse(payload["ok"])
                    self.assertEqual("invalid_argument", payload["error"]["code"])
                    self.assertEqual(name, payload["error"]["details"]["tool"])
                    self.assertEqual(fields, payload["error"]["details"]["fields"])
                    self.assertNotIn("admin", result.content[0].text)
                    self.assertNotIn("passwd", result.content[0].text)
            envelopes.append([_text_payload(result) for result in results])
        self.assertEqual(envelopes[0], envelopes[1])
        self.assertEqual([], service.method_calls)

        schemas = load_schemas()
        registry = check_schema_documents(schemas)
        validate_with_schema(schemas, registry, "error-response.schema.json", envelopes[0][0])

    def test_valid_strings_are_passed_verbatim_and_never_json_pre_parsed(self) -> None:
        service = Mock()
        service.get_clause.side_effect = StandardsForgeError("not_found", "No authorized resource matches the request.")
        service.build_context.side_effect = StandardsForgeError("not_found", "No authorized resource matches the request.")
        server = create_mcp_server(service, "local-user")
        results = self._call_all(
            server,
            [
                ("get_clause", {"package_digest": self.DIGEST, "clause_reference": '["4.2.1"]', "record_id": "null"}),
                ("build_context", {"package_digest": self.DIGEST, "clause_references": ["4.2.1"], "max_bytes": 10}),
            ],
        )
        self.assertEqual(["not_found", "not_found"], [_text_payload(item)["error"]["code"] for item in results])
        service.get_clause.assert_called_once_with(
            self.DIGEST,
            '["4.2.1"]',
            "local-user",
            max_bytes=None,
            response_profile=None,
            record_id="null",
        )
        service.build_context.assert_called_once_with(
            self.DIGEST, ["4.2.1"], "local-user", max_bytes=10, response_profile=None
        )

    def test_unknown_tool_and_invalid_service_output_are_typed_envelopes(self) -> None:
        service = Mock()
        service.search.return_value = {"operation": "search"}
        server = create_mcp_server(service, "local-user")
        with self.assertLogs("standardsforge.mcp_server", level="ERROR"):
            unknown, malformed = self._call_all(
                server, [("install_pack", {"source": "x"}), ("search", {"query": "x"})]
            )
        self.assertTrue(unknown.is_error)
        self.assertEqual("unsupported_operation", _text_payload(unknown)["error"]["code"])
        self.assertTrue(malformed.is_error)
        self.assertEqual(
            {"ok": False, "error": {"code": "internal_error", "message": "The operation failed unexpectedly; no partial success is asserted."}},
            _text_payload(malformed),
        )

    def test_advertised_schemas_are_closed_and_strict(self) -> None:
        server = create_mcp_server(Mock(), "local-user")

        async def scenario():
            async with Client(server, raise_exceptions=True) as client:
                return await client.list_tools()

        listed = asyncio.run(scenario())
        for tool in listed.tools:
            self.assertIs(False, tool.input_schema.get("additionalProperties"), tool.name)
            for argument, schema in tool.input_schema["properties"].items():
                self.assertNotIn("number", json.dumps(schema), (tool.name, argument))

    def test_padded_startup_principal_is_rejected_not_stripped(self) -> None:
        for principal in (" local-user", "local-user ", "local-user\n", " ", "", "local\ud800user", "\udfff"):
            with self.subTest(principal=principal):
                with self.assertRaises(StandardsForgeError) as caught:
                    create_mcp_server(Mock(), principal)
                self.assertEqual("invalid_principal", caught.exception.code)


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
                self.assertEqual(MCP_SERVER_INSTRUCTIONS, client.instructions)
            self.assertEqual(list(MCP_TOOL_NAMES), [tool.name for tool in listed.tools])
            self.assertEqual(set(expected_arguments), {tool.name for tool in listed.tools})
            for tool in listed.tools:
                self.assertEqual(expected_arguments[tool.name], set(tool.input_schema["properties"]))
                self.assertEqual(MCP_TOOL_TITLES[tool.name], tool.title)
                self.assertEqual(MCP_TOOL_DESCRIPTIONS[tool.name], tool.description)
                contract_tool = next(item for item in contract["tools"] if item["name"] == tool.name)
                self.assertEqual(contract_tool["title"], tool.title)
                self.assertEqual(contract_tool["description"], tool.description)
                for argument, schema in tool.input_schema["properties"].items():
                    self.assertTrue(schema.get("description"), (tool.name, argument))
                    self.assertEqual(
                        contract_tool["argument_schemas"][argument]["description"],
                        schema["description"],
                    )
                self.assertNotIn("principal", tool.input_schema["properties"])
                self.assertNotIn("principal_id", tool.input_schema["properties"])
                self.assertNotIn("result_mode", tool.input_schema["properties"])
                self.assertEqual({"ok", "result"}, set(tool.output_schema["required"]))
                self.assertNotEqual(True, tool.output_schema.get("additionalProperties"))
                result_reference = tool.output_schema["properties"]["result"]["$ref"]
                result_schema = tool.output_schema["$defs"][result_reference.rsplit("/", 1)[-1]]
                self.assertIn("operation", result_schema["required"])
                self.assertEqual(
                    tool.name,
                    result_schema["properties"]["operation"]["const"],
                )
                if tool.name in {"get_clause", "build_context"}:
                    profile_schema = json.dumps(tool.input_schema["properties"]["response_profile"])
                    self.assertIn("compact_evidence_v1", profile_schema)
                    self.assertIn("concise_evidence_v1", profile_schema)
                    self.assertNotIn("response_profile", tool.input_schema.get("required", []))
                if tool.name == "get_clause":
                    self.assertIn("record_id", tool.input_schema["properties"])
                    self.assertNotIn("clause_reference", tool.input_schema.get("required", []))
                    self.assertNotIn("record_id", tool.input_schema.get("required", []))
                if tool.name == "search":
                    self.assertEqual(
                        ["exact_phrase", "all_terms", "any_terms", "natural_language", "concept_language"],
                        tool.input_schema["properties"]["query_mode"]["enum"],
                    )
                    self.assertEqual(
                        "all_terms",
                        tool.input_schema["properties"]["query_mode"]["default"],
                    )
                if tool.name == "diff_editions":
                    self.assertFalse(result_schema["additionalProperties"])
                    for definition_name in (
                        "_DiffAddedChange",
                        "_DiffRemovedChange",
                        "_DiffModifiedChange",
                        "_DiffMovedChange",
                        "_DiffUnchangedChange",
                        "_DiffAlignmentCandidate",
                        "_DiffDependencyImpact",
                        "_DiffDependencyEdge",
                        "_DiffEdgeCause",
                        "_DiffTargetCause",
                        "_DiffChangeCounts",
                        "_DiffEvidenceRecord",
                        "_DiffRecordDerivation",
                        "_DiffStructureSpan",
                        "_DiffStructureRelationship",
                        "_DiffSemanticStatement",
                        "_DiffSemanticQualifier",
                        "_DiffSemanticQuantity",
                        "_DiffSemanticRecord",
                        "_DiffReviewer",
                        "_DiffReviewTool",
                        "_DiffReviewEvent",
                        "_DiffUnreviewedStructure",
                        "_DiffReviewedStructure",
                        "_DiffSemanticStructure",
                    ):
                        self.assertFalse(
                            tool.output_schema["$defs"][definition_name]["additionalProperties"]
                        )
                    edge_schema = result_schema["properties"]["dependency_edges_added"][
                        "items"
                    ]
                    self.assertEqual(4, edge_schema["minItems"])
                    self.assertEqual(4, edge_schema["maxItems"])
                    self.assertEqual(
                        {"statement_role", "method", "review_status"},
                        set(
                            tool.output_schema["$defs"]["_DiffRecordDerivation"][
                                "required"
                            ]
                        ),
                    )
                self.assertTrue(tool.annotations.read_only_hint)
                self.assertFalse(tool.annotations.open_world_hint)

        _run_with_socket_creation_denied(scenario())

    def test_structured_only_mode_omits_duplicate_success_text(self) -> None:
        server = create_mcp_server(self.service, "local-user", result_mode="structured_only")
        expected = self.service.search("axial load", "local-user")

        async def scenario() -> None:
            async with Client(server, raise_exceptions=True) as client:
                result = await client.call_tool("search", {"query": "axial load"})

            self.assertFalse(result.is_error)
            self.assertEqual([], result.content)
            self.assertEqual({"ok": True, "result": expected}, result.structured_content)

        _run_with_socket_creation_denied(scenario())

    def test_structured_only_mode_preserves_text_error_envelope(self) -> None:
        results = []
        for result_mode in ("text_and_structured", "structured_only"):
            server = create_mcp_server(self.service, "local-user", result_mode=result_mode)

            async def scenario() -> None:
                async with Client(server, raise_exceptions=True) as client:
                    result = await client.call_tool("get_clause", {"package_digest": self.first_digest})
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content)
                results.append(_text_payload(result))

            _run_with_socket_creation_denied(scenario())

        self.assertEqual(results[0], results[1])
        self.assertEqual("invalid_selector", results[0]["error"]["code"])

    def test_invalid_argument_values_remain_typed_domain_errors(self) -> None:
        server = create_mcp_server(self.service, "local-user")
        cases = (
            ("search", {"query": "adapter", "limit": 0}, "invalid_limit"),
            (
                "build_context",
                {"package_digest": self.first_digest, "clause_references": []},
                "invalid_clause_reference",
            ),
            (
                "get_clause",
                {
                    "package_digest": self.first_digest,
                    "clause_reference": "4.2.1",
                    "max_bytes": 0,
                },
                "invalid_budget",
            ),
        )

        async def scenario() -> None:
            async with Client(server, raise_exceptions=True) as client:
                for name, arguments, expected_code in cases:
                    result = await client.call_tool(name, arguments)
                    self.assertTrue(result.is_error, name)
                    self.assertEqual(expected_code, _text_payload(result)["error"]["code"])

        _run_with_socket_creation_denied(scenario())

    def test_compact_profile_matches_core_packet_and_envelope(self) -> None:
        server = create_mcp_server(self.service, "local-user")
        cases = [
            (
                "get_clause",
                {
                    "package_digest": self.first_digest,
                    "clause_reference": "4.2.1",
                    "response_profile": "compact_evidence_v1",
                },
                self.service.get_clause(
                    self.first_digest, "4.2.1", "local-user", response_profile="compact_evidence_v1"
                ),
            ),
            (
                "build_context",
                {
                    "package_digest": self.first_digest,
                    "clause_references": ["4.2.1", "4.2.2", "4.2.1"],
                    "response_profile": "compact_evidence_v1",
                },
                self.service.build_context(
                    self.first_digest,
                    ["4.2.1", "4.2.2", "4.2.1"],
                    "local-user",
                    response_profile="compact_evidence_v1",
                ),
            ),
            (
                "get_clause",
                {
                    "package_digest": self.first_digest,
                    "clause_reference": "4.2.1",
                    "response_profile": "concise_evidence_v1",
                },
                self.service.get_clause(
                    self.first_digest, "4.2.1", "local-user", response_profile="concise_evidence_v1"
                ),
            ),
            (
                "build_context",
                {
                    "package_digest": self.first_digest,
                    "clause_references": ["4.2.1", "4.2.2"],
                    "response_profile": "concise_evidence_v1",
                },
                self.service.build_context(
                    self.first_digest,
                    ["4.2.1", "4.2.2"],
                    "local-user",
                    response_profile="concise_evidence_v1",
                ),
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

    def test_all_seven_operations_match_core_results_with_networking_denied(self) -> None:
        server = create_mcp_server(self.service, "local-user")
        cases = [
            (
                "search",
                {
                    "query": "axial ingress",
                    "package_digest": self.first_digest,
                    "scope_prefix": "4.2",
                    "query_mode": "any_terms",
                },
                self.service.search(
                    "axial ingress",
                    "local-user",
                    package_digest=self.first_digest,
                    scope_prefix="4.2",
                    query_mode="any_terms",
                ),
            ),
            (
                "list_documents",
                {"identifier_prefix": "EXAMPLE-SPEC", "limit": 50},
                self.service.list_documents("local-user", "EXAMPLE-SPEC", 50),
            ),
            (
                "resolve_document",
                {
                    "identifier": "EXAMPLE-SPEC-100",
                    "edition_id": "example:spec-100:2025-a",
                    "representation": "curated_records",
                },
                self.service.resolve_document(
                    "EXAMPLE-SPEC-100", "local-user", "example:spec-100:2025-a", "curated_records"
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
                self.assertTrue(search_result.is_error)
                self.assertNotIn(secret_principal, search_result.content[0].text)
                self.assertEqual("invalid_argument", _text_payload(search_result)["error"]["code"])

                denied = await client.call_tool(
                    "get_clause",
                    {"package_digest": self.first_digest, "clause_reference": "4.2.1"},
                )
                self.assertTrue(denied.is_error)
                payload = _text_payload(denied)
                self.assertEqual("not_found", payload["error"]["code"])
                self.assertNotIn(secret_principal, denied.content[0].text)

        asyncio.run(scenario())

    def test_registered_tools_match_contracts_exactly(self) -> None:
        server = create_mcp_server(self.service, "local-user")

        async def scenario():
            async with Client(server, raise_exceptions=True) as client:
                return await client.list_tools()

        listed = [(tool.name, tool.input_schema) for tool in asyncio.run(scenario()).tools]
        self.assertEqual([], validate_contracts.mcp_tool_contract_problems(listed))
        self.assertEqual("matched", validate_contracts.validate_mcp_tool_contracts()["status"])

        original_load = validate_contracts.load_json

        def drifted(mutate):
            def load(relative):
                document = copy.deepcopy(original_load(relative))
                mutate(relative, document)
                return document

            with patch.object(validate_contracts, "load_json", side_effect=load):
                return validate_contracts.mcp_tool_contract_problems(listed)

        def tool(document, name):
            return next(item for item in document["tools"] if item["name"] == name)

        def operation(document, name):
            return next(item for item in document["read_operations"] if item["name"] == name)

        mutations = {
            "default": lambda rel, doc: rel.endswith("mcp-tools.json")
            and tool(doc, "search")["argument_schemas"]["limit"].update(default=50),
            "enum": lambda rel, doc: rel.endswith("mcp-tools.json")
            and tool(doc, "browse_records")["argument_schemas"]["relation"]["enum"].pop(),
            "optional": lambda rel, doc: rel.endswith("mcp-tools.json")
            and tool(doc, "enumerate_obligations")["optional_arguments"].remove("cursor"),
            "required": lambda rel, doc: rel.endswith("mcp-tools.json")
            and tool(doc, "get_clause")["optional_arguments"].append("package_digest"),
            "read_operation": lambda rel, doc: rel.endswith("query-operations.json")
            and doc["read_operations"].remove(operation(doc, "get_source_pdfs")),
            "operation_optional": lambda rel, doc: rel.endswith("query-operations.json")
            and operation(doc, "search")["optional_arguments"].pop("limit"),
        }
        for label, mutate in mutations.items():
            with self.subTest(drift=label):
                self.assertTrue(drifted(mutate))

    def test_migrated_v1_unknown_statement_role_passes_mcp_output_validation(self) -> None:
        legacy = json.dumps(
            {"statement_role": "unknown", "method": "legacy_unknown", "review_status": "unreviewed"},
            sort_keys=True,
            separators=(",", ":"),
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE records SET derivation_json = ?, statement_role = 'unknown' WHERE package_digest = ?",
                (legacy, self.first_digest),
            )
        connection.close()
        read_only = StandardsForgeService.open_read_only(self.db_path, self.object_root)
        expected = read_only.diff_editions(self.first_digest, self.second_digest, "local-user")
        server = create_mcp_server(read_only, "local-user")

        async def scenario() -> None:
            async with Client(server, raise_exceptions=True) as client:
                result = await client.call_tool(
                    "diff_editions",
                    {"from_package_digest": self.first_digest, "to_package_digest": self.second_digest},
                )
            self.assertFalse(result.is_error, result.content)
            self.assertEqual({"ok": True, "result": expected}, result.structured_content)
            roles = {
                change["before"]["derivation"]["statement_role"]
                for change in result.structured_content["result"]["changes"]
                if "before" in change
            }
            self.assertEqual({"unknown"}, roles)

        _run_with_socket_creation_denied(scenario())

    def test_server_main_rejects_padded_principal_at_startup(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("standardsforge.mcp_server.MCPServer.run") as run:
            code = mcp_main(
                ["--db", str(self.db_path), "--store", str(self.object_root), "--principal", "local-user "]
            )
        self.assertEqual(2, code)
        run.assert_not_called()
        self.assertEqual("invalid_principal", json.loads(stderr.getvalue())["error"]["code"])

    def test_search_term_overflow_is_a_typed_mcp_error(self) -> None:
        server = create_mcp_server(self.service, "local-user")
        query = " ".join(f"term{index}" for index in range(33))

        async def scenario() -> None:
            async with Client(server, raise_exceptions=True) as client:
                result = await client.call_tool("search", {"query": query})

            self.assertTrue(result.is_error)
            payload = _text_payload(result)
            self.assertEqual("invalid_query", payload["error"]["code"])
            self.assertEqual({"max_terms": 32, "actual_terms": 33}, payload["error"]["details"])

        _run_with_socket_creation_denied(scenario())

    def test_stdio_subprocess_round_trip(self) -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
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
            self.assertEqual(result.structured_content, _text_payload(result))
            self.assertEqual("search", result.structured_content["result"]["operation"])
            hit = result.structured_content["result"]["results"][0]
            self.assertEqual(self.first_digest, hit["package_digest"])
            self.assertEqual("sources/example-spec-100a.txt", hit["source"]["path"])
            self.assertIn("⟦", hit["matched_snippet"])
            self.assertIn("⟧", hit["matched_snippet"])
            self.assertEqual(
                {"start": "⟦", "end": "⟧"},
                result.structured_content["result"]["snippet_markers"],
            )
            self.assertNotIn("heading_ancestry", hit)

        asyncio.run(scenario())

    def test_stdio_subprocess_structured_only_mode(self) -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            args=[
                "-m",
                "standardsforge.mcp_server",
                "--db",
                str(self.db_path),
                "--store",
                str(self.object_root),
                "--principal",
                "local-user",
                "--result-mode",
                "structured_only",
            ],
        )

        async def scenario() -> None:
            async with Client(parameters) as client:
                result = await client.call_tool("search", {"query": "axial load"})
            self.assertFalse(result.is_error)
            self.assertEqual([], result.content)
            self.assertEqual("search", result.structured_content["result"]["operation"])
            self.assertEqual(self.first_digest, result.structured_content["result"]["results"][0]["package_digest"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
