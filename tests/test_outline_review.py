from __future__ import annotations

import copy
import hashlib
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema.validators import validator_for
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.outline_compiler import compile_derived_outline_pack  # noqa: E402
from standardsforge.outline_review import export_outline_review_draft, promote_outline_review  # noqa: E402
from standardsforge.pack import open_validated_pack, validate_pack_directory  # noqa: E402
from standardsforge.review_shard import export_outline_review_shard  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402
from standardsforge.structure_compiler import compile_structured_page_pack_section, load_structure_annotations  # noqa: E402


class OutlineReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        from tests.test_outline_compiler import OutlineCompilerTests

        self.fixture = OutlineCompilerTests(methodName="test_compiles_installs_resolves_and_retrieves_unreviewed_outline_offline")
        self.fixture.setUp()
        self.root = self.fixture.root
        self.base = self.fixture.base_pack
        self.outline = self.root / "outline"
        compile_derived_outline_pack(self.base, self.outline)
        with open_validated_pack(self.outline) as pack:
            self.candidate = next(record for record in pack.records if record["kind"] == "section")
        self.draft_path = self.root / "draft.json"
        self.decision_path = self.root / "decision.json"
        self.annotations_path = self.root / "reviewed-annotations.json"

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _export(self) -> dict:
        return export_outline_review_draft(self.outline, self.base, self.candidate["record_id"], self.draft_path)

    def _decision(self, draft_digest: str) -> dict:
        draft = json.loads(self.draft_path.read_text(encoding="utf-8"))
        node = copy.deepcopy(draft["proposed_node"])
        node["derivation"] = {"method": "explicit_synthetic_review", "review_status": "human_reviewed"}
        return {
            "schema_version": "0.1.0",
            "draft_sha256": draft_digest,
            "review": {
                "reviewer_id": "synthetic-reviewer",
                "reviewer_type": "human",
                "reviewed_at": "2026-09-22T00:00:00Z",
                "method": "exact_span_and_heading_review",
                "tool": None,
                "unresolved_issues": [],
                "attestation": "extraction_review_not_project_applicability_or_approval",
            },
            "node": node,
        }

    def _write_decision(self, decision: dict) -> None:
        self.decision_path.write_text(json.dumps(decision, ensure_ascii=False), encoding="utf-8")

    def test_selected_candidate_roundtrips_to_reviewed_pack_offline(self) -> None:
        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")):
            exported = self._export()
            draft = json.loads(self.draft_path.read_text(encoding="utf-8"))
            self.assertEqual("proposed_unreviewed", draft["state"])
            self.assertEqual("proposed", draft["proposed_node"]["derivation"]["review_status"])
            self.assertEqual(self.candidate["structure"]["logical_id"], draft["proposed_node"]["logical_id"])
            decision = self._decision(exported["draft_sha256"])
            schemas = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in (ROOT / "contracts").glob("*.schema.json")
            }
            registry = Registry().with_resources(
                (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
            )
            for name, instance in (
                ("outline-review-draft.schema.json", draft),
                ("outline-review-decision.schema.json", decision),
            ):
                schema = schemas[name]
                validator_for(schema)(schema, registry=registry).validate(instance)
            self._write_decision(decision)
            promote_outline_review(self.draft_path, self.decision_path, self.outline, self.base, self.annotations_path)
            schema = schemas["structure-annotations.schema.json"]
            validator_for(schema)(schema, registry=registry).validate(json.loads(self.annotations_path.read_text(encoding="utf-8")))
            first = compile_structured_page_pack_section(self.base, self.outline, self.annotations_path, self.root / "reviewed-first")
            second = compile_structured_page_pack_section(self.base, self.outline, self.annotations_path, self.root / "reviewed-second")
        self.assertEqual(first["package_digest"], second["package_digest"])
        reviewed = validate_pack_directory(self.root / "reviewed-first")
        with open_validated_pack(self.base) as base:
            self.assertEqual(base.rights["redistribution"], reviewed.rights["redistribution"])
            self.assertEqual(base.rights["processing"], reviewed.rights["processing"])
        self.assertTrue((self.root / "reviewed-first" / "sources" / "test.pdf").is_file())
        self.assertEqual("reviewed_structure", reviewed.manifest["representation"])
        self.assertEqual(1, len(reviewed.records))
        record = reviewed.records[0]
        self.assertEqual(self.candidate["text"], record["text"])
        self.assertEqual("human_reviewed", record["derivation"]["review_status"])
        self.assertEqual(draft["proposed_node"]["logical_id"], record["structure"]["logical_id"])
        self.assertEqual(exported["source_page_pack_digest"], json.loads((self.root / "reviewed-first" / "structure-report.json").read_text(encoding="utf-8"))["source_page_pack_digest"])
        policy = self.root / "reviewed-policy.json"
        policy.write_text(json.dumps({
            "policy_version": "0.1.0", "policy_id": "reviewed-outline-test",
            "principal_id": "reviewer", "allow_admin_install": True, "allow_serve": True,
            "allowed_pack_ids": [reviewed.manifest["pack_id"]],
            "allowed_content_classes": [reviewed.rights["content_class"]],
        }), encoding="utf-8")
        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")):
            service = StandardsForgeService(self.root / "reviewed-memory.db", self.root / "reviewed-objects")
            installed = service.install_pack(self.root / "reviewed-first", policy)
            packet = service.get_clause(installed["package_digest"], record["clause_reference"], "reviewer", response_profile="compact_evidence_v1")
        self.assertEqual(record["text"], packet["evidence"]["records"][0]["text"])
        self.assertEqual("human_verified", packet["evidence"]["records"][0]["structure"]["review"]["status"])
        self.assertFalse(packet["completeness"]["complete_for_requested_scope"])
        source = packet["evidence"]["source_files"][0]
        self.assertTrue(source["source_checks"]["source_digest_verified"])
        self.assertTrue(source["source_checks"]["extracted_text_digest_verified"])

    def test_rejects_draft_as_reviewed_and_stale_or_unreviewed_decisions(self) -> None:
        exported = self._export()
        with self.assertRaises(StandardsForgeError):
            load_structure_annotations(self.draft_path)
        decision = self._decision(exported["draft_sha256"])
        decision["draft_sha256"] = "0" * 64
        self._write_decision(decision)
        with self.assertRaisesRegex(StandardsForgeError, "draft bytes"):
            promote_outline_review(self.draft_path, self.decision_path, self.outline, self.base, self.annotations_path)
        decision["draft_sha256"] = exported["draft_sha256"]
        decision["node"]["derivation"]["review_status"] = "proposed"
        self._write_decision(decision)
        with self.assertRaises(StandardsForgeError):
            promote_outline_review(self.draft_path, self.decision_path, self.outline, self.base, self.annotations_path)
        self.assertFalse(self.annotations_path.exists())

    def test_rejects_changed_source_and_wrong_reviewed_span(self) -> None:
        exported = self._export()
        decision = self._decision(exported["draft_sha256"])
        decision["node"]["source_spans"][0]["start_byte"] += 1
        self._write_decision(decision)
        with self.assertRaises(StandardsForgeError):
            promote_outline_review(self.draft_path, self.decision_path, self.outline, self.base, self.annotations_path)
        decision = self._decision(exported["draft_sha256"])
        self._write_decision(decision)
        (self.base / "sources" / "test.extracted.txt").write_text("changed", encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            promote_outline_review(self.draft_path, self.decision_path, self.outline, self.base, self.annotations_path)

    def test_rejects_forged_draft_even_with_matching_decision_hash(self) -> None:
        self._export()
        draft = json.loads(self.draft_path.read_text(encoding="utf-8"))
        draft["proposed_node"]["heading"] = "forged heading"
        self.draft_path.write_text(json.dumps(draft), encoding="utf-8")
        decision = self._decision(hashlib.sha256(self.draft_path.read_bytes()).hexdigest())
        self._write_decision(decision)
        with self.assertRaisesRegex(StandardsForgeError, "exact source outline candidate"):
            promote_outline_review(self.draft_path, self.decision_path, self.outline, self.base, self.annotations_path)

    def test_compiler_rechecks_exact_outline_proposal(self) -> None:
        exported = self._export()
        self._write_decision(self._decision(exported["draft_sha256"]))
        promote_outline_review(self.draft_path, self.decision_path, self.outline, self.base, self.annotations_path)
        annotations = json.loads(self.annotations_path.read_text(encoding="utf-8"))
        annotations["candidate_content_sha256"] = "0" * 64
        self.annotations_path.write_text(json.dumps(annotations), encoding="utf-8")
        with self.assertRaisesRegex(StandardsForgeError, "exact outline proposal"):
            compile_structured_page_pack_section(self.base, self.outline, self.annotations_path, self.root / "rejected")
        self.assertFalse((self.root / "rejected").exists())

    def test_parameterized_ambiguous_numbered_evidence_requires_explicit_kind_and_reference(self) -> None:
        from tests.test_outline_compiler import OutlineCompilerTests

        class ParameterizedFixture(OutlineCompilerTests):
            def _write_base_page_pack(self) -> None:
                self.page_text += "2.3.1  Maintain 15 kPa (2.2 psi) for 30 minutes at 25 C.\n"
                super()._write_base_page_pack()

        fixture = ParameterizedFixture(methodName="test_compiles_installs_resolves_and_retrieves_unreviewed_outline_offline")
        fixture.setUp()
        try:
            outline = fixture.root / "parameterized-outline"
            compile_derived_outline_pack(fixture.base_pack, outline)
            with open_validated_pack(outline) as pack:
                candidate = next(record for record in pack.records if "Maintain 15 kPa" in record["text"])
                self.assertEqual("unsupported_region", candidate["kind"])
                self.assertIn("ambiguous-numbered", candidate["clause_reference"])
                unrelated_unsupported = next(record for record in pack.records if record["kind"] == "unsupported_region" and "ambiguous-numbered" not in record["clause_reference"])
            with self.assertRaises(StandardsForgeError):
                export_outline_review_draft(outline, fixture.base_pack, unrelated_unsupported["record_id"], fixture.root / "unrelated-draft.json")
            selection = fixture.root / "selection.json"
            selection.write_text(json.dumps({"schema_version": "0.1.0", "shard_id": "pending-rejected", "record_ids": [candidate["record_id"]]}), encoding="utf-8")
            with self.assertRaises(StandardsForgeError):
                export_outline_review_shard(outline, fixture.base_pack, selection, fixture.root / "pending-shard")
            self.assertFalse((fixture.root / "pending-shard").exists())
            draft_path = fixture.root / "pending-draft.json"
            exported = export_outline_review_draft(outline, fixture.base_pack, candidate["record_id"], draft_path)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual("0.2.0", draft["schema_version"])
            self.assertEqual("unsupported_region", draft["source_candidate_kind"])
            self.assertEqual("pending_explicit_reviewer_kind", draft["classification_state"])
            self.assertEqual("unsupported_region", draft["proposed_node"]["kind"])
            schemas = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in (ROOT / "contracts").glob("*.schema.json")
            }
            registry = Registry().with_resources(
                (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
            )
            schema = schemas["outline-review-draft.schema.json"]
            validator_for(schema)(schema, registry=registry).validate(draft)
            node = copy.deepcopy(draft["proposed_node"])
            node["derivation"] = {"method": "synthetic_exact_parameter_review", "review_status": "human_reviewed"}
            decision = {
                "schema_version": "0.1.0", "draft_sha256": exported["draft_sha256"],
                "review": {
                    "reviewer_id": "synthetic-reviewer", "reviewer_type": "human",
                    "reviewed_at": "2026-09-22T00:00:00Z",
                    "method": "exact_numbered_clause_and_source_review", "tool": None,
                    "unresolved_issues": [],
                    "attestation": "extraction_review_not_project_applicability_or_approval",
                },
                "node": node,
            }
            decision_path = fixture.root / "decision.json"
            annotations = fixture.root / "reviewed.json"
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            with self.assertRaisesRegex(StandardsForgeError, "reviewed structural kind"):
                promote_outline_review(draft_path, decision_path, outline, fixture.base_pack, annotations)
            node["kind"] = "clause"
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            with self.assertRaisesRegex(StandardsForgeError, "reviewed clause reference"):
                promote_outline_review(draft_path, decision_path, outline, fixture.base_pack, annotations)
            node["clause_reference"] = "2.3.1"
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            promote_outline_review(draft_path, decision_path, outline, fixture.base_pack, annotations)
            validator_for(schemas["structure-annotations.schema.json"])(schemas["structure-annotations.schema.json"], registry=registry).validate(json.loads(annotations.read_text(encoding="utf-8")))
            compiled = fixture.root / "reviewed-pack"
            compile_structured_page_pack_section(fixture.base_pack, outline, annotations, compiled)
            reviewed = validate_pack_directory(compiled)
            self.assertEqual("clause", reviewed.records[0]["kind"])
            self.assertEqual("2.3.1", reviewed.records[0]["clause_reference"])
            self.assertEqual(draft["proposed_node"]["exact_text"], reviewed.records[0]["text"])
            self.assertEqual("human_reviewed", reviewed.records[0]["derivation"]["review_status"])
            decision["draft_sha256"] = "0" * 64
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            with self.assertRaises(StandardsForgeError):
                promote_outline_review(draft_path, decision_path, outline, fixture.base_pack, fixture.root / "stale-reviewed.json")
            decision["draft_sha256"] = exported["draft_sha256"]
            decision["node"]["source_spans"][0]["start_byte"] += 1
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            with self.assertRaises(StandardsForgeError):
                promote_outline_review(draft_path, decision_path, outline, fixture.base_pack, fixture.root / "wrong-span-reviewed.json")
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
