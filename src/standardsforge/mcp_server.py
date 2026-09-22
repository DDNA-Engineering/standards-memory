from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Sequence

from mcp.server import MCPServer
from mcp.server._otel import OpenTelemetryMiddleware
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from . import __version__
from .errors import StandardsForgeError, require
from .service import StandardsForgeService


MCP_TOOL_NAMES = (
    "search",
    "list_documents",
    "resolve_document",
    "get_clause",
    "build_context",
    "enumerate_obligations",
    "diff_editions",
)
MCP_SERVER_INSTRUCTIONS = (
    "Read MIL-STDs as edition-pinned evidence, not as free-floating prose. If the exact identifier is unknown, "
    "list the authorized installed documents first. Then resolve the exact "
    "identifier, edition, and representation; never combine editions or silently choose among representations. "
    "Use reviewed_structure or curated_records only for their declared reviewed scope, derived_structure only "
    "as automated unreviewed navigation, and page_text as physical extracted text. Search is discovery, not "
    "applicability or completeness: pin a returned package digest and retrieve exact evidence before answering. "
    "Read the selected text together with returned governing context, conditions, exceptions, notes, table or "
    "figure references, source citations, derivation status, and coverage. For MIL-STDs, distinguish scope, "
    "tailoring, referenced documents, definitions, requirements, and verification or test methods; preserve "
    "notice and revision composition. The word 'shall' can mark normative wording but does not establish project "
    "applicability; applicability and compliance require an external approved baseline and human authority. "
    "enumerate_obligations covers only explicitly classified records, so zero results with incomplete "
    "classification does not mean the standard has no requirements. Never upgrade automated or unreviewed "
    "derivations into confirmed requirements or approval. Administrative operations are not exposed."
)
MCP_TOOL_DESCRIPTIONS = {
    "search": (
        "Discover authorized records by local lexical search. Results include identifier, edition_id, and package_digest "
        "for replay; they are candidates, not applicability, "
        "obligation completeness, or exact document identity; use resolve_document for an identifier and replay "
        "a selected evidence_selector through get_clause."
    ),
    "list_documents": (
        "List authorized installed document packages with exact identity, representation, immutable package digest, "
        "record count, and declared coverage. Optional normalized identifier-prefix filtering and signed pagination "
        "remain bound to the startup principal; current publisher status does not establish a project baseline."
    ),
    "resolve_document": (
        "Resolve an exact authorized identifier, optional edition, and representation to an immutable package "
        "digest. Specify representation when ambiguous: derived_structure is automated and unreviewed, while "
        "page_text is physical extracted text."
    ),
    "get_clause": (
        "Retrieve one exact package-pinned record and its required evidence context. Interpret exact text with "
        "citations, relationships, derivation review status, and coverage; this does not decide applicability or compliance."
    ),
    "build_context": (
        "Retrieve multiple exact package-pinned records with their deduplicated required context. Preserve "
        "conditions, exceptions, notes, and unresolved relationships; the packet is evidence, not an approval decision."
    ),
    "enumerate_obligations": (
        "Traverse only records explicitly classified as obligations in one immutable package. Always inspect "
        "classification and source-interpretation coverage: zero classified rows is not proof of zero requirements."
    ),
    "diff_editions": (
        "Compare two authorized immutable packages by record identity and dependency context. Report evidence "
        "changes without inferring engineering impact, applicability, supersession, or compliance."
    ),
}

StructuredToolResult = Annotated[CallToolResult, dict[str, Any]]
MCPResultMode = Literal["text_and_structured", "structured_only"]


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _invoke(
    operation: Callable[[], dict[str, Any]],
    *,
    result_mode: MCPResultMode,
) -> CallToolResult:
    try:
        payload = {"ok": True, "result": operation()}
        return CallToolResult(
            content=(
                [TextContent(type="text", text=_json(payload))]
                if result_mode == "text_and_structured"
                else []
            ),
            structured_content=payload,
        )
    except StandardsForgeError as exc:
        payload = {"ok": False, "error": exc.as_dict()}
    except Exception:
        payload = {
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": "The operation failed unexpectedly; no partial success is asserted.",
            },
        }
    return CallToolResult(
        content=[TextContent(type="text", text=_json(payload))],
        is_error=True,
    )


def _disable_telemetry(server: MCPServer[Any]) -> None:
    """Remove the pinned SDK's provisional tracing middleware.

    This is intentionally explicit. A no-op exporter is insufficient because a host
    process could configure OpenTelemetry before constructing the local server.
    """

    server._lowlevel_server.middleware[:] = [
        middleware
        for middleware in server._lowlevel_server.middleware
        if not isinstance(middleware, OpenTelemetryMiddleware)
    ]


