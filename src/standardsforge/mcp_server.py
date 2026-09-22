from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Sequence

from mcp.server import MCPServer
from mcp.server._otel import OpenTelemetryMiddleware
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import ConfigDict
from typing_extensions import NotRequired, TypedDict

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
MCP_SERVER_INSTRUCTIONS = (
    "Read MIL-STDs as edition-pinned evidence, not as free-floating prose. First resolve the exact "
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
        "Discover authorized records by explicit local lexical mode: exact_phrase preserves token order and "
        "adjacency, all_terms requires every parsed term, and any_terms accepts at least one. Results are "
        "candidates, not applicability, "
        "obligation completeness, or exact document identity; use resolve_document for an identifier and replay "
        "a selected evidence_selector through get_clause."
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
        "Compare two authorized immutable packages by exact record identity. Return review-required logical-key "
        "candidates separately and traverse each edition's required-dependency graph independently; do not infer "
        "cross-edition equivalence, engineering impact, applicability, supersession, or compliance."
    ),
}

class _SearchInterpretation(TypedDict):
    mode: Literal["exact_phrase", "all_terms", "any_terms"]
    normalized_query: str
    parsed_terms: list[str]


class _SearchResult(TypedDict):
    operation: Literal["search"]
    retrieval_mode: Literal["lexical_fts5"]
    query: str
    query_interpretation: _SearchInterpretation
    snippet_markers: dict[str, str]
    filters: dict[str, Any]
    results: list[dict[str, Any]]
    coverage_by_package: dict[str, dict[str, Any]]
    completeness: dict[str, Any]
    limitations: list[str]


class _ResolveDocumentResult(TypedDict):
    operation: Literal["resolve_document"]
    retrieval_mode: Literal["exact_identifier"]
    document_family_id: str
    identifier: str
    normalized_identifier: str
    title: str
    edition_id: str
    revision: str
    representation: Literal["page_text", "derived_structure", "reviewed_structure", "curated_records"]
    package_digest: str


class _GetClauseResult(TypedDict):
    schema_version: Literal["0.1.0"]
    operation: Literal["get_clause"]
    retrieval_mode: Literal["exact_pinned_clause"]
    package: dict[str, Any]
    evidence: Any
    limitations: list[str]
    budget: dict[str, Any]
    response_profile: NotRequired[Literal["compact_evidence_v1", "concise_evidence_v1"]]
    required_relationships: NotRequired[list[dict[str, Any]]]
    relationships: NotRequired[list[dict[str, Any]]]
    completeness: NotRequired[dict[str, Any]]
    authorization: NotRequired[dict[str, Any]]
    provenance: NotRequired[dict[str, Any]]
    coverage: NotRequired[dict[str, Any]]
    token_measurement: NotRequired[dict[str, Any]]


class _BuildContextResult(_GetClauseResult):
    operation: Literal["build_context"]
    retrieval_mode: Literal["exact_pinned_multi_clause"]
    requested_clause_references: list[str]


class _EnumerateObligationsResult(TypedDict):
    schema_version: Literal["0.1.0"]
    operation: Literal["enumerate_obligations"]
    retrieval_mode: Literal["stable_record_traversal"]
    package: dict[str, Any]
    scope_prefix: str | None
    obligations: list[dict[str, Any]]
    page: dict[str, Any]
    completeness: dict[str, Any]
    limitations: list[str]
    budget: dict[str, Any]


