from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .acquisition import acquire_active_mil_stds, verify_mil_std_acquisition
from .compiler import compile_pdf_to_pack
from .corpus_compiler import compile_mil_std_corpus, install_compiled_corpus, write_corpus_policy
from .errors import StandardsForgeError, require
from .outline_compiler import compile_derived_outline_pack
from .pack import write_pack_archive
from .policy import write_pack_policy
from .service import StandardsForgeService
from .source_catalog import verify_source_set
from .structure_compiler import compile_structured_pdf_section


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="standardsforge", description="Offline-first standards evidence engine")
    parser.add_argument("--db", default=".standardsforge/memory.db", help="SQLite metadata database")
    parser.add_argument("--store", default=".standardsforge/objects", help="Immutable object directory")
    commands = parser.add_subparsers(dest="command", required=True)

    verify = commands.add_parser("verify-pack", help="Validate a data-only pack without installing it")
    verify.add_argument("source")

    archive = commands.add_parser("archive-pack", help="Administrative: write a deterministic compressed pack archive")
    archive.add_argument("source")
    archive.add_argument("destination")
    archive.add_argument("--compresslevel", type=int, choices=range(1, 10), default=6)

    verify_sources = commands.add_parser(
        "verify-source-set", help="Administrative: verify local source PDFs against a tracked catalog"
    )
    verify_sources.add_argument("catalog")
    verify_sources.add_argument("--source-root", default=".standardsforge/sources/dla")

    compile_pdf = commands.add_parser(
        "compile-pdf", help="Administrative: compile one verified PDF into a page-indexed data-only pack"
    )
    compile_pdf.add_argument("catalog")
    compile_pdf.add_argument("document_id")
    compile_pdf.add_argument("output_directory")
    compile_pdf.add_argument("--source-root", required=True)

    compile_corpus = commands.add_parser(
        "compile-mil-std-corpus",
        help="Administrative: compile every verified downloaded DLA current MIL-STD component into record-scoped compressed packs",
    )
    compile_corpus.add_argument("manifest")
    compile_corpus.add_argument("output_root")
    compile_corpus.add_argument("--source-root", required=True)
    compile_corpus.add_argument("--compresslevel", type=int, choices=range(1, 10), default=6)

    corpus_policy = commands.add_parser(
        "write-corpus-policy",
        help="Administrative: write an exact trusted local pack allowlist for a completed corpus",
    )
    corpus_policy.add_argument("index")
    corpus_policy.add_argument("output")
    corpus_policy.add_argument("--principal", required=True)

    pack_policy = commands.add_parser(
        "write-pack-policy",
        help="Administrative: write an exact trusted local policy for one validated pack",
    )
    pack_policy.add_argument("source")
    pack_policy.add_argument("output")
    pack_policy.add_argument("--principal", required=True)
    pack_policy.add_argument(
        "--content-class",
        required=True,
        help="Operator-confirmed content class; must match the validated pack claim",
    )

    install_corpus = commands.add_parser(
        "install-corpus",
        help="Administrative: validate and install every pack in a completed corpus under one trusted policy",
    )
    install_corpus.add_argument("index")
    install_corpus.add_argument("--policy", required=True)

    compile_structure = commands.add_parser(
        "compile-structure",
        help="Administrative: compile reviewed structural annotations for a verified PDF section",
    )
    compile_structure.add_argument("catalog")
    compile_structure.add_argument("document_id")
    compile_structure.add_argument("annotations")
    compile_structure.add_argument("output_directory")
    compile_structure.add_argument("--source-root", required=True)

    compile_outline = commands.add_parser(
        "compile-derived-outline",
        help="Administrative: derive unreviewed structural outline candidates from a verified page-text pack",
    )
    compile_outline.add_argument("source_pack")
    compile_outline.add_argument("output_directory")

    acquire = commands.add_parser(
        "acquire-mil-std",
        help="Administrative: inventory and download every current publicly exposed active MIL-STD from DLA",
    )
    acquire.add_argument("--output-root", default=".standardsforge/sources/dla/mil-std")
    acquire.add_argument("--manifest")
    acquire.add_argument("--inventory-only", action="store_true")
    acquire.add_argument("--reuse-inventory", action="store_true")
    acquire.add_argument("--delay-seconds", type=float, default=0.2)

    verify_acquisition = commands.add_parser(
        "verify-mil-std-acquisition",
        help="Administrative: close a DLA MIL-STD acquisition manifest against local PDF bytes",
    )
    verify_acquisition.add_argument("manifest")
    verify_acquisition.add_argument("--output-root", default=".standardsforge/sources/dla/mil-std")

    install = commands.add_parser("install", help="Administrative: validate and install a locally authorized pack")
    install.add_argument("source")
    install.add_argument("--policy", required=True, help="Trusted local operator policy JSON")

    resolve = commands.add_parser("resolve", help="Read-only: resolve an exact document identity")
    resolve.add_argument("identifier")
    resolve.add_argument("--edition")
    resolve.add_argument(
        "--representation",
        choices=["page_text", "derived_structure", "reviewed_structure", "curated_records"],
    )
    resolve.add_argument("--principal", required=True)

    list_documents = commands.add_parser("list-documents", help="Read-only: list authorized installed document packages")
    list_documents.add_argument("--identifier-prefix")
    list_documents.add_argument("--limit", type=int, default=50)
    list_documents.add_argument("--cursor")
    list_documents.add_argument("--principal", required=True)

    get_clause = commands.add_parser("get-clause", help="Read-only: retrieve a pinned clause and required context")
    get_clause.add_argument("package_digest")
    get_clause.add_argument("clause_reference", nargs="?")
    get_clause.add_argument(
        "--record-id",
        help="Canonical record identity; may be used alone or with a matching clause reference",
    )
    get_clause.add_argument("--principal", required=True)
    get_clause.add_argument("--max-bytes", type=int)
    get_clause.add_argument("--response-profile", choices=["compact_evidence_v1", "concise_evidence_v1"])

    build_context = commands.add_parser("build-context", help="Read-only: assemble dependency-complete evidence for clauses")
    build_context.add_argument("package_digest")
    build_context.add_argument("clause_references", nargs="+")
    build_context.add_argument("--principal", required=True)
    build_context.add_argument("--max-bytes", type=int)
    build_context.add_argument("--response-profile", choices=["compact_evidence_v1", "concise_evidence_v1"])

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
    search.add_argument("--package-digest")
    search.add_argument("--scope-prefix")
    search.add_argument(
        "--query-mode",
        choices=("exact_phrase", "all_terms", "any_terms", "natural_language"),
        default="all_terms",
    )

    revoke = commands.add_parser("revoke", help="Administrative: immediately revoke a principal's package grant")
    revoke.add_argument("package_digest")
    revoke.add_argument("--principal", required=True)
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "verify-source-set":
        return verify_source_set(args.catalog, args.source_root)
    if args.command == "archive-pack":
        return write_pack_archive(args.source, args.destination, compresslevel=args.compresslevel)
    if args.command == "compile-pdf":
        return compile_pdf_to_pack(args.catalog, args.document_id, args.source_root, args.output_directory)
    if args.command == "compile-mil-std-corpus":
        return compile_mil_std_corpus(
            args.manifest,
            args.source_root,
            args.output_root,
            compresslevel=args.compresslevel,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
    if args.command == "write-corpus-policy":
        return write_corpus_policy(args.index, args.output, args.principal)
    if args.command == "write-pack-policy":
        return write_pack_policy(args.source, args.output, args.principal, args.content_class)
    if args.command == "install-corpus":
        return install_compiled_corpus(
            args.index,
            args.policy,
            args.db,
            args.store,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
    if args.command == "compile-structure":
        return compile_structured_pdf_section(
            args.catalog,
            args.document_id,
            args.source_root,
            args.annotations,
            args.output_directory,
        )
    if args.command == "compile-derived-outline":
        return compile_derived_outline_pack(args.source_pack, args.output_directory)
    if args.command == "acquire-mil-std":
        return acquire_active_mil_stds(
            args.output_root,
            manifest_path=args.manifest,
            inventory_only=args.inventory_only,
            reuse_inventory=args.reuse_inventory,
            delay_seconds=args.delay_seconds,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
    if args.command == "verify-mil-std-acquisition":
        return verify_mil_std_acquisition(args.manifest, args.output_root)
    if args.command == "get-clause":
        for name, value in (
            ("clause_reference", args.clause_reference),
            ("record_id", args.record_id),
        ):
            require(
                value is None or bool(value.strip()),
                "invalid_selector",
                f"{name} must be a non-empty string when supplied.",
            )
        require(
            args.clause_reference is not None or args.record_id is not None,
            "invalid_selector",
            "get-clause requires clause_reference, record_id, or both.",
        )
    service = StandardsForgeService(Path(args.db), Path(args.store))
    if args.command == "verify-pack":
        return service.verify_pack(args.source)
    if args.command == "install":
        return service.install_pack(args.source, args.policy)
    if args.command == "resolve":
        return service.resolve_document(args.identifier, args.principal, args.edition, args.representation)
    if args.command == "list-documents":
        return service.list_documents(args.principal, args.identifier_prefix, args.limit, args.cursor)
    if args.command == "get-clause":
        return service.get_clause(
            args.package_digest,
            args.clause_reference,
            args.principal,
            max_bytes=args.max_bytes,
            response_profile=args.response_profile,
            record_id=args.record_id,
        )
    if args.command == "build-context":
        return service.build_context(
            args.package_digest,
            args.clause_references,
            args.principal,
            max_bytes=args.max_bytes,
            response_profile=args.response_profile,
        )
    if args.command == "enumerate-obligations":
        return service.enumerate_obligations(
            args.package_digest, args.principal, args.scope, args.limit, args.cursor, args.max_bytes
        )
    if args.command == "diff-editions":
        return service.diff_editions(
            args.from_package_digest, args.to_package_digest, args.principal, args.max_bytes
        )
    if args.command == "search":
        return service.search(
            args.query,
            args.principal,
            args.limit,
            package_digest=args.package_digest,
            scope_prefix=args.scope_prefix,
            query_mode=args.query_mode,
        )
    if args.command == "revoke":
        return service.revoke(args.package_digest, args.principal)
    raise StandardsForgeError("unsupported_operation", "The requested operation is not implemented.")


def _emit_json(stream: Any, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        binary.write(payload.encode("utf-8"))
        binary.flush()
    else:
        stream.write(payload)
        stream.flush()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = _run(args)
    except StandardsForgeError as exc:
        _emit_json(sys.stderr, {"ok": False, "error": exc.as_dict()})
        return 2
    except Exception:
        _emit_json(
            sys.stderr,
            {
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": "The operation failed unexpectedly; no partial success is asserted.",
                },
            },
        )
        return 1
    _emit_json(sys.stdout, {"ok": True, "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
