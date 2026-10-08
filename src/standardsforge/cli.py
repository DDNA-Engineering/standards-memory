from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .acquisition import acquire_active_mil_stds, verify_mil_std_acquisition
from .compiler import compile_pdf_to_pack
from .corpus_compiler import compile_mil_std_corpus, install_compiled_corpus, write_corpus_policy
from .coverage_ledger import apply_dispositions, page_ledger, write_artifact, link_semantic_evidence
from .doctor import run_doctor
from .errors import StandardsForgeError, require
from .handoff import export_engineering_handoff
from .outline_compiler import compile_derived_outline_pack
from .outline_review import export_outline_review_draft, promote_outline_review
from .pack import open_validated_pack, write_pack_archive
from .policy import write_pack_policy
from .review_shard import export_outline_review_shard, merge_outline_review_shard
from .real_benchmark import run_real_benchmark
from .service import StandardsForgeService
from .source_catalog import verify_source_set
from .structure_compiler import compile_structured_page_pack_section, compile_structured_pdf_section, compile_reviewed_page_section
from .transcription import compile_page_transcription
from .bundle import build_bundle, verify_bundle, install_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="standardsforge", description="Offline-first standards evidence engine")
    parser.add_argument("--db", default=".standardsforge/memory.db", help="SQLite metadata database")
    parser.add_argument("--store", default=".standardsforge/objects", help="Immutable object directory")
    parser.add_argument("--tokenizer-artifact", help="Explicit local tokenizer artifact for select-evidence")
    parser.add_argument("--tokenizer-sha256", help="Trusted SHA-256 pin for the local tokenizer artifact")
    parser.add_argument("--reference-bindings", help="Trusted local reviewed cross-standard binding artifact")
    parser.add_argument("--reference-bindings-sha256", help="Trusted SHA-256 pin for reviewed bindings")
    commands = parser.add_subparsers(dest="command", required=True)

    follow = commands.add_parser("follow-references", help="Read-only: follow explicitly reviewed exact cross-standard bindings")
    follow.add_argument("package_digest")
    follow.add_argument("record_id")
    follow.add_argument("--principal", required=True)
    follow.add_argument("--max-bytes", type=int)

    answer_review = commands.add_parser("export-answer-review", help="Administrative: export a local human answer-review form with exact source evidence")
    answer_review.add_argument("suite")
    answer_review.add_argument("submission")
    answer_review.add_argument("output")
    answer_review.add_argument("--principal", required=True)
    answer_qualify = commands.add_parser("qualify-answers", help="Administrative: validate source-bound answers and explicit reviewer judgments")
    answer_qualify.add_argument("suite")
    answer_qualify.add_argument("submission")
    answer_qualify.add_argument("adjudication")
    answer_qualify.add_argument("--principal", required=True)
    answer_qualify.add_argument("--output", required=True)

    tokenizer = commands.add_parser("export-tokenizer", help="Administrative: explicitly acquire and export a local tokenizer")
    tokenizer.add_argument("encoding", choices=("cl100k_base", "o200k_base"))
    tokenizer.add_argument("destination")
    select = commands.add_parser("select-evidence", help="Read-only: select the smallest measured lossless evidence profile")
    select.add_argument("package_digest")
    select.add_argument("record_id")
    select.add_argument("--principal", required=True)
    select.add_argument("--max-tokens", type=int)
    select.add_argument("--max-bytes", type=int)

    doctor = commands.add_parser("doctor", help="Read-only: diagnose local runtime and installed-state readiness")
    doctor.add_argument("--policy", help="Trusted local operator policy to compare with installed grants")
    doctor.add_argument("--principal", help="Principal whose active grants must be ready")
    doctor.add_argument("--full-integrity", action="store_true", help="Validate every installed package instead of one deterministic package")
    doctor.add_argument("--require-mcp", action="store_true", help="Treat the optional MCP dependency as required")

    verify = commands.add_parser("verify-pack", help="Validate a data-only pack without installing it")
    verify.add_argument("source")

    coverage = commands.add_parser("coverage-ledger", help="Administrative: inventory every physical page and pending source disposition")
    coverage.add_argument("source")
    coverage.add_argument("output")
    coverage.add_argument("--review", help="Explicit page-local reviewer dispositions bound to the original ledger digest")
    coverage.add_argument("--semantic-pack", help="Exact reviewed-structure pack whose source spans should be linked")

    transcription = commands.add_parser("compile-page-transcription", help="Administrative: compile explicitly reviewed visual page text against a pinned source pack")
    transcription.add_argument("source")
    transcription.add_argument("transcription")
    transcription.add_argument("rasters")
    transcription.add_argument("output")

    reviewed_section = commands.add_parser("compile-reviewed-page-section", help="Administrative: compile explicit semantic and relationship review against exact page text")
    reviewed_section.add_argument("source")
    reviewed_section.add_argument("annotations")
    reviewed_section.add_argument("output")

    qualify = commands.add_parser("qualify-real", help="Administrative: run explicit source-pinned real-document regressions")
    qualify.add_argument("suite")
    qualify.add_argument("--principal", required=True)
    qualify.add_argument("--output", help="Optional new file retaining all raw responses and verdicts")

    archive = commands.add_parser("archive-pack", help="Administrative: write a deterministic compressed pack archive")
    archive.add_argument("source")
    archive.add_argument("destination")
    archive.add_argument("--compresslevel", type=int, choices=range(1, 10), default=6)

    bundle = commands.add_parser("bundle-packs", help="Administrative: losslessly deduplicate explicit local packs into one data-only bundle")
    bundle.add_argument("destination")
    bundle.add_argument("sources", nargs="+")
    verify_bundle_parser = commands.add_parser("verify-bundle", help="Verify every reconstructed package in a content bundle")
    verify_bundle_parser.add_argument("source")
    install_bundle_parser = commands.add_parser("install-bundle", help="Administrative: install a content bundle under trusted local policy")
    install_bundle_parser.add_argument("source")
    install_bundle_parser.add_argument("--policy", required=True)

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

    compile_pack_structure = commands.add_parser(
        "compile-structure-from-pack",
        help="Administrative: compile reviewed annotations against their exact verified page-text pack",
    )
    compile_pack_structure.add_argument("source_page_pack")
    compile_pack_structure.add_argument("outline_pack")
    compile_pack_structure.add_argument("annotations")
    compile_pack_structure.add_argument("output_directory")
    compile_pack_structure.add_argument("--shard-directory")
    compile_pack_structure.add_argument("--decisions-directory")

    outline_draft = commands.add_parser(
        "export-outline-draft",
        help="Administrative: export one exact unreviewed outline candidate for explicit review",
    )
    outline_draft.add_argument("outline_pack")
    outline_draft.add_argument("source_page_pack")
    outline_draft.add_argument("record_id")
    outline_draft.add_argument("output_path")

    outline_shard = commands.add_parser(
        "export-outline-shard",
        help="Administrative: export a bounded exact selection of unreviewed outline drafts",
    )
    outline_shard.add_argument("outline_pack")
    outline_shard.add_argument("source_page_pack")
    outline_shard.add_argument("selection_path")
    outline_shard.add_argument("output_directory")

    merge_shard = commands.add_parser(
        "merge-review-shard",
        help="Administrative: replay one exact shard and its per-node review decisions",
    )
    merge_shard.add_argument("shard_directory")
    merge_shard.add_argument("decisions_directory")
    merge_shard.add_argument("outline_pack")
    merge_shard.add_argument("source_page_pack")
    merge_shard.add_argument("output_path")

    promote_review = commands.add_parser(
        "promote-outline-review",
        help="Administrative: validate an explicit reviewer decision and write pack-bound annotations",
    )
    promote_review.add_argument("draft_path")
    promote_review.add_argument("decision_path")
    promote_review.add_argument("outline_pack")
    promote_review.add_argument("source_page_pack")
    promote_review.add_argument("output_path")

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

    export_handoff = commands.add_parser(
        "export-handoff",
        help="Administrative: write a source-first reader and neutral engineering handoff",
    )
    export_handoff.add_argument("package_digest")
    export_handoff.add_argument("clause_reference", nargs="?")
    export_handoff.add_argument("--record-id")
    export_handoff.add_argument("--principal", required=True)
    export_handoff.add_argument("--candidate", required=True, help="Closed caller-authored candidate JSON")
    export_handoff.add_argument("--output", required=True, help="New output directory")

    resolve = commands.add_parser("resolve", help="Read-only: resolve an exact document identity")
    resolve.add_argument("identifier")
    resolve.add_argument("--edition")
    resolve.add_argument(
        "--representation",
        choices=["page_text", "derived_structure", "reviewed_structure", "curated_records"],
    )
    resolve.add_argument("--principal", required=True)

    list_documents = commands.add_parser(
        "list-documents", help="Read-only: list authorized installed document packages"
    )
    list_documents.add_argument("--identifier-prefix")
    list_documents.add_argument("--limit", type=int, default=50)
    list_documents.add_argument("--cursor")
    list_documents.add_argument("--principal", required=True)

    source_pdfs = commands.add_parser("source-pdfs", help="Read-only: locate verified preserved source PDFs")
    source_pdfs.add_argument("package_digest")
    source_pdfs.add_argument("--principal", required=True)

    browse = commands.add_parser("browse-records", help="Read-only: browse source-verified records and structural links")
    browse.add_argument("package_digest")
    browse.add_argument("--principal", required=True)
    browse.add_argument("--relation", choices=["all", "roots", "children", "parent", "adjacent", "outgoing", "incoming"], default="all")
    browse.add_argument("--record-id")
    browse.add_argument("--kind")
    browse.add_argument("--scope-prefix")
    browse.add_argument("--limit", type=int, default=50)
    browse.add_argument("--cursor")
    browse.add_argument("--max-bytes", type=int)

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
        choices=("exact_phrase", "all_terms", "any_terms", "natural_language", "concept_language"),
        default="all_terms",
    )

    revoke = commands.add_parser("revoke", help="Administrative: immediately revoke a principal's package grant")
    revoke.add_argument("package_digest")
    revoke.add_argument("--principal", required=True)
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "export-tokenizer":
        from .tokenization import export_tokenizer
        return export_tokenizer(args.encoding, args.destination)
    if args.command == "bundle-packs":
        return build_bundle(args.sources, args.destination)
    if args.command == "verify-bundle":
        return verify_bundle(args.source)
    if args.command == "install-bundle":
        return install_bundle(args.source, StandardsForgeService(args.db, args.store), args.policy)
    if args.command == "qualify-real":
        suite_path = Path(args.suite)
        require(suite_path.stat().st_size <= 16 * 1024 * 1024, "invalid_real_suite", "Suite exceeds 16 MiB.")
        artifact = run_real_benchmark(StandardsForgeService.open_read_only(args.db, args.store), args.principal, json.loads(suite_path.read_text(encoding="utf-8")))
        if args.output:
            write_artifact(args.output, artifact)
        require(artifact["run"]["gate"]["passed"], "real_qualification_failed", "One or more real-document regression cases failed.", metrics=artifact["run"]["metrics"])
        return {key: artifact["run"][key] for key in ("suite_sha256", "runtime_source_sha256", "metrics", "gate", "qualification")}
    if args.command == "compile-page-transcription":
        return compile_page_transcription(args.source, args.transcription, args.rasters, args.output)
    if args.command == "compile-reviewed-page-section":
        return compile_reviewed_page_section(args.source, args.annotations, args.output)
    if args.command == "coverage-ledger":
        with open_validated_pack(args.source) as pack:
            if args.review:
                review_path = Path(args.review)
                require(review_path.stat().st_size <= 16 * 1024 * 1024, "invalid_coverage_review", "Review JSON exceeds 16 MiB.")
                artifact = apply_dispositions(pack, json.loads(review_path.read_text(encoding="utf-8")))
            else:
                artifact = page_ledger(pack)
            if args.semantic_pack:
                with open_validated_pack(args.semantic_pack) as reviewed:
                    artifact = link_semantic_evidence(pack, reviewed, artifact)
        write_artifact(args.output, artifact)
        return {"output": args.output, "ledger_sha256": artifact["ledger_sha256"], "physical_pages": artifact["ledger"]["physical_pages"], "semantic_qualification": "not_established"}
    if args.command == "doctor":
        return run_doctor(
            args.db,
            args.store,
            policy_path=args.policy,
            principal_id=args.principal,
            full_integrity=args.full_integrity,
            require_mcp=args.require_mcp,
        )
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
    if args.command == "compile-structure-from-pack":
        return compile_structured_page_pack_section(
            args.source_page_pack, args.outline_pack, args.annotations, args.output_directory,
            shard_directory=args.shard_directory, decisions_directory=args.decisions_directory,
        )
    if args.command == "export-outline-draft":
        return export_outline_review_draft(args.outline_pack, args.source_page_pack, args.record_id, args.output_path)
    if args.command == "export-outline-shard":
        return export_outline_review_shard(args.outline_pack, args.source_page_pack, args.selection_path, args.output_directory)
    if args.command == "merge-review-shard":
        return merge_outline_review_shard(args.shard_directory, args.decisions_directory, args.outline_pack, args.source_page_pack, args.output_path)
    if args.command == "promote-outline-review":
        return promote_outline_review(args.draft_path, args.decision_path, args.outline_pack, args.source_page_pack, args.output_path)
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
    if args.command in {"get-clause", "export-handoff"}:
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
            f"{args.command} requires clause_reference, record_id, or both.",
        )
    if args.command == "export-handoff":
        return export_engineering_handoff(
            args.db,
            args.store,
            args.package_digest,
            args.principal,
            args.candidate,
            args.output,
            clause_reference=args.clause_reference,
            record_id=args.record_id,
        )
    service = (
        StandardsForgeService(Path(args.db), Path(args.store))
        if args.command in {"install", "revoke", "verify-pack"}
        else StandardsForgeService.open_read_only(Path(args.db), Path(args.store))
    )
    require(bool(args.tokenizer_artifact) == bool(args.tokenizer_sha256), "invalid_tokenizer", "Tokenizer artifact and SHA-256 must be supplied together.")
    if args.tokenizer_artifact:
        service.configure_tokenizer(args.tokenizer_artifact, args.tokenizer_sha256)
    require(bool(args.reference_bindings) == bool(args.reference_bindings_sha256), "invalid_reference_bindings", "Reference artifact and SHA-256 must be supplied together.")
    if args.reference_bindings:
        service.configure_reference_bindings(args.reference_bindings, args.reference_bindings_sha256)
    if args.command in {"export-answer-review", "qualify-answers"}:
        from .answer_benchmark import run_answer_benchmark
        from .answer_review_ui import export_answer_review
        def read_document(path):
            with Path(path).open("rb") as stream:
                raw = stream.read(32 * 1024 * 1024 + 1)
            require(len(raw) <= 32 * 1024 * 1024, "invalid_answer_benchmark", "Answer artifact exceeds the local input limit.")
            return json.loads(raw)
        suite, submission = read_document(args.suite), read_document(args.submission)
        if args.command == "export-answer-review":
            return export_answer_review(service, args.principal, suite, submission, args.output)
        artifact = run_answer_benchmark(service, args.principal, suite, submission, read_document(args.adjudication))
        write_artifact(args.output, artifact)
        return artifact
    if args.command == "follow-references":
        return service.follow_references(args.package_digest, args.record_id, args.principal, max_bytes=args.max_bytes)
    if args.command == "select-evidence":
        return service.select_evidence(args.package_digest, args.record_id, args.principal,
                                       max_tokens=args.max_tokens, max_bytes=args.max_bytes)
    if args.command == "verify-pack":
        return service.verify_pack(args.source)
    if args.command == "install":
        return service.install_pack(args.source, args.policy)
    if args.command == "resolve":
        return service.resolve_document(args.identifier, args.principal, args.edition, args.representation)
    if args.command == "list-documents":
        return service.list_documents(args.principal, args.identifier_prefix, args.limit, args.cursor)
    if args.command == "source-pdfs":
        return service.get_source_pdfs(args.package_digest, args.principal)
    if args.command == "browse-records":
        return service.browse_records(args.package_digest, args.principal, relation=args.relation,
                                      record_id=args.record_id, kind=args.kind, scope_prefix=args.scope_prefix,
                                      limit=args.limit, cursor=args.cursor, max_bytes=args.max_bytes)
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
    if args.command == "doctor" and result["ready"] is False:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
