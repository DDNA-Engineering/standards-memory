from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Sequence

from mcp.server import MCPServer
from mcp.server._otel import OpenTelemetryMiddleware
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

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
MCP_TOOL_TITLES = {
    "search": "Search standards evidence",
    "list_documents": "List installed standards",
    "resolve_document": "Resolve a standard edition",
    "get_clause": "Get exact clause evidence",
    "build_context": "Build clause context",
    "enumerate_obligations": "Enumerate classified obligations",
    "diff_editions": "Compare standard editions",
}
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
        "Discover authorized records by explicit local lexical mode: exact_phrase preserves token order and adjacency, "
        "all_terms requires every parsed term, any_terms accepts at least one, and natural_language uses bounded "
        "stemming with a disclosed one-step relaxation when its strict match is empty. Results include identifier, "
        "edition_id, and package_digest for replay; they are candidates, not applicability, "
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

    @server.tool(title=MCP_TOOL_TITLES["search"], description=MCP_TOOL_DESCRIPTIONS["search"], annotations=read_only)
    def search(
        query: Annotated[str, Field(description="Search text; parsed locally and never sent to a network service.")],
        limit: Annotated[int, Field(description="Maximum records to return, from 1 through 100.")] = 20,
        package_digest: Annotated[str | None, Field(description="Optional exact authorized package SHA-256 pin.")] = None,
        scope_prefix: Annotated[str | None, Field(description="Optional exact clause reference or dot-delimited descendant scope.")] = None,
        query_mode: Annotated[
            Literal["exact_phrase", "all_terms", "any_terms", "natural_language"],
            Field(description="Explicit lexical interpretation; natural_language applies bounded stemming and discloses any fallback."),
        ] = "all_terms",
    ) -> StructuredToolResult:
        return _invoke(
            lambda: service.search(
                query,
                bound_principal,
                limit,
                package_digest=package_digest,
                scope_prefix=scope_prefix,
                query_mode=query_mode,
            ),
            result_mode=result_mode,
        )

    @server.tool(title=MCP_TOOL_TITLES["list_documents"], description=MCP_TOOL_DESCRIPTIONS["list_documents"], annotations=read_only)
    def list_documents(
        identifier_prefix: Annotated[str | None, Field(description="Optional normalized document-identifier prefix filter.")] = None,
        limit: Annotated[int, Field(description="Maximum documents to return, from 1 through 100.")] = 50,
        cursor: Annotated[str | None, Field(description="Optional opaque signed cursor from the preceding page.")] = None,
    ) -> StructuredToolResult:
        return _invoke(
            lambda: service.list_documents(bound_principal, identifier_prefix, limit, cursor),
            result_mode=result_mode,
        )

    @server.tool(title=MCP_TOOL_TITLES["resolve_document"], description=MCP_TOOL_DESCRIPTIONS["resolve_document"], annotations=read_only)
    def resolve_document(
        identifier: Annotated[str, Field(description="Exact document identifier to resolve; no fuzzy identifier matching.")],
        edition_id: Annotated[str | None, Field(description="Optional exact edition identity when more than one is installed.")] = None,
        representation: Annotated[
            Literal["page_text", "derived_structure", "reviewed_structure", "curated_records"] | None,
            Field(description="Optional exact representation; required when the identifier and edition are ambiguous."),
        ] = None,
    ) -> StructuredToolResult:
        return _invoke(
            lambda: service.resolve_document(identifier, bound_principal, edition_id, representation),
            result_mode=result_mode,
        )

    @server.tool(title=MCP_TOOL_TITLES["get_clause"], description=MCP_TOOL_DESCRIPTIONS["get_clause"], annotations=read_only)
    def get_clause(
        package_digest: Annotated[str, Field(description="Exact authorized package SHA-256 pin returned by resolution or search.")],
        clause_reference: Annotated[str | None, Field(description="Exact clause reference selector; supply this, record_id, or both.")] = None,
        record_id: Annotated[str | None, Field(description="Exact stable record selector; supply this, clause_reference, or both.")] = None,
        max_bytes: Annotated[int | None, Field(description="Optional positive response budget in UTF-8 bytes.")] = None,
        response_profile: Annotated[
            Literal["compact_evidence_v1", "concise_evidence_v1"] | None,
            Field(description="Optional deterministic evidence projection; omission returns the full packet."),
        ] = None,
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

    @server.tool(title=MCP_TOOL_TITLES["build_context"], description=MCP_TOOL_DESCRIPTIONS["build_context"], annotations=read_only)
    def build_context(
        package_digest: Annotated[str, Field(description="Exact authorized package SHA-256 pin.")],
        clause_references: Annotated[list[str], Field(description="One or more exact clause references whose required context is assembled.")],
        max_bytes: Annotated[int | None, Field(description="Optional positive response budget in UTF-8 bytes.")] = None,
        response_profile: Annotated[
            Literal["compact_evidence_v1", "concise_evidence_v1"] | None,
            Field(description="Optional deterministic evidence projection; omission returns the full packet."),
        ] = None,
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

    @server.tool(title=MCP_TOOL_TITLES["enumerate_obligations"], description=MCP_TOOL_DESCRIPTIONS["enumerate_obligations"], annotations=read_only)
    def enumerate_obligations(
        package_digest: Annotated[str, Field(description="Exact authorized package SHA-256 pin.")],
        scope_prefix: Annotated[str | None, Field(description="Optional exact clause reference or dot-delimited descendant scope.")] = None,
        limit: Annotated[int, Field(description="Maximum obligations to return, from 1 through 100.")] = 50,
        cursor: Annotated[str | None, Field(description="Optional opaque signed cursor from the preceding page.")] = None,
        max_bytes: Annotated[int | None, Field(description="Optional positive response budget in UTF-8 bytes.")] = None,
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

    @server.tool(title=MCP_TOOL_TITLES["diff_editions"], description=MCP_TOOL_DESCRIPTIONS["diff_editions"], annotations=read_only)
    def diff_editions(
        from_package_digest: Annotated[str, Field(description="Exact authorized baseline package SHA-256 pin.")],
        to_package_digest: Annotated[str, Field(description="Exact authorized comparison package SHA-256 pin.")],
        max_bytes: Annotated[int | None, Field(description="Optional positive response budget in UTF-8 bytes.")] = None,
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
