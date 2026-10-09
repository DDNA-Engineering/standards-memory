from __future__ import annotations

import argparse
import asyncio
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


EXPECTED_TOOLS = [
    "search",
    "list_documents",
    "resolve_document",
    "get_clause",
    "build_context",
    "enumerate_obligations",
    "diff_editions",
    "browse_records",
    "select_evidence",
    "follow_references",
    "get_source_pdfs",
]


async def _smoke(db: str, store: str, principal: str, query: str, launcher: str | None = None,
                 server_options: list[str] | None = None, tokens: bool = False) -> None:
    direct = StdioServerParameters(
        command=sys.executable,
        args=[
            "-I",
            "-m",
            "standardsforge.mcp_server",
            "--db",
            db,
            "--store",
            store,
            "--principal",
            principal,
            "--result-mode",
            "structured_only",
            *(server_options or []),
        ],
    )
    await _smoke_server(direct, query, tokens)
    if launcher is not None:
        # The launcher is qualified in addition to, never instead of, the direct server.
        await _smoke_server(StdioServerParameters(command=sys.executable, args=["-I", launcher]), query, tokens)


async def _smoke_server(parameters: StdioServerParameters, query: str, tokens: bool = False) -> None:
    async with Client(parameters, raise_exceptions=True) as client:
        tools = await client.list_tools()
        if [tool.name for tool in tools.tools] != EXPECTED_TOOLS:
            raise RuntimeError("The prepared MCP server exposed an unexpected tool surface.")
        inventory = await client.call_tool("list_documents", {"limit": 1})
        if inventory.is_error or inventory.structured_content is None:
            raise RuntimeError("The prepared MCP server document-inventory smoke failed.")
        inventory_result = inventory.structured_content.get("result", {})
        if not inventory_result.get("documents") or inventory_result.get("page", {}).get("matching_authorized_package_count", 0) < 1:
            raise RuntimeError("The prepared MCP server has no authorized installed documents.")
        result = await client.call_tool("search", {"query": query, "limit": 1})
        if result.is_error or result.structured_content is None:
            raise RuntimeError("The prepared MCP server search smoke failed.")
        results = result.structured_content.get("result", {}).get("results")
        if not results:
            raise RuntimeError("The prepared MCP server search returned no authorized evidence.")
        if tokens:
            selector = results[0].get("evidence_selector", {})
            selected = await client.call_tool("select_evidence", {
                "package_digest": selector.get("package_digest"), "record_id": selector.get("record_id"), "max_tokens": 100000})
            if selected.is_error or selected.structured_content is None or selected.structured_content.get("ok") is not True:
                raise RuntimeError("The prepared MCP server could not select evidence under a token budget.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--launcher", help="Also qualify the generated host launcher after setup completes.")
    parser.add_argument("--tokenizer-artifact")
    parser.add_argument("--tokenizer-sha256")
    parser.add_argument("--reference-bindings")
    parser.add_argument("--reference-bindings-sha256")
    args = parser.parse_args()
    options: list[str] = []
    for name in ("tokenizer_artifact", "tokenizer_sha256", "reference_bindings", "reference_bindings_sha256"):
        value = getattr(args, name)
        if value is not None:
            options += ["--" + name.replace("_", "-"), value]
    asyncio.run(_smoke(args.db, args.store, args.principal, args.query, args.launcher,
                       options, tokens=args.tokenizer_artifact is not None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
