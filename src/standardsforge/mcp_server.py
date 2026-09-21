from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Annotated, Any, Callable, Sequence

from mcp.server import MCPServer
from mcp.server._otel import OpenTelemetryMiddleware
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from . import __version__
from .errors import StandardsForgeError, require
from .service import StandardsForgeService


MCP_TOOL_NAMES = (
    "search",
    "resolve_document",
    "get_clause",
    "build_context",
    "enumerate_obligations",
    "diff_editions",
)

StructuredToolResult = Annotated[CallToolResult, dict[str, Any]]


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _invoke(operation: Callable[[], dict[str, Any]]) -> CallToolResult:
    try:
        payload = {"ok": True, "result": operation()}
        return CallToolResult(
            content=[TextContent(type="text", text=_json(payload))],
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


def create_mcp_server(service: StandardsForgeService, principal_id: str) -> MCPServer[Any]:
    """Create a local stdio-only MCP surface bound to one trusted principal."""

    require(
        isinstance(principal_id, str) and bool(principal_id.strip()),
        "invalid_principal",
        "A non-empty startup principal is required.",
    )
    bound_principal = principal_id.strip()
    server: MCPServer[Any] = MCPServer(
        "standardsforge",
        description="Read-only, offline access to locally authorized standards evidence.",
        instructions=(
            "Use package digests as immutable pins. Results are evidence, not applicability, "
            "compliance, or approval decisions. Administrative operations are not exposed."
        ),
        version=__version__,
        log_level="WARNING",
    )
    _disable_telemetry(server)
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)

    @server.tool(annotations=read_only)
    def search(query: str, limit: int = 20) -> StructuredToolResult:
        """Search authorized installed records using deterministic local lexical retrieval."""

        return _invoke(lambda: service.search(query, bound_principal, limit))

    @server.tool(annotations=read_only)
    def resolve_document(identifier: str, edition_id: str | None = None) -> StructuredToolResult:
        """Resolve an exact authorized document identity to an immutable package digest."""

        return _invoke(lambda: service.resolve_document(identifier, bound_principal, edition_id))

    @server.tool(annotations=read_only)
    def get_clause(
        package_digest: str,
        clause_reference: str,
        max_bytes: int | None = None,
    ) -> StructuredToolResult:
        """Retrieve one pinned clause with every required governing dependency."""

        return _invoke(
            lambda: service.get_clause(package_digest, clause_reference, bound_principal, max_bytes)
        )

    @server.tool(annotations=read_only)
    def build_context(
        package_digest: str,
        clause_references: list[str],
        max_bytes: int | None = None,
    ) -> StructuredToolResult:
        """Assemble dependency-complete evidence for multiple clauses in one pinned package."""

        return _invoke(
            lambda: service.build_context(package_digest, clause_references, bound_principal, max_bytes)
        )

    @server.tool(annotations=read_only)
    def enumerate_obligations(
        package_digest: str,
        scope_prefix: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        max_bytes: int | None = None,
    ) -> StructuredToolResult:
        """Traverse explicitly classified obligations with policy-bound stable pagination."""

        return _invoke(
            lambda: service.enumerate_obligations(
                package_digest,
                bound_principal,
                scope_prefix,
                limit,
                cursor,
                max_bytes,
            )
        )

    @server.tool(annotations=read_only)
    def diff_editions(
        from_package_digest: str,
        to_package_digest: str,
        max_bytes: int | None = None,
    ) -> StructuredToolResult:
        """Compare two authorized editions by exact record identity and dependency context."""

        return _invoke(
            lambda: service.diff_editions(
                from_package_digest,
                to_package_digest,
                bound_principal,
                max_bytes,
            )
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        service = StandardsForgeService(Path(args.db), Path(args.store))
        server = create_mcp_server(service, args.principal)
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