def create_mcp_server(
    service: StandardsForgeService,
    principal_id: str,
    result_mode: MCPResultMode = "text_and_structured",
) -> MCPServer[Any]:
    require(
        isinstance(principal_id, str) and bool(principal_id.strip()),
        "invalid_principal",
        "A non-empty startup principal is required.",
    )
    require(
        result_mode in ("text_and_structured", "structured_only"),
        "invalid_result_mode",
        "The MCP result mode is unsupported.",
        result_mode=result_mode,
    )
    bound_principal = principal_id.strip()
    server: MCPServer[Any] = MCPServer(
        "standardsforge",
        description="Read-only, offline access to locally authorized standards evidence.",
        instructions=MCP_SERVER_INSTRUCTIONS,
        version=__version__,
        log_level="WARNING",
    )
    _disable_telemetry(server)
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)

    @server.tool(description=MCP_TOOL_DESCRIPTIONS["search"], annotations=read_only)
    def search(
        query: str,
        limit: int = 20,
        package_digest: str | None = None,
        scope_prefix: str | None = None,
    ) -> StructuredToolResult:
        return _invoke(
            lambda: service.search(
                query,
                bound_principal,
                limit,
                package_digest=package_digest,
                scope_prefix=scope_prefix,
            ),
            result_mode=result_mode,
        )

    @server.tool(description=MCP_TOOL_DESCRIPTIONS["list_documents"], annotations=read_only)
    def list_documents(
        identifier_prefix: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> StructuredToolResult:
        return _invoke(
            lambda: service.list_documents(bound_principal, identifier_prefix, limit, cursor),
            result_mode=result_mode,
        )

    @server.tool(description=MCP_TOOL_DESCRIPTIONS["resolve_document"], annotations=read_only)
    def resolve_document(
        identifier: str,
        edition_id: str | None = None,
        representation: Literal["page_text", "derived_structure", "reviewed_structure", "curated_records"] | None = None,
    ) -> StructuredToolResult:
        return _invoke(
            lambda: service.resolve_document(identifier, bound_principal, edition_id, representation),
            result_mode=result_mode,
        )

    @server.tool(description=MCP_TOOL_DESCRIPTIONS["get_clause"], annotations=read_only)
    def get_clause(
        package_digest: str,
        clause_reference: str | None = None,
        record_id: str | None = None,
        max_bytes: int | None = None,
        response_profile: Literal["compact_evidence_v1", "concise_evidence_v1"] | None = None,
    ) -> StructuredToolResult:
        def retrieve() -> dict[str, Any]:
            for name, value in (
                ("clause_reference", clause_reference),
                ("record_id", record_id),
            ):
                require(
                    value is None or bool(value.strip()),
                    "invalid_selector",
                    f"{name} must be a non-empty string when supplied.",
                )
            require(
                clause_reference is not None or record_id is not None,
                "invalid_selector",
                "get_clause requires clause_reference, record_id, or both.",
            )
            return service.get_clause(
                package_digest,
                clause_reference,
                bound_principal,
                max_bytes=max_bytes,
                response_profile=response_profile,
                record_id=record_id,
            )

        return _invoke(retrieve, result_mode=result_mode)

    @server.tool(description=MCP_TOOL_DESCRIPTIONS["build_context"], annotations=read_only)
    def build_context(
        package_digest: str,
        clause_references: list[str],
        max_bytes: int | None = None,
        response_profile: Literal["compact_evidence_v1", "concise_evidence_v1"] | None = None,
    ) -> StructuredToolResult:
        return _invoke(
            lambda: service.build_context(
                package_digest,
                clause_references,
                bound_principal,
                max_bytes=max_bytes,
                response_profile=response_profile,
            ),
            result_mode=result_mode,
        )

    @server.tool(description=MCP_TOOL_DESCRIPTIONS["enumerate_obligations"], annotations=read_only)
    def enumerate_obligations(
        package_digest: str,
        scope_prefix: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        max_bytes: int | None = None,
    ) -> StructuredToolResult:
        return _invoke(
            lambda: service.enumerate_obligations(
                package_digest,
                bound_principal,
                scope_prefix,
                limit,
                cursor,
                max_bytes,
            ),
            result_mode=result_mode,
        )

    @server.tool(description=MCP_TOOL_DESCRIPTIONS["diff_editions"], annotations=read_only)
    def diff_editions(
        from_package_digest: str,
        to_package_digest: str,
        max_bytes: int | None = None,
    ) -> StructuredToolResult:
        return _invoke(
            lambda: service.diff_editions(
                from_package_digest,
                to_package_digest,
                bound_principal,
                max_bytes,
            ),
            result_mode=result_mode,
        )

    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="standardsforge-mcp",
        description="Local read-only StandardsForge MCP server over stdio",
    )
    parser.add_argument("--db", default=".standardsforge/memory.db", help="SQLite metadata database")
    parser.add_argument("--store", default=".standardsforge/objects", help="Immutable object directory")
    parser.add_argument(
        "--principal",
        required=True,
        help="Trusted local principal bound to every tool call (never exposed as a tool argument)",
    )
    parser.add_argument(
        "--result-mode",
        choices=("text_and_structured", "structured_only"),
        default="text_and_structured",
        help=(
            "MCP success encoding; structured_only omits the duplicate text payload "
            "(default: text_and_structured)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        service = StandardsForgeService(Path(args.db), Path(args.store))
        server = create_mcp_server(service, args.principal, result_mode=args.result_mode)
    except StandardsForgeError as exc:
        print(_json({"ok": False, "error": exc.as_dict()}), file=sys.stderr)
        return 2
    except Exception:
        print(
            _json(
                {
                    "ok": False,
                    "error": {
                        "code": "server_startup_error",
                        "message": "The local MCP server could not start.",
                    },
                }
            ),
            file=sys.stderr,
        )
        return 1
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