class _ClosedTypedDict(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")


class _DiffPackage(_ClosedTypedDict):
    package_digest: str
    pack_id: str
    document_family_id: str
    edition_id: str
    identifier: str
    revision: str
    title: str


class _DiffBudget(_ClosedTypedDict):
    kind: Literal["bytes"]
    used: int
    limit: int | None


class _DiffCitation(_ClosedTypedDict):
    source_path: str
    source_sha256: str
    page: int
    locator: str
    quote_sha256: str
    text_path: NotRequired[str]
    text_sha256: NotRequired[str]
    text_start_byte: NotRequired[int]
    text_end_byte: NotRequired[int]


class _DiffSourceChecks(_ClosedTypedDict):
    source_digest_verified: Literal[True]
    quote_digest_verified: Literal[True]
    exact_quote_present: Literal[True]
    extracted_text_digest_verified: NotRequired[Literal[True]]


class _DiffRecordDerivation(_ClosedTypedDict):
    statement_role: Literal["obligation", "governing_note", "informative", "unclassified"]
    method: str
    review_status: str


class _DiffStructureSpan(_ClosedTypedDict):
    path: str
    sha256: str
    text_path: str
    text_sha256: str
    physical_page: int
    start_byte: int
    end_byte: int
    quote_sha256: str


class _DiffStructureRelationship(_ClosedTypedDict):
    relationship: Literal[
        "contains",
        "sequence_after",
        "governed_by",
        "defines",
        "uses_definition",
        "qualifies",
        "exception_to",
        "references",
        "caption_of",
        "table_footnote_for",
        "footnote_for",
        "header_for",
        "illustrates",
        "continues_on",
    ]
    target_status: Literal["resolved", "out_of_scope", "unresolved", "ambiguous"]
    target_logical_id: str | None
    target_locator: str | None
    candidate_logical_ids: list[str]
    required: bool
    method: str
    review_status: str
    evidence_spans: list[_DiffStructureSpan]


class _DiffSemanticStatement(_ClosedTypedDict):
    subject: str
    action: str
    modality: Literal["shall", "must", "should", "may", "will", "other"]
    polarity: Literal["affirmative", "negative"]
    exact_text: str
    span_indices: list[int]


class _DiffSemanticQualifier(_ClosedTypedDict):
    kind: Literal[
        "condition",
        "exception",
        "source_applicability",
        "test_condition",
        "acceptance_criterion",
        "tailoring_instruction",
    ]
    exact_text: str
    span_indices: list[int]


class _DiffSemanticQuantity(_ClosedTypedDict):
    raw: str
    value: str | None
    unit: str | None
    tolerance: str | None
    span_indices: list[int]


class _DiffSemanticRecord(_ClosedTypedDict):
    schema_version: Literal["0.1.0"]
    content_role: Literal[
        "requirement_candidate",
        "governing_condition",
        "exception",
        "applicability_statement",
        "definition",
        "table_header",
        "table_row",
        "table_footnote",
        "note",
        "prose",
    ]
    normativity: Literal["normative", "informative", "mixed", "unclassified"]
    statement: _DiffSemanticStatement | None
    qualifiers: list[_DiffSemanticQualifier]
    quantities: list[_DiffSemanticQuantity]
    unresolved_issues: list[str]
    project_applicability: Literal["not_decided"]


class _DiffReviewer(_ClosedTypedDict):
    id: str
    type: Literal["agent", "human"]


class _DiffReviewTool(_ClosedTypedDict):
    name: str
    version: str
    configuration_sha256: str | None


class _DiffReviewEvent(_ClosedTypedDict):
    schema_version: Literal["0.1.0"]
    status: Literal[
        "agent_reviewed", "human_verified", "human_verified_with_uncertainty", "rejected"
    ]
    reviewed_content_sha256: str
    scope: Literal["structure_only", "structure_and_semantics"]
    reviewer: _DiffReviewer
    reviewed_at: str
    method: str
    tool: _DiffReviewTool | None
    unresolved_issues: list[str]
    attestation: Literal["extraction_review_not_project_applicability_or_approval"]


class _DiffStructureBase(_ClosedTypedDict):
    logical_id: str
    content_sha256: str
    parent_logical_id: str | None
    ordinal: int
    source_spans: list[_DiffStructureSpan]
    relationships: list[_DiffStructureRelationship]


class _DiffUnreviewedStructure(_DiffStructureBase):
    pass


class _DiffReviewedStructure(_DiffStructureBase):
    review: _DiffReviewEvent


class _DiffSemanticStructure(_DiffStructureBase):
    semantics: _DiffSemanticRecord
    review: _DiffReviewEvent


class _DiffEvidenceRecord(_ClosedTypedDict):
    record_id: str
    kind: str
    clause_reference: str
    heading: str
    text: str
    derivation: _DiffRecordDerivation
    citation: _DiffCitation
    source_checks: _DiffSourceChecks
    structure: NotRequired[
        _DiffUnreviewedStructure | _DiffReviewedStructure | _DiffSemanticStructure
    ]


class _DiffAddedChange(_ClosedTypedDict):
    record_id: str
    status: Literal["added"]
    after_text_sha256: str
    after: _DiffEvidenceRecord


class _DiffRemovedChange(_ClosedTypedDict):
    record_id: str
    status: Literal["removed"]
    before_text_sha256: str
    before: _DiffEvidenceRecord


class _DiffModifiedChange(_ClosedTypedDict):
    record_id: str
    status: Literal["modified"]
    before_text_sha256: str
    after_text_sha256: str
    source_location_changed: bool
    before: _DiffEvidenceRecord
    after: _DiffEvidenceRecord


class _DiffMovedChange(_ClosedTypedDict):
    record_id: str
    status: Literal["moved"]
    before_text_sha256: str
    after_text_sha256: str
    source_location_changed: Literal[True]
    before: _DiffEvidenceRecord
    after: _DiffEvidenceRecord


class _DiffUnchangedChange(_ClosedTypedDict):
    record_id: str
    status: Literal["unchanged"]
    before_text_sha256: str
    after_text_sha256: str
    source_location_changed: Literal[False]


class _DiffAlignmentCandidate(_ClosedTypedDict):
    before_record_id: str
    after_record_id: str
    kind: str
    clause_reference: str
    basis: Literal["unique_kind_clause_reference"]
    review_status: Literal["review_required"]
    before_text_sha256: str
    after_text_sha256: str


class _DiffDependencyEdge(_ClosedTypedDict):
    source_record_id: str
    relationship: str
    target_record_id: str
    required: bool


class _DiffEdgeCause(_ClosedTypedDict):
    type: Literal["dependency_edge_added", "dependency_edge_removed"]
    record_id: str


class _DiffTargetCause(_ClosedTypedDict):
    type: Literal["target_record_changed"]
    record_id: str
    status: Literal["added", "removed", "modified", "moved", "unchanged", "unresolved"]


class _DiffDependencyImpact(_ClosedTypedDict):
    side: Literal["before", "after"]
    record_id: str
    path: list[_DiffDependencyEdge]
    cause: _DiffEdgeCause | _DiffTargetCause


class _DiffChangeCounts(_ClosedTypedDict):
    added: int
    removed: int
    modified: int
    moved: int
    unchanged: int


class _DiffEditionsResult(_ClosedTypedDict):
    schema_version: Literal["0.2.0"]
    operation: Literal["diff_editions"]
    alignment_mode: Literal["exact_record_id_only_with_non_authoritative_candidates_v1"]
    from_package: _DiffPackage
    to_package: _DiffPackage
    changes: list[
        _DiffAddedChange
        | _DiffRemovedChange
        | _DiffModifiedChange
        | _DiffMovedChange
        | _DiffUnchangedChange
    ]
    alignment_candidates: list[_DiffAlignmentCandidate]
    change_counts: _DiffChangeCounts
    dependency_context_impacts: list[str]
    dependency_impact_paths: list[_DiffDependencyImpact]
    dependency_edges_added: list[tuple[str, str, str, bool]]
    dependency_edges_removed: list[tuple[str, str, str, bool]]
    limitations: list[str]
    budget: _DiffBudget


class _SearchSuccess(TypedDict):
    ok: Literal[True]
    result: _SearchResult


class _ResolveDocumentSuccess(TypedDict):
    ok: Literal[True]
    result: _ResolveDocumentResult


class _GetClauseSuccess(TypedDict):
    ok: Literal[True]
    result: _GetClauseResult


class _BuildContextSuccess(TypedDict):
    ok: Literal[True]
    result: _BuildContextResult


class _EnumerateObligationsSuccess(TypedDict):
    ok: Literal[True]
    result: _EnumerateObligationsResult


class _DiffEditionsSuccess(_ClosedTypedDict):
    ok: Literal[True]
    result: _DiffEditionsResult


SearchToolResult = Annotated[CallToolResult, _SearchSuccess]
ResolveDocumentToolResult = Annotated[CallToolResult, _ResolveDocumentSuccess]
GetClauseToolResult = Annotated[CallToolResult, _GetClauseSuccess]
BuildContextToolResult = Annotated[CallToolResult, _BuildContextSuccess]
EnumerateObligationsToolResult = Annotated[CallToolResult, _EnumerateObligationsSuccess]
DiffEditionsToolResult = Annotated[CallToolResult, _DiffEditionsSuccess]
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
        query_mode: Literal["exact_phrase", "all_terms", "any_terms"] = "all_terms",
    ) -> SearchToolResult:
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

    @server.tool(description=MCP_TOOL_DESCRIPTIONS["resolve_document"], annotations=read_only)
    def resolve_document(
        identifier: str,
        edition_id: str | None = None,
        representation: Literal["page_text", "derived_structure", "reviewed_structure", "curated_records"] | None = None,
    ) -> ResolveDocumentToolResult:
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
    ) -> GetClauseToolResult:
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
    ) -> BuildContextToolResult:
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
    ) -> EnumerateObligationsToolResult:
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
    ) -> DiffEditionsToolResult:
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
