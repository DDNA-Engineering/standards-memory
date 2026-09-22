from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import StandardsForgeError, require
from .service import StandardsForgeService


HANDOFF_NAME = "evidence-handoff.json"
READER_NAME = "reader.html"
MANIFEST_NAME = "manifest.json"
EXPECTED_FILES = {HANDOFF_NAME, READER_NAME, MANIFEST_NAME}
HEX64 = re.compile(r"[0-9a-f]{64}")
ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
LOCATOR = re.compile(
    r"standardsforge://evidence/v1/packages/([0-9a-f]{64})/records/([A-Za-z0-9_-]+)"
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _pretty_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_handoff", f"{label} is not valid UTF-8 JSON.") from exc
    require(isinstance(value, dict), "invalid_handoff", f"{label} must contain one JSON object.")
    return value


def _exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(
        isinstance(value, dict) and set(value) == keys,
        "invalid_handoff",
        f"{label} has missing or unknown fields.",
    )
    return value


def _bounded_text(value: Any, label: str, maximum: int) -> str:
    require(
        isinstance(value, str) and 1 <= len(value) <= maximum,
        "invalid_handoff",
        f"{label} must be bounded non-empty text.",
    )
    return value


def _validate_note_items(value: Any, label: str, maximum: int) -> None:
    require(
        isinstance(value, list) and len(value) <= maximum,
        "invalid_handoff",
        f"{label} must be a bounded array.",
    )
    seen: set[str] = set()
    for item in value:
        item = _exact_keys(item, {"id", "text"}, f"{label} item")
        item_id = _bounded_text(item["id"], f"{label} item id", 128)
        require(ITEM_ID.fullmatch(item_id) is not None, "invalid_handoff", f"{label} item ID is invalid.")
        require(item_id not in seen, "invalid_handoff", f"{label} item IDs must be unique.")
        seen.add(item_id)
        _bounded_text(item["text"], f"{label} item text", 4096)


def validate_candidate_draft(value: Any) -> dict[str, Any]:
    draft = _exact_keys(
        value,
        {
            "schema_version",
            "kind",
            "text",
            "author",
            "authored_at",
            "method",
            "tool",
            "assumptions",
            "unresolved_questions",
            "tailoring_proposals",
        },
        "candidate draft",
    )
    require(draft["schema_version"] == "0.1.0", "invalid_handoff", "Candidate draft version is unsupported.")
    require(
        draft["kind"] in {"requirement_candidate", "test_basis_candidate"},
        "invalid_handoff",
        "Candidate kind is unsupported.",
    )
    _bounded_text(draft["text"], "candidate text", 20000)
    author = _exact_keys(draft["author"], {"id", "type"}, "candidate author")
    _bounded_text(author["id"], "candidate author ID", 256)
    require(author["type"] in {"human", "agent"}, "invalid_handoff", "Candidate author type is unsupported.")
    authored_at = _bounded_text(draft["authored_at"], "candidate authored_at", 64)
    require(authored_at.endswith("Z"), "invalid_handoff", "Candidate authored_at must be UTC date-time text.")
    try:
        datetime.fromisoformat(authored_at.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise StandardsForgeError("invalid_handoff", "Candidate authored_at is not a valid date-time.") from exc
    _bounded_text(draft["method"], "candidate method", 512)
    tool = draft["tool"]
    if author["type"] == "agent":
        tool = _exact_keys(tool, {"name", "version", "configuration_sha256"}, "candidate tool")
        _bounded_text(tool["name"], "candidate tool name", 256)
        _bounded_text(tool["version"], "candidate tool version", 128)
        require(
            isinstance(tool["configuration_sha256"], str)
            and HEX64.fullmatch(tool["configuration_sha256"]) is not None,
            "invalid_handoff",
            "Candidate tool configuration digest is invalid.",
        )
    else:
        require(tool is None, "invalid_handoff", "A human-authored candidate must not claim agent tool provenance.")
    _validate_note_items(draft["assumptions"], "candidate assumptions", 64)
    _validate_note_items(draft["unresolved_questions"], "candidate unresolved questions", 64)
    proposals = draft["tailoring_proposals"]
    require(
        isinstance(proposals, list) and len(proposals) <= 32,
        "invalid_handoff",
        "Candidate tailoring proposals must be a bounded array.",
    )
    proposal_ids: set[str] = set()
    for proposal in proposals:
        proposal = _exact_keys(proposal, {"id", "text", "status"}, "tailoring proposal")
        proposal_id = _bounded_text(proposal["id"], "tailoring proposal ID", 128)
        require(ITEM_ID.fullmatch(proposal_id) is not None, "invalid_handoff", "Tailoring proposal ID is invalid.")
        require(proposal_id not in proposal_ids, "invalid_handoff", "Tailoring proposal IDs must be unique.")
        proposal_ids.add(proposal_id)
        _bounded_text(proposal["text"], "tailoring proposal text", 4096)
        require(
            proposal["status"] == "proposed_not_approved",
            "invalid_handoff",
            "Tailoring cannot be represented as approved in a handoff candidate.",
        )
    return draft


def encode_evidence_locator(package_digest: str, record_id: str) -> str:
    require(
        isinstance(package_digest, str) and HEX64.fullmatch(package_digest) is not None,
        "invalid_handoff",
        "A lowercase package digest is required for the durable locator.",
    )
    record_id = _bounded_text(record_id, "record ID", 1024)
    token = base64.urlsafe_b64encode(record_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"standardsforge://evidence/v1/packages/{package_digest}/records/{token}"


def decode_evidence_locator(locator: str) -> tuple[str, str]:
    require(isinstance(locator, str), "invalid_handoff", "Evidence locator must be text.")
    match = LOCATOR.fullmatch(locator)
    require(match is not None, "invalid_handoff", "Evidence locator is not canonical.")
    package_digest, token = match.groups()
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        record_id = raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise StandardsForgeError("invalid_handoff", "Evidence locator record token is invalid.") from exc
    require(
        bool(record_id) and encode_evidence_locator(package_digest, record_id) == locator,
        "invalid_handoff",
        "Evidence locator record token is not canonical.",
    )
    return package_digest, record_id


def _package_representation(manifest: dict[str, Any]) -> str:
    explicit = manifest.get("representation")
    if explicit in {"page_text", "derived_structure", "reviewed_structure", "curated_records"}:
        return explicit
    parsed_coverage = manifest.get("coverage", {}).get("parsed_source_coverage", "")
    if isinstance(parsed_coverage, str) and parsed_coverage.startswith("text_layer_extracted_"):
        return "page_text"
    if isinstance(parsed_coverage, str) and parsed_coverage.startswith("partial_reviewed_structural_"):
        return "reviewed_structure"
    return "curated_records"


def _unresolved_issues(packet: dict[str, Any]) -> list[str]:
    issues: set[str] = set()
    for record in packet["evidence"]:
        structure = record.get("structure")
        if not isinstance(structure, dict):
            continue
        for section in (structure.get("semantics"), structure.get("review")):
            if isinstance(section, dict):
                for issue in section.get("unresolved_issues", []):
                    if isinstance(issue, str) and issue:
                        issues.add(issue)
                    elif isinstance(issue, dict):
                        issues.add(json.dumps(issue, sort_keys=True, ensure_ascii=False))
        for relationship in structure.get("relationships", []):
            if isinstance(relationship, dict) and relationship.get("status") not in {None, "resolved"}:
                issues.add(
                    f"relationship {relationship.get('type', 'unknown')} status: {relationship.get('status')}"
                )
    return sorted(issues)


def _build_handoff(
    packet: dict[str, Any],
    package_row: Any,
    principal_id: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    require(
        packet.get("operation") == "get_clause"
        and packet.get("retrieval_mode") == "exact_pinned_clause"
        and packet.get("schema_version") == "0.1.0"
        and isinstance(packet.get("evidence"), list)
        and bool(packet["evidence"]),
        "invalid_handoff",
        "Handoff export requires one complete detailed get-clause packet.",
    )
    completeness = packet.get("completeness", {})
    require(
        completeness.get("dependency_closure") == "complete_for_returned_required_graph"
        and completeness.get("output_budget_coverage") == "complete",
        "invalid_handoff",
        "Handoff export refuses incomplete or truncated evidence.",
    )
    root = packet["evidence"][0]
    package_digest = packet["package"]["package_digest"]
    manifest = json.loads(package_row["manifest_json"])
    rights = json.loads(package_row["rights_json"])
    packet_sha256 = _sha256_bytes(_canonical_json(packet))
    draft_sha256 = _sha256_bytes(_canonical_json(candidate))
    context_ids = list(dict.fromkeys(item["record_id"] for item in packet["evidence"][1:]))
    selection = {
        "durable_locator": encode_evidence_locator(package_digest, root["record_id"]),
        "package_digest": package_digest,
        "pack_id": packet["package"]["pack_id"],
        "document_family_id": packet["package"]["document_family_id"],
        "edition_id": packet["package"]["edition_id"],
        "representation": _package_representation(manifest),
        "identifier": packet["package"]["identifier"],
        "revision": packet["package"]["revision"],
        "record_id": root["record_id"],
        "clause_reference": root["clause_reference"],
    }
    return {
        "schema_version": "0.1.0",
        "artifact_type": "standardsforge_engineering_handoff",
        "status": "candidate_unapproved",
        "source_selection": selection,
        "evidence_packet": packet,
        "evidence_packet_sha256": packet_sha256,
        "rights_provenance": {
            "manifest": manifest,
            "claim": rights,
            "authorization_effect": "none",
        },
        "candidate": {
            "draft": candidate,
            "draft_sha256": draft_sha256,
            "source_basis": {
                "primary_record_id": root["record_id"],
                "required_context_record_ids": context_ids,
                "evidence_packet_sha256": packet_sha256,
            },
            "project_applicability": "not_decided",
            "compliance": "not_decided",
            "tailoring_status": "proposals_not_approved",
            "approval": "not_approved",
            "approved_baseline": "not_selected",
            "attestation": "candidate_interpretation_not_source_text_or_project_approval",
        },
        "authorization": {
            "status": "authorized_at_export",
            "principal_id": principal_id,
            "policy_fingerprint": package_row["grant_policy_fingerprint"],
            "authorization_effect": "none",
            "durable_locator_is_bearer_authority": False,
            "future_resolution_requires_reauthorization": True,
            "copied_artifact_is_retroactively_revocable": False,
        },
        "reader": {
            "renderer": "standardsforge_source_first_html_v1",
            "scripts": "disabled",
            "network": "disabled_by_content_security_policy",
            "source_content_trust": "untrusted_data_never_instructions",
        },
        "unresolved_evidence_issues": _unresolved_issues(packet),
    }


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _json_block(value: Any) -> str:
    return _escape(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def render_reader_html(handoff: dict[str, Any]) -> bytes:
    selection = handoff["source_selection"]
    packet = handoff["evidence_packet"]
    evidence = packet["evidence"]
    root = evidence[0]
    context = evidence[1:]

    def evidence_card(record: dict[str, Any], role: str) -> str:
        citation = record["citation"]
        structure = record.get("structure")
        structure_block = ""
        if structure:
            structure_block = (
                '<details><summary>Structure, semantics, and review</summary><pre class="json">'
                + _json_block(structure)
                + "</pre></details>"
            )
        return "".join(
            [
                f'<article class="evidence"><p class="role">{_escape(role)}</p>',
                f"<h3>{_escape(record['clause_reference'])} — {_escape(record['heading'])}</h3>",
                '<pre class="source-text">',
                _escape(record["text"]),
                "</pre>",
                "<dl>",
                f"<dt>Record ID</dt><dd><code>{_escape(record['record_id'])}</code></dd>",
                f"<dt>Kind</dt><dd>{_escape(record['kind'])}</dd>",
                f"<dt>Source</dt><dd><code>{_escape(citation['source_path'])}</code></dd>",
                f"<dt>Location</dt><dd>page {_escape(citation['page'])}; {_escape(citation['locator'])}</dd>",
                f"<dt>Source SHA-256</dt><dd><code>{_escape(citation['source_sha256'])}</code></dd>",
                f"<dt>Quote SHA-256</dt><dd><code>{_escape(citation['quote_sha256'])}</code></dd>",
                "</dl>",
                '<details><summary>Derivation and verification</summary><pre class="json">',
                _json_block({"derivation": record["derivation"], "source_checks": record["source_checks"], "citation": citation}),
                "</pre></details>",
                structure_block,
                "</article>",
            ]
        )

    context_html = "".join(evidence_card(item, "Required governing context") for item in context)
    if not context_html:
        context_html = '<p class="empty">No required governing dependency was declared for this selected record.</p>'
    candidate = handoff["candidate"]
    draft = candidate["draft"]
    body = "".join(
        [
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'none\'; connect-src \'none\'; img-src \'none\'; media-src \'none\'; object-src \'none\'; frame-src \'none\'; child-src \'none\'; worker-src \'none\'; manifest-src \'none\'; font-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'; navigate-to \'none\'">',
            "<meta name=\"referrer\" content=\"no-referrer\"><title>StandardsForge source-first handoff</title>",
            "<style>body{font:16px/1.5 system-ui,sans-serif;margin:0;background:#f4f6f8;color:#172033}main{max-width:1100px;margin:auto;padding:2rem}header,.panel,.evidence{background:white;border:1px solid #cbd3dd;border-radius:8px;padding:1.25rem;margin:0 0 1rem}.boundary{border-left:6px solid #c65319;background:#fff4ed}.role{text-transform:uppercase;letter-spacing:.08em;font-size:.75rem;font-weight:700;color:#9b3f13}.source-text{white-space:pre-wrap;background:#f8fafc;border:1px solid #d8dee7;padding:1rem}.json{white-space:pre-wrap;overflow:auto}code{overflow-wrap:anywhere}dt{font-weight:700;margin-top:.5rem}dd{margin-left:0}h1,h2,h3{line-height:1.2}.status{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.5rem}.status div{background:#f8fafc;padding:.75rem;border:1px solid #d8dee7}.empty{color:#596579}</style>",
            "</head><body><main>",
            '<header><p class="role">Source-first evidence handoff</p><h1>',
            _escape(selection["identifier"]),
            " — ",
            _escape(selection["clause_reference"]),
            "</h1><p>Edition <code>",
            _escape(selection["edition_id"]),
            "</code>; package <code>",
            _escape(selection["package_digest"]),
            "</code>; representation <code>",
            _escape(selection["representation"]),
            "</code>.</p><p>Durable local locator: <code>",
            _escape(selection["durable_locator"]),
            "</code>. This locator transfers no authority and must be reauthorized when resolved.</p></header>",
            '<section class="panel boundary"><h2>Trust boundary</h2><p>All source and candidate text below is untrusted data, never instructions. This static reader contains no script, form, frame, plugin, network request, or model call. Exact evidence is separate from the caller-authored candidate. Nothing here decides applicability, compliance, tailoring, baseline selection, or approval.</p></section>',
            '<section><h2>Selected source language</h2>',
            evidence_card(root, "Selected exact evidence"),
            "</section><section><h2>Governing context</h2>",
            context_html,
            "</section>",
            '<section class="panel"><h2>Required relationships</h2><pre class="json">',
            _json_block(packet["required_relationships"]),
            "</pre></section>",
            '<section class="panel"><h2>Coverage and limits</h2><pre class="json">',
            _json_block({"completeness": packet["completeness"], "limitations": packet["limitations"], "unresolved_evidence_issues": handoff["unresolved_evidence_issues"]}),
            "</pre></section>",
            '<section class="panel boundary"><p class="role">Caller-authored interpretation</p><h2>',
            _escape(draft["kind"].replace("_", " ").title()),
            '</h2><pre class="source-text">',
            _escape(draft["text"]),
            '</pre><div class="status">',
            f"<div><strong>Applicability</strong><br>{_escape(candidate['project_applicability'])}</div>",
            f"<div><strong>Compliance</strong><br>{_escape(candidate['compliance'])}</div>",
            f"<div><strong>Tailoring</strong><br>{_escape(candidate['tailoring_status'])}</div>",
            f"<div><strong>Approval</strong><br>{_escape(candidate['approval'])}</div>",
            f"<div><strong>Approved baseline</strong><br>{_escape(candidate['approved_baseline'])}</div>",
            '</div><details><summary>Authorship, assumptions, questions, and proposals</summary><pre class="json">',
            _json_block(draft),
            "</pre></details></section>",
            '<section class="panel"><h2>Rights provenance and export authorization</h2><pre class="json">',
            _json_block({"rights_provenance": handoff["rights_provenance"], "authorization": handoff["authorization"]}),
            "</pre></section>",
            "</main></body></html>\n",
        ]
    )
    return body.encode("utf-8")


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    checker = getattr(path, "is_junction", None)
    if checker is not None and checker():
        return True
    if os.name == "nt":
        try:
            attributes = os.lstat(path).st_file_attributes
        except (AttributeError, OSError):
            return False
        return bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            and attributes & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
        )
    return False


def _validate_handoff_shape(handoff: dict[str, Any]) -> None:
    _exact_keys(
        handoff,
        {
            "schema_version",
            "artifact_type",
            "status",
            "source_selection",
            "evidence_packet",
            "evidence_packet_sha256",
            "rights_provenance",
            "candidate",
            "authorization",
            "reader",
            "unresolved_evidence_issues",
        },
        "engineering handoff",
    )
    require(
        handoff["schema_version"] == "0.1.0"
        and handoff["artifact_type"] == "standardsforge_engineering_handoff"
        and handoff["status"] == "candidate_unapproved",
        "invalid_handoff",
        "Engineering handoff identity is invalid.",
    )
    selection = _exact_keys(
        handoff["source_selection"],
        {"durable_locator", "package_digest", "pack_id", "document_family_id", "edition_id", "representation", "identifier", "revision", "record_id", "clause_reference"},
        "source selection",
    )
    locator_package, locator_record = decode_evidence_locator(selection["durable_locator"])
    require(
        locator_package == selection["package_digest"] and locator_record == selection["record_id"],
        "invalid_handoff",
        "Durable locator does not match the source selection.",
    )
    packet = handoff["evidence_packet"]
    require(
        isinstance(packet, dict)
        and packet.get("operation") == "get_clause"
        and packet.get("package", {}).get("package_digest") == selection["package_digest"]
        and packet.get("package", {}).get("pack_id") == selection["pack_id"]
        and packet.get("package", {}).get("document_family_id") == selection["document_family_id"]
        and packet.get("package", {}).get("edition_id") == selection["edition_id"]
        and packet.get("package", {}).get("identifier") == selection["identifier"]
        and packet.get("package", {}).get("revision") == selection["revision"]
        and isinstance(packet.get("evidence"), list)
        and bool(packet["evidence"])
        and packet["evidence"][0].get("record_id") == selection["record_id"]
        and packet["evidence"][0].get("clause_reference") == selection["clause_reference"],
        "invalid_handoff",
        "Evidence packet does not match the selected root.",
    )
    packet_sha256 = _sha256_bytes(_canonical_json(packet))
    require(
        handoff["evidence_packet_sha256"] == packet_sha256,
        "invalid_handoff",
        "Evidence packet digest is invalid.",
    )
    candidate = _exact_keys(
        handoff["candidate"],
        {"draft", "draft_sha256", "source_basis", "project_applicability", "compliance", "tailoring_status", "approval", "approved_baseline", "attestation"},
        "handoff candidate",
    )
    validate_candidate_draft(candidate["draft"])
    require(
        candidate["draft_sha256"] == _sha256_bytes(_canonical_json(candidate["draft"])),
        "invalid_handoff",
        "Candidate draft digest is invalid.",
    )
    basis = _exact_keys(candidate["source_basis"], {"primary_record_id", "required_context_record_ids", "evidence_packet_sha256"}, "candidate source basis")
    expected_context = list(dict.fromkeys(item["record_id"] for item in packet["evidence"][1:]))
    require(
        basis == {
            "primary_record_id": selection["record_id"],
            "required_context_record_ids": expected_context,
            "evidence_packet_sha256": packet_sha256,
        },
        "invalid_handoff",
        "Candidate source basis is not the complete evidence packet.",
    )
    require(
        candidate["project_applicability"] == "not_decided"
        and candidate["compliance"] == "not_decided"
        and candidate["tailoring_status"] == "proposals_not_approved"
        and candidate["approval"] == "not_approved"
        and candidate["approved_baseline"] == "not_selected"
        and candidate["attestation"] == "candidate_interpretation_not_source_text_or_project_approval",
        "invalid_handoff",
        "Candidate decision boundaries are invalid.",
    )
    rights = _exact_keys(
        handoff["rights_provenance"],
        {"manifest", "claim", "authorization_effect"},
        "rights provenance",
    )
    manifest = rights["manifest"]
    claim = rights["claim"]
    require(
        isinstance(manifest, dict)
        and manifest.get("pack_id") == selection["pack_id"]
        and manifest.get("document_family_id") == selection["document_family_id"]
        and manifest.get("edition_id") == selection["edition_id"]
        and manifest.get("identifier") == selection["identifier"]
        and manifest.get("revision") == selection["revision"]
        and _package_representation(manifest) == selection["representation"]
        and manifest.get("coverage") == packet.get("completeness", {}).get("declared_pack_coverage"),
        "invalid_handoff",
        "Pack provenance does not match the selected evidence.",
    )
    claim = _exact_keys(
        claim,
        {"rights_schema_version", "content_class", "redistribution", "processing", "model_use", "statement"},
        "rights claim",
    )
    require(
        claim["rights_schema_version"] == "0.1.0"
        and all(isinstance(claim[key], str) and bool(claim[key]) for key in ("content_class", "redistribution", "model_use", "statement"))
        and isinstance(claim["processing"], list)
        and len(claim["processing"]) == len(set(claim["processing"]))
        and all(isinstance(item, str) and bool(item) for item in claim["processing"])
        and rights["authorization_effect"] == "none",
        "invalid_handoff",
        "Rights provenance cannot grant authorization.",
    )
    authorization = _exact_keys(
        handoff["authorization"],
        {"status", "principal_id", "policy_fingerprint", "authorization_effect", "durable_locator_is_bearer_authority", "future_resolution_requires_reauthorization", "copied_artifact_is_retroactively_revocable"},
        "handoff authorization",
    )
    require(
        authorization["status"] == "authorized_at_export"
        and isinstance(authorization["principal_id"], str)
        and bool(authorization["principal_id"])
        and isinstance(authorization["policy_fingerprint"], str)
        and HEX64.fullmatch(authorization["policy_fingerprint"]) is not None
        and authorization["authorization_effect"] == "none"
        and authorization["durable_locator_is_bearer_authority"] is False
        and authorization["future_resolution_requires_reauthorization"] is True
        and authorization["copied_artifact_is_retroactively_revocable"] is False,
        "invalid_handoff",
        "Handoff authorization boundary is invalid.",
    )
    require(
        handoff["reader"]
        == {
            "renderer": "standardsforge_source_first_html_v1",
            "scripts": "disabled",
            "network": "disabled_by_content_security_policy",
            "source_content_trust": "untrusted_data_never_instructions",
        },
        "invalid_handoff",
        "Reader trust boundary is invalid.",
    )
    require(
        isinstance(handoff["unresolved_evidence_issues"], list)
        and len(handoff["unresolved_evidence_issues"]) == len(set(handoff["unresolved_evidence_issues"]))
        and all(isinstance(item, str) and 1 <= len(item) <= 4096 for item in handoff["unresolved_evidence_issues"]),
        "invalid_handoff",
        "Unresolved evidence issues are invalid.",
    )


def validate_handoff_bundle(root: Path | str) -> dict[str, Any]:
    root = Path(root)
    require(root.is_dir() and not _is_link_like(root), "invalid_handoff", "Handoff bundle root is missing or linked.")
    root = root.resolve(strict=True)
    observed: set[str] = set()
    for path in root.iterdir():
        require(not _is_link_like(path), "invalid_handoff", "Handoff bundle entries cannot be links or junctions.")
        require(path.is_file(), "invalid_handoff", "Handoff bundle entries must be regular files.")
        observed.add(path.name)
    require(observed == EXPECTED_FILES, "invalid_handoff", "Handoff bundle file set is not closed.")
    manifest = _load_object(root / MANIFEST_NAME, "handoff manifest")
    _exact_keys(manifest, {"schema_version", "artifact_type", "status", "package_digest", "root_record_id", "handoff_sha256", "files"}, "handoff manifest")
    require(
        manifest["schema_version"] == "0.1.0"
        and manifest["artifact_type"] == "standardsforge_source_first_handoff_bundle"
        and manifest["status"] == "candidate_unapproved",
        "invalid_handoff",
        "Handoff manifest identity is invalid.",
    )
    require(isinstance(manifest["files"], list) and len(manifest["files"]) == 2, "invalid_handoff", "Handoff manifest file inventory is invalid.")
    expected_paths = [HANDOFF_NAME, READER_NAME]
    for entry, expected_path in zip(manifest["files"], expected_paths):
        entry = _exact_keys(entry, {"path", "bytes", "sha256"}, "handoff manifest file")
        require(entry["path"] == expected_path, "invalid_handoff", "Handoff manifest paths are noncanonical.")
        path = root / expected_path
        require(
            type(entry["bytes"]) is int
            and entry["bytes"] > 0
            and path.stat().st_size == entry["bytes"]
            and isinstance(entry["sha256"], str)
            and _sha256(path) == entry["sha256"],
            "invalid_handoff",
            "Handoff file failed inventory validation.",
        )
    handoff = _load_object(root / HANDOFF_NAME, "engineering handoff")
    _validate_handoff_shape(handoff)
    require(
        manifest["package_digest"] == handoff["source_selection"]["package_digest"]
        and manifest["root_record_id"] == handoff["source_selection"]["record_id"]
        and manifest["handoff_sha256"] == _sha256(root / HANDOFF_NAME),
        "invalid_handoff",
        "Handoff manifest identities do not match the handoff.",
    )
    require(
        (root / READER_NAME).read_bytes() == render_reader_html(handoff),
        "invalid_handoff",
        "Reader HTML is not the deterministic rendering of the handoff.",
    )
    return manifest


def export_engineering_handoff(
    db_path: Path | str,
    object_store: Path | str,
    package_digest: str,
    principal_id: str,
    candidate_path: Path | str,
    output_directory: Path | str,
    *,
    clause_reference: str | None = None,
    record_id: str | None = None,
) -> dict[str, Any]:
    require(
        clause_reference is not None or record_id is not None,
        "invalid_selector",
        "Handoff export requires a clause reference, record ID, or both.",
    )
    candidate = validate_candidate_draft(_load_object(Path(candidate_path), "candidate draft"))
    output = Path(output_directory)
    require(not output.exists() and not output.is_symlink(), "output_exists", "Handoff output already exists.")
    service = StandardsForgeService(Path(db_path), Path(object_store))
    packet = service.get_clause(
        package_digest,
        clause_reference,
        principal_id,
        response_profile=None,
        record_id=record_id,
    )
    package_row = service.store.authorized_package(principal_id, package_digest)
    handoff = _build_handoff(packet, package_row, principal_id, candidate)
    _validate_handoff_shape(handoff)

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    parent = parent.resolve(strict=True)
    require(not _is_link_like(parent), "invalid_output", "Handoff output parent cannot be a link or junction.")
    output = parent / output.name
    require(not output.exists(), "output_exists", "Handoff output already exists.")
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".partial", dir=parent))
    try:
        handoff_bytes = _pretty_json(handoff)
        reader_bytes = render_reader_html(handoff)
        (temporary / HANDOFF_NAME).write_bytes(handoff_bytes)
        (temporary / READER_NAME).write_bytes(reader_bytes)
        manifest = {
            "schema_version": "0.1.0",
            "artifact_type": "standardsforge_source_first_handoff_bundle",
            "status": "candidate_unapproved",
            "package_digest": package_digest,
            "root_record_id": handoff["source_selection"]["record_id"],
            "handoff_sha256": _sha256_bytes(handoff_bytes),
            "files": [
                {"path": HANDOFF_NAME, "bytes": len(handoff_bytes), "sha256": _sha256_bytes(handoff_bytes)},
                {"path": READER_NAME, "bytes": len(reader_bytes), "sha256": _sha256_bytes(reader_bytes)},
            ],
        }
        (temporary / MANIFEST_NAME).write_bytes(_pretty_json(manifest))
        validate_handoff_bundle(temporary)
        final_row = service.store.authorized_package(principal_id, package_digest)
        require(
            final_row["grant_policy_fingerprint"] == handoff["authorization"]["policy_fingerprint"],
            "authorization_changed",
            "Authorization changed during handoff export.",
        )
        try:
            os.mkdir(output)
        except FileExistsError as exc:
            raise StandardsForgeError("output_exists", "Handoff output already exists.") from exc
        activated: list[Path] = []
        try:
            for name in (HANDOFF_NAME, READER_NAME, MANIFEST_NAME):
                destination = output / name
                os.replace(temporary / name, destination)
                activated.append(destination)
            os.rmdir(temporary)
        except Exception:
            for path in reversed(activated):
                path.unlink(missing_ok=True)
            try:
                os.rmdir(output)
            except OSError:
                pass
            raise
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return {
        "artifact_type": "standardsforge_source_first_handoff_bundle",
        "status": "candidate_unapproved",
        "output_directory": str(output),
        "package_digest": package_digest,
        "root_record_id": handoff["source_selection"]["record_id"],
        "durable_locator": handoff["source_selection"]["durable_locator"],
        "handoff_sha256": manifest["handoff_sha256"],
        "manifest_sha256": _sha256(output / MANIFEST_NAME),
    }
