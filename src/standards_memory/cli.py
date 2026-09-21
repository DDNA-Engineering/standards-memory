from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .errors import StandardsMemoryError
from .service import StandardsMemoryService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="standards-memory", description="Offline-first standards evidence engine")
    parser.add_argument("--db", default=".standards-memory/memory.db", help="SQLite metadata database")
    parser.add_argument("--store", default=".standards-memory/objects", help="Immutable object directory")
    commands = parser.add_subparsers(dest="command", required=True)

    verify = commands.add_parser("verify-pack", help="Validate a data-only pack without installing it")
    verify.add_argument("source")

    install = commands.add_parser("install", help="Administrative: validate and install a locally authorized pack")
    install.add_argument("source")
    install.add_argument("--policy", required=True, help="Trusted local operator policy JSON")

    resolve = commands.add_parser("resolve", help="Read-only: resolve an exact document identity")
    resolve.add_argument("identifier")
    resolve.add_argument("--edition")
    resolve.add_argument("--principal", required=True)

    get_clause = commands.add_parser("get-clause", help="Read-only: retrieve a pinned clause and required context")
    get_clause.add_argument("package_digest")
    get_clause.add_argument("clause_reference")
    get_clause.add_argument("--principal", required=True)
    get_clause.add_argument("--max-bytes", type=int)

    build_context = commands.add_parser("build-context", help="Read-only: assemble dependency-complete evidence for clauses")
    build_context.add_argument("package_digest")
    build_context.add_argument("clause_references", nargs="+")
    build_context.add_argument("--principal", required=True)
    build_context.add_argument("--max-bytes", type=int)

    enumerate_obligations = commands.add_parser(
        "enumerate-obligations", help="Read-only: traverse every declared obligation in a pinned scope"
    )
    enumerate_obligations.add_argument("package_digest")
    enumerate_obligations.add_argument("--principal", required=True)
    enumerate_obligations.add_argument("--scope")
    enumerate_obligations.add_argument("--limit", type=int, default=50)
    enumerate_obligations.add_argument("--cursor")
    enumerate_obligations.add_argument("--max-bytes", type=int)

    diff_editions = commands.add_parser("diff-editions", help="Read-only: compare two authorized package editions")
    diff_editions.add_argument("from_package_digest")
    diff_editions.add_argument("to_package_digest")
    diff_editions.add_argument("--principal", required=True)
    diff_editions.add_argument("--max-bytes", type=int)

    search = commands.add_parser("search", help="Read-only: lexical discovery over authorized installed records")
    search.add_argument("query")
    search.add_argument("--principal", required=True)
    search.add_argument("--limit", type=int, default=20)

    revoke = commands.add_parser("revoke", help="Administrative: immediately revoke a principal's package grant")
    revoke.add_argument("package_digest")
    revoke.add_argument("--principal", required=True)
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    service = StandardsMemoryService(Path(args.db), Path(args.store))
    if args.command == "verify-pack":
        return service.verify_pack(args.source)
    if args.command == "install":
        return service.install_pack(args.source, args.policy)
    if args.command == "resolve":
        return service.resolve_document(args.identifier, args.principal, args.edition)
    if args.command == "get-clause":
        return service.get_clause(args.package_digest, args.clause_reference, args.principal, args.max_bytes)
    if args.command == "build-context":
        return service.build_context(args.package_digest, args.clause_references, args.principal, args.max_bytes)
    if args.command == "enumerate-obligations":
        return service.enumerate_obligations(
            args.package_digest, args.principal, args.scope, args.limit, args.cursor, args.max_bytes
        )
    if args.command == "diff-editions":
        return service.diff_editions(
            args.from_package_digest, args.to_package_digest, args.principal, args.max_bytes
        )
    if args.command == "search":
        return service.search(args.query, args.principal, args.limit)
    if args.command == "revoke":
        return service.revoke(args.package_digest, args.principal)
    raise StandardsMemoryError("unsupported_operation", "The requested operation is not implemented.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = _run(args)
    except StandardsMemoryError as exc:
        print(json.dumps({"ok": False, "error": exc.as_dict()}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "internal_error",
                        "message": "The operation failed unexpectedly; no partial success is asserted.",
                    },
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"ok": True, "result": result}, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
