from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.benchmark import validate_suite_document  # noqa: E402
from standardsforge.doctor import run_doctor  # noqa: E402
from standardsforge.handoff import export_engineering_handoff, validate_handoff_bundle  # noqa: E402
from standardsforge.pack import validate_pack_directory  # noqa: E402
from standardsforge.policy import load_policy  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402
from standardsforge.source_catalog import load_source_catalog  # noqa: E402


def load_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def load_schemas() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted((ROOT / "contracts").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise SystemExit(f"{path.name} must contain one JSON object.")
        schemas[path.name] = schema
    return schemas


def check_schema_documents(schemas: dict[str, dict[str, Any]]) -> Registry:
    resources: list[tuple[str, Resource[Any]]] = []
    for name, schema in schemas.items():
        validator_for(schema).check_schema(schema)
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise SystemExit(f"{name} must declare a non-empty $id.")
        resources.append((schema_id, Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate_with_schema(
    schemas: dict[str, dict[str, Any]],
    registry: Registry,
    schema_name: str,
    instance: Any,
) -> None:
    schema = schemas[schema_name]
    validator_for(schema)(schema, registry=registry).validate(instance)


def validate_repository_instances(
    schemas: dict[str, dict[str, Any]], registry: Registry
) -> list[str]:
    instances: list[tuple[str, Path]] = []
    for pack_root in sorted((ROOT / "examples" / "packs").iterdir()):
        if not pack_root.is_dir():
            continue
        instances.extend(
            (
                ("pack-manifest.schema.json", pack_root / "manifest.json"),
                ("inventory.schema.json", pack_root / "inventory.json"),
                ("rights.schema.json", pack_root / "rights.json"),
            )
        )
        records = json.loads((pack_root / "records.json").read_text(encoding="utf-8"))
        records_schema = (
            "records-v0.2.schema.json"
            if records.get("schema_version") == "0.2.0"
            else "records.schema.json"
        )
        validate_with_schema(schemas, registry, records_schema, records)
        instances.append((records_schema, pack_root / "records.json"))

    instances.extend(
        ("local-policy.schema.json", path)
        for path in sorted((ROOT / "examples" / "policies").glob("*.json"))
    )
    instances.extend(
        ("source-catalog.schema.json", path)
        for path in sorted((ROOT / "catalog").glob("*.json"))
    )
    instances.extend(
        ("benchmark-suite.schema.json", path)
        for path in sorted((ROOT / "benchmarks").glob("*.json"))
    )
    instances.extend(
        ("handoff-candidate.schema.json", path)
        for path in sorted((ROOT / "examples" / "handoffs").glob("*.json"))
    )

    validated: list[str] = []
    for schema_name, path in instances:
        instance = json.loads(path.read_text(encoding="utf-8"))
        validate_with_schema(schemas, registry, schema_name, instance)
        if schema_name == "benchmark-suite.schema.json":
            validate_suite_document(instance, ROOT)
        validated.append(path.relative_to(ROOT).as_posix())
    return validated


def _error_envelope(operation: Any) -> dict[str, Any]:
    try:
        operation()
    except StandardsForgeError as exc:
        return {"ok": False, "error": exc.as_dict()}
    raise AssertionError("The contract error case unexpectedly succeeded.")


def _build_semantic_contract_pack(base: Path) -> Path:
    source = ROOT / "examples" / "packs" / "fictional-adapter-v1"
    target = base / "semantic-contract-pack"
    shutil.copytree(source, target)
    records_path = target / "records.json"
    records_document = json.loads(records_path.read_text(encoding="utf-8"))
    record = next(
        item for item in records_document["records"] if item["record_id"] == "clause-4.2.2"
    )
    source_path = target / record["source"]["path"]
    source_bytes = source_path.read_bytes()
    text_bytes = record["text"].encode("utf-8")
    start_byte = source_bytes.index(text_bytes)
    content_sha256 = hashlib.sha256(text_bytes).hexdigest()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    record["structure"] = {
        "logical_id": "synthetic:semantic-contract:clause-4.2.2",
        "content_sha256": content_sha256,
        "parent_logical_id": None,
        "ordinal": 1,
        "source_spans": [
            {
                "path": record["source"]["path"],
                "sha256": source_sha256,
                "text_path": record["source"]["path"],
                "text_sha256": source_sha256,
                "physical_page": 1,
                "start_byte": start_byte,
                "end_byte": start_byte + len(text_bytes),
                "quote_sha256": content_sha256,
            }
        ],
        "relationships": [],
        "semantics": {
            "schema_version": "0.1.0",
            "content_role": "requirement_candidate",
            "normativity": "normative",
            "statement": {
                "subject": "adapter",
                "action": "prevent",
                "modality": "shall",
                "polarity": "affirmative",
                "exact_text": record["text"],
                "span_indices": [0],
            },
            "qualifiers": [
                {
                    "kind": "test_condition",
                    "exact_text": "during a 10-minute synthetic spray exposure",
                    "span_indices": [0],
                }
            ],
            "quantities": [
                {
                    "raw": "10-minute",
                    "value": "10",
                    "unit": "minute",
                    "tolerance": None,
                    "span_indices": [0],
                }
            ],
            "unresolved_issues": [],
            "project_applicability": "not_decided",
        },
        "review": {
            "schema_version": "0.1.0",
            "status": "agent_reviewed",
            "reviewed_content_sha256": content_sha256,
            "scope": "structure_and_semantics",
            "reviewer": {"id": "contract-review-agent", "type": "agent"},
            "reviewed_at": "2026-09-22T12:00:00Z",
            "method": "synthetic_contract_validation",
            "tool": {
                "name": "synthetic-review-agent",
                "version": "1.0",
                "configuration_sha256": "b" * 64,
            },
            "unresolved_issues": [],
            "attestation": "extraction_review_not_project_applicability_or_approval",
        },
    }
    records_bytes = (json.dumps(records_document, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    records_path.write_bytes(records_bytes)
    inventory_path = target / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records_entry = next(item for item in inventory["files"] if item["path"] == "records.json")
    records_entry.update(
        {"sha256": hashlib.sha256(records_bytes).hexdigest(), "bytes": len(records_bytes)}
    )
    inventory_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def validate_actual_query_contracts(
    schemas: dict[str, dict[str, Any]], registry: Registry
) -> dict[str, int]:
    with tempfile.TemporaryDirectory(prefix="standardsforge-contracts-") as temporary:
        base = Path(temporary)
        service = StandardsForgeService(base / "memory.db", base / "objects")
        policy = ROOT / "examples" / "policies" / "local-synthetic.json"
        first_digest = service.install_pack(
            _build_semantic_contract_pack(base), policy
        )["package_digest"]
        second_digest = service.install_pack(
            ROOT / "examples" / "packs" / "fictional-adapter-v2", policy
        )["package_digest"]

        first_page = service.enumerate_obligations(
            first_digest, "local-user", limit=1
        )
        next_cursor = first_page["page"]["next_cursor"]
        if not isinstance(next_cursor, str):
            raise AssertionError("The continuation fixture did not produce a cursor.")
        final_page = service.enumerate_obligations(
            first_digest, "local-user", limit=1, cursor=next_cursor
        )
        first_document_page = service.list_documents("local-user", "EXAMPLE-SPEC", limit=1)
        document_cursor = first_document_page["page"]["next_cursor"]
        if not isinstance(document_cursor, str):
            raise AssertionError("The document inventory fixture did not produce a cursor.")
        final_document_page = service.list_documents(
            "local-user", "EXAMPLE-SPEC", limit=1, cursor=document_cursor
        )

        detailed_results = [
            service.search("axial load", "local-user"),
            first_document_page,
            final_document_page,
            service.resolve_document(
                "EXAMPLE-SPEC-100",
                "local-user",
                "example:spec-100:2025-a",
                "curated_records",
            ),
            service.get_clause(first_digest, "4.2.1", "local-user"),
            service.build_context(
                first_digest, ["4.2.1", "4.2.2"], "local-user"
            ),
            first_page,
            final_page,
            service.diff_editions(
                first_digest, second_digest, "local-user"
            ),
            service.search(
                "steady axial load", "local-user", query_mode="exact_phrase"
            ),
            service.search(
                "axial ingress", "local-user", query_mode="any_terms"
            ),
            service.search(
                "How should connectors be retained under loads?",
                "local-user",
                query_mode="natural_language",
            ),
        ]
        profile_results = [
            service.get_clause(
                first_digest,
                "4.2.1",
                "local-user",
                response_profile="compact_evidence_v1",
            ),
            service.build_context(
                first_digest,
                ["4.2.1", "4.2.2"],
                "local-user",
                response_profile="compact_evidence_v1",
            ),
            service.get_clause(
                first_digest,
                "4.2.1",
                "local-user",
                response_profile="concise_evidence_v1",
            ),
            service.build_context(
                first_digest,
                ["4.2.1", "4.2.2"],
                "local-user",
                response_profile="concise_evidence_v1",
            ),
        ]

        for result in detailed_results:
            validate_with_schema(
                schemas, registry, "query-response.schema.json", result
            )
            validate_with_schema(
                schemas,
                registry,
                "success-response.schema.json",
                {"ok": True, "result": result},
            )
        for result in profile_results:
            schema_name = (
                "compact-evidence-response.schema.json"
                if result["response_profile"] == "compact_evidence_v1"
                else "concise-evidence-response.schema.json"
            )
            validate_with_schema(schemas, registry, schema_name, result)
            validate_with_schema(
                schemas,
                registry,
                "success-response.schema.json",
                {"ok": True, "result": result},
            )

        doctor_result = run_doctor(
            base / "memory.db",
            base / "objects",
            policy_path=policy,
            principal_id="local-user",
            full_integrity=True,
        )
        validate_with_schema(
            schemas, registry, "doctor-response.schema.json", doctor_result
        )
        if not doctor_result["ready"] or not doctor_result["integrity"]["complete"]:
            raise AssertionError("The actual full-integrity doctor report was not ready.")

        malformed_doctor = json.loads(json.dumps(doctor_result))
        malformed_doctor["ready"] = False
        try:
            validate_with_schema(
                schemas, registry, "doctor-response.schema.json", malformed_doctor
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("An inconsistent doctor readiness report passed validation.")

        errors = [
            _error_envelope(lambda: service.search(" ", "local-user")),
            _error_envelope(
                lambda: service.get_clause(
                    first_digest, "4.2.1", "unauthorized-user"
                )
            ),
            {
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": "The operation failed unexpectedly; no partial success is asserted.",
                },
            },
        ]
        for error in errors:
            validate_with_schema(
                schemas, registry, "error-response.schema.json", error
            )
        resolve_not_found = _error_envelope(
            lambda: service.resolve_document("EXAMPLE-SPEC", "local-user")
        )
        validate_with_schema(schemas, registry, "error-response.schema.json", resolve_not_found)
        validate_with_schema(
            schemas, registry, "resolve-document-not-found-error.schema.json", resolve_not_found
        )
        errors.append(resolve_not_found)

        malformed = {"ok": True, "result": dict(detailed_results[0])}
        del malformed["result"]["operation"]
        try:
            validate_with_schema(
                schemas, registry, "success-response.schema.json", malformed
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("A malformed success packet passed contract validation.")

        malformed_error = {
            "ok": False,
            "error": {"code": "invalid_query"},
        }
        try:
            validate_with_schema(
                schemas,
                registry,
                "error-response.schema.json",
                malformed_error,
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("A malformed error packet passed contract validation.")

        detailed_context = next(
            result for result in detailed_results if result["operation"] == "build_context"
        )
        diff_result = next(
            result for result in detailed_results if result["operation"] == "diff_editions"
        )
        malformed_semantics = json.loads(json.dumps(detailed_context))
        semantic_record = next(
            item for item in malformed_semantics["evidence"] if item.get("structure", {}).get("semantics")
        )
        semantic_record["structure"]["semantics"]["project_applicability"] = "applicable"
        try:
            validate_with_schema(
                schemas, registry, "query-response.schema.json", malformed_semantics
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("A false semantic applicability claim passed response validation.")

        malformed_review = json.loads(json.dumps(profile_results[3]))
        reviewed_node = next(
            item
            for item in malformed_review["provenance"]["structure_nodes"]
            if item.get("review")
        )
        reviewed_node["review"]["status"] = "human_verified"
        try:
            validate_with_schema(
                schemas,
                registry,
                "concise-evidence-response.schema.json",
                malformed_review,
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("A false human review claim passed response validation.")

        missing_review = json.loads(json.dumps(detailed_context))
        semantic_record = next(
            item for item in missing_review["evidence"] if item.get("structure", {}).get("semantics")
        )
        del semantic_record["structure"]["review"]
        try:
            validate_with_schema(
                schemas, registry, "query-response.schema.json", missing_review
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("Semantic evidence without review passed response validation.")

        malformed_interpretation = json.loads(json.dumps(detailed_results[-1]))
        malformed_interpretation["query_interpretation"]["mode"] = "implicit"
        try:
            validate_with_schema(
                schemas,
                registry,
                "query-response.schema.json",
                malformed_interpretation,
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("An undeclared search query mode passed response validation.")

        missing_natural_strategy = json.loads(json.dumps(detailed_results[-1]))
        del missing_natural_strategy["query_interpretation"]["selected_strategy"]
        try:
            validate_with_schema(
                schemas, registry, "query-response.schema.json", missing_natural_strategy
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("A natural-language response without its selected strategy passed validation.")

        exact_with_natural_fields = json.loads(json.dumps(detailed_results[0]))
        exact_with_natural_fields["query_interpretation"]["selected_strategy"] = "stemmed_all_terms"
        try:
            validate_with_schema(
                schemas, registry, "query-response.schema.json", exact_with_natural_fields
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("An exact search response carrying natural-only fields passed validation.")

        malformed_diff_packets: list[tuple[dict[str, Any], str]] = []
        moved_without_after = json.loads(json.dumps(diff_result))
        moved_change = next(
            item for item in moved_without_after["changes"] if item["status"] == "modified"
        )
        moved_change["status"] = "moved"
        moved_change["source_location_changed"] = True
        del moved_change["after"]
        malformed_diff_packets.append(
            (moved_without_after, "A moved change without after evidence passed response validation.")
        )

        changed_target_without_status = json.loads(json.dumps(diff_result))
        target_cause = next(
            item["cause"]
            for item in changed_target_without_status["dependency_impact_paths"]
            if item["cause"]["type"] == "target_record_changed"
        )
        del target_cause["status"]
        malformed_diff_packets.append(
            (
                changed_target_without_status,
                "A changed-target cause without status passed response validation.",
            )
        )

        edge_cause_with_status = json.loads(json.dumps(diff_result))
        edge_cause = next(
            item["cause"]
            for item in edge_cause_with_status["dependency_impact_paths"]
            if item["cause"]["type"] == "target_record_changed"
        )
        edge_cause["type"] = "dependency_edge_added"
        malformed_diff_packets.append(
            (edge_cause_with_status, "An edge-delta cause with status passed response validation.")
        )

        short_dependency_edge = json.loads(json.dumps(diff_result))
        short_dependency_edge["dependency_edges_added"] = [["a", "b", "c"]]
        malformed_diff_packets.append(
            (short_dependency_edge, "A short dependency-edge tuple passed response validation.")
        )

        for malformed_diff, message in malformed_diff_packets:
            try:
                validate_with_schema(
                    schemas, registry, "query-response.schema.json", malformed_diff
                )
            except ValidationError:
                pass
            else:
                raise AssertionError(message)

        handoff_root = base / "contract-handoff"
        export_engineering_handoff(
            base / "memory.db",
            base / "objects",
            first_digest,
            "local-user",
            ROOT / "examples" / "handoffs" / "fictional-adapter-requirement-draft.json",
            handoff_root,
            record_id="clause-4.2.1",
        )
        handoff = json.loads((handoff_root / "evidence-handoff.json").read_text(encoding="utf-8"))
        handoff_manifest = validate_handoff_bundle(handoff_root)
        validate_with_schema(schemas, registry, "engineering-handoff.schema.json", handoff)
        validate_with_schema(schemas, registry, "handoff-bundle.schema.json", handoff_manifest)
        validate_with_schema(schemas, registry, "query-response.schema.json", handoff["evidence_packet"])

        false_approval = json.loads(json.dumps(handoff))
        false_approval["candidate"]["approval"] = "approved"
        try:
            validate_with_schema(
                schemas, registry, "engineering-handoff.schema.json", false_approval
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("A handoff with a false approval state passed validation.")

        return {
            "detailed_results": len(detailed_results),
            "profile_results": len(profile_results),
            "doctor_results": 1,
            "handoff_results": 1,
            "typed_errors": len(errors),
            "negative_cases": 12,
        }


def validate_semantic_contracts(
    schemas: dict[str, dict[str, Any]], registry: Registry
) -> dict[str, int]:
    semantic = {
        "schema_version": "0.1.0",
        "content_role": "requirement_candidate",
        "normativity": "normative",
        "statement": {
            "subject": "equipment",
            "action": "maintain",
            "modality": "shall",
            "polarity": "affirmative",
            "exact_text": "The equipment shall maintain 25°C when energized.",
            "span_indices": [0],
        },
        "qualifiers": [
            {"kind": "condition", "exact_text": "when energized", "span_indices": [0]},
            {
                "kind": "exception",
                "exact_text": "Unless safety override is active",
                "span_indices": [1],
            },
        ],
        "quantities": [
            {
                "raw": "25°C",
                "value": "25",
                "unit": "°C",
                "tolerance": None,
                "span_indices": [0],
            }
        ],
        "unresolved_issues": [],
        "project_applicability": "not_decided",
    }
    review = {
        "schema_version": "0.1.0",
        "status": "agent_reviewed",
        "reviewed_content_sha256": "a" * 64,
        "scope": "structure_and_semantics",
        "reviewer": {"id": "contract-review-agent", "type": "agent"},
        "reviewed_at": "2026-09-22T12:00:00Z",
        "method": "synthetic_contract_validation",
        "tool": {
            "name": "synthetic-review-agent",
            "version": "1.0",
            "configuration_sha256": "b" * 64,
        },
        "unresolved_issues": [],
        "attestation": "extraction_review_not_project_applicability_or_approval",
    }
    annotation_review = {
        "reviewer_id": review["reviewer"]["id"],
        "reviewer_type": review["reviewer"]["type"],
        "reviewed_at": review["reviewed_at"],
        "method": review["method"],
        "tool": review["tool"],
        "unresolved_issues": [],
        "attestation": review["attestation"],
    }
    annotation = {
        "schema_version": "0.2.0",
        "document_id": "SYNTHETIC-SEMANTIC-CONTRACT",
        "edition_id": "synthetic:semantic-contract:2026",
        "source_pdf_sha256": "c" * 64,
        "compiler": {"name": "pypdf", "version": "6.19.0"},
        "extraction_mode": "simple",
        "text_encoding": "UTF-8",
        "offset_convention": "half_open_utf8_byte_offsets_per_physical_page",
        "review": annotation_review,
        "nodes": [
            {
                "logical_id": "synthetic:requirement:1",
                "kind": "clause",
                "ordinal": 1,
                "clause_reference": "1",
                "heading": "Synthetic requirement",
                "statement_role": "obligation",
                "exact_text": "The equipment shall maintain 25°C when energized.\nUnless safety override is active",
                "source_spans": [
                    {
                        "physical_page": 1,
                        "page_text_sha256": "d" * 64,
                        "start_byte": 0,
                        "end_byte": 51,
                    },
                    {
                        "physical_page": 2,
                        "page_text_sha256": "e" * 64,
                        "start_byte": 0,
                        "end_byte": 32,
                    },
                ],
                "content_sha256": "f" * 64,
                "derivation": {
                    "method": "synthetic_contract_validation",
                    "review_status": "agent_reviewed",
                },
                "semantics": semantic,
            }
        ],
        "relationships": [],
        "unsupported_regions": [],
    }
    validate_with_schema(schemas, registry, "semantic-record.schema.json", semantic)
    validate_with_schema(schemas, registry, "review-event.schema.json", review)
    validate_with_schema(
        schemas, registry, "structure-annotations.schema.json", annotation
    )

    invalid_semantic = dict(semantic, project_applicability="applicable")
    invalid_review = dict(review, attestation="approved_for_project_use")
    missing_agent_tool = dict(review, tool=None)
    false_human_review = dict(review, status="human_verified")
    for schema_name, instance in (
        ("semantic-record.schema.json", invalid_semantic),
        ("review-event.schema.json", invalid_review),
        ("review-event.schema.json", missing_agent_tool),
        ("review-event.schema.json", false_human_review),
    ):
        try:
            validate_with_schema(schemas, registry, schema_name, instance)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"A malformed {schema_name} instance passed validation.")

    legacy_semantics = json.loads(json.dumps(annotation))
    legacy_semantics["schema_version"] = "0.1.0"
    missing_annotation_tool = json.loads(json.dumps(annotation))
    missing_annotation_tool["review"]["tool"] = None
    for instance in (legacy_semantics, missing_annotation_tool):
        try:
            validate_with_schema(
                schemas, registry, "structure-annotations.schema.json", instance
            )
        except ValidationError:
            pass
        else:
            raise AssertionError(
                "A malformed structure annotation instance passed validation."
            )
    return {"positive_instances": 3, "negative_cases": 6}


def main() -> int:
    schemas = load_schemas()
    registry = check_schema_documents(schemas)
    validated_instances = validate_repository_instances(schemas, registry)

    requirements = load_json("docs/requirements/requirements.json")
    tasks = load_json("backlog/tasks.json")
    requirement_ids = {item["id"] for item in requirements["requirements"]}
    for task in tasks["tasks"]:
        missing = sorted(set(task["requirements"]) - requirement_ids)
        if missing:
            raise SystemExit(
                f"{task['task_id']} references missing requirements: {missing}"
            )

    packs = []
    for relative in (
        "examples/packs/fictional-adapter-v1",
        "examples/packs/fictional-adapter-v2",
    ):
        pack = validate_pack_directory(ROOT / relative)
        packs.append(
            {
                "pack_id": pack.manifest["pack_id"],
                "edition_id": pack.manifest["edition_id"],
                "package_digest": pack.package_digest,
                "records": len(pack.records),
            }
        )

    policy = load_policy(ROOT / "examples/policies/local-synthetic.json")
    source_catalogs = [
        load_source_catalog(ROOT / "catalog/mil-format-authorities.json"),
        load_source_catalog(ROOT / "catalog/mil-std-810h.json"),
    ]
    response_contracts = validate_actual_query_contracts(schemas, registry)
    semantic_contracts = validate_semantic_contracts(schemas, registry)
    output = {
        "ok": True,
        "task_ids": [task["task_id"] for task in tasks["tasks"]],
        "requirement_count": len(requirement_ids),
        "schema_documents": sorted(schemas),
        "validated_contract_instances": validated_instances,
        "response_contracts": response_contracts,
        "semantic_contracts": semantic_contracts,
        "packs": packs,
        "policy_fingerprint": policy.fingerprint,
        "source_catalogs": [
            {
                "catalog_id": source_catalog["catalog_id"],
                "documents": [
                    document["document_id"]
                    for document in source_catalog["documents"]
                ],
            }
            for source_catalog in source_catalogs
        ],
        "limitations": [
            "Real source PDFs are local ignored inputs, not repository fixtures.",
            "PDF text-layer compilation, one full-document unreviewed derived outline, one reviewed structural slice, and one synthetic reviewed semantic packet are implemented; document-wide visual and reviewed semantic extraction remain unqualified.",
        ],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
