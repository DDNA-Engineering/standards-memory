from __future__ import annotations

import argparse
import asyncio
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


EXPECTED_TOOLS = [
    "search",
    "resolve_document",
    "get_clause",
    "build_context",
    "enumerate_obligations",
    "diff_editions",
]


async def _smoke(db: str, store: str, principal: str, query: str) -> None:
    parameters = StdioServerParameters(
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
        ],
    )
    async with Client(parameters, raise_exceptions=True) as client:
        tools = await client.list_tools()
        if [tool.name for tool in tools.tools] != EXPECTED_TOOLS:
            raise RuntimeError("The prepared MCP server exposed an unexpected tool surface.")
        result = await client.call_tool("search", {"query": query, "limit": 1})
        if result.is_error or result.structured_content is None:
            raise RuntimeError("The prepared MCP server search smoke failed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--query", required=True)
    args = parser.parse_args()
    asyncio.run(_smoke(args.db, args.store, args.principal, args.query))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
