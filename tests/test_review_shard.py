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
from standardsforge.pack import open_validated_pack, validate_pack_directory  # noqa: E402
from standardsforge.review_shard import export_outline_review_shard, merge_outline_review_shard  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402
from standardsforge.structure_compiler import compile_structured_page_pack_section  # noqa: E402


class ReviewShardTests(unittest.TestCase):
    def setUp(self) -> None:
        from tests.test_outline_compiler import OutlineCompilerTests

        self.fixture = OutlineCompilerTests(methodName="test_compiles_installs_resolves_and_retrieves_unreviewed_outline_offline")
        self.fixture.setUp()
        self.root = self.fixture.root
        self.base = self.fixture.base_pack
        self.outline = self.root / "outline"
        compile_derived_outline_pack(self.base, self.outline)
        with open_validated_pack(self.outline) as pack:
            self.candidates = [record for record in pack.records if record["kind"] in {"section", "clause"}][:2]
        self.assertEqual(2, len(self.candidates))
        self.selection = self.root / "selection.json"
        self.shard = self.root / "shard"
        self.decisions = self.root / "decisions"
        self.annotations = self.root / "annotations.json"
        self.selection.write_text(json.dumps({
            "schema_version": "0.1.0", "shard_id": "synthetic-section-1",
            "record_ids": [candidate["record_id"] for candidate in reversed(self.candidates)],
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _export(self) -> None:
        export_outline_review_shard(self.outline, self.base, self.selection, self.shard)

    def _decide(self) -> None:
        self.decisions.mkdir()
        manifest = json.loads((self.shard / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(2, manifest["candidate_count"])
        for index, entry in enumerate(manifest["candidates"]):
            draft = json.loads((self.shard / entry["draft_path"]).read_text(encoding="utf-8"))
            node = copy.deepcopy(draft["proposed_node"])
            reviewer_type = "human" if index == 0 else "agent"
            node["derivation"] = {
                "method": "explicit_synthetic_review",
                "review_status": "human_reviewed" if reviewer_type == "human" else "agent_reviewed",
            }
            decision = {
                "schema_version": "0.1.0",
                "draft_sha256": entry["draft_sha256"],
                "review": {
                    "reviewer_id": f"synthetic-{reviewer_type}",
                    "reviewer_type": reviewer_type,
                    "reviewed_at": "2026-09-22T00:00:00Z",
                    "method": "exact_source_and_structure_review",
                    "tool": None if reviewer_type == "human" else {
                        "name": "synthetic-test-tool", "version": "1", "configuration_sha256": "0" * 64,
                    },
                    "unresolved_issues": [],
                    "attestation": "extraction_review_not_project_applicability_or_approval",
                },
                "node": node,
            }
            decision_path = self.decisions / f"{hashlib.sha256(entry['candidate_record_id'].encode()).hexdigest()}.json"
            decision_path.write_text(json.dumps(decision), encoding="utf-8")

    def _merge(self) -> None:
        merge_outline_review_shard(self.shard, self.decisions, self.outline, self.base, self.annotations)

    def test_offline_deterministic_shard_review_compile_and_retrieve(self) -> None:
        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")):
            self._export()
            self._decide()
            self._merge()
            schemas = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in (ROOT / "contracts").glob("*.schema.json")
            }
            registry = Registry().with_resources(
                (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
            )
            for name, value in (
                ("outline-review-selection.schema.json", json.loads(self.selection.read_text(encoding="utf-8"))),
                ("outline-review-shard.schema.json", json.loads((self.shard / "manifest.json").read_text(encoding="utf-8"))),
                ("structure-annotations.schema.json", json.loads(self.annotations.read_text(encoding="utf-8"))),
            ):
                validator_for(schemas[name])(schemas[name], registry=registry).validate(value)
            first = compile_structured_page_pack_section(
                self.base, self.outline, self.annotations, self.root / "first",
                shard_directory=self.shard, decisions_directory=self.decisions,
            )
            second = compile_structured_page_pack_section(
                self.base, self.outline, self.annotations, self.root / "second",
                shard_directory=self.shard, decisions_directory=self.decisions,
            )
        self.assertEqual(first["package_digest"], second["package_digest"])
        pack = validate_pack_directory(self.root / "first")
        self.assertEqual(2, len(pack.records))
        self.assertEqual({"human_reviewed", "agent_reviewed"}, {record["derivation"]["review_status"] for record in pack.records})
        self.assertEqual("partial_reviewed_structural_section_only", pack.manifest["coverage"]["parsed_source_coverage"])
        policy = self.root / "policy.json"
        policy.write_text(json.dumps({
            "policy_version": "0.1.0", "policy_id": "synthetic-shard-test",
            "principal_id": "reviewer", "allow_admin_install": True, "allow_serve": True,
            "allowed_pack_ids": [pack.manifest["pack_id"]],
            "allowed_content_classes": [pack.rights["content_class"]],
        }), encoding="utf-8")
        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")):
            service = StandardsForgeService(self.root / "memory.db", self.root / "objects")
            installed = service.install_pack(self.root / "first", policy)
            packet = service.get_clause(installed["package_digest"], pack.records[0]["clause_reference"], "reviewer", response_profile="compact_evidence_v1")
        self.assertFalse(packet["completeness"]["complete_for_requested_scope"])
        self.assertEqual(pack.records[0]["text"], packet["evidence"]["records"][0]["text"])
        self.assertTrue(packet["evidence"]["source_files"][0]["source_checks"]["source_digest_verified"])

    def test_missing_extra_stale_and_unreviewed_decisions_fail_closed(self) -> None:
        self._export()
        self._decide()
        first = next(self.decisions.iterdir())
        original = first.read_bytes()
        first.unlink()
        with self.assertRaises(StandardsForgeError):
            self._merge()
        first.write_bytes(original)
        extra = self.decisions / "extra.json"
        extra.write_text("{}", encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            self._merge()
        extra.unlink()
        decision = json.loads(original)
        decision["draft_sha256"] = "0" * 64
        first.write_text(json.dumps(decision), encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            self._merge()
        decision = json.loads(original)
        decision["node"]["derivation"]["review_status"] = "proposed"
        first.write_text(json.dumps(decision), encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            self._merge()
        self.assertFalse(self.annotations.exists())

    def test_rejects_forged_draft_and_annotation_and_out_of_shard_parent(self) -> None:
        self._export()
        self._decide()
        manifest = json.loads((self.shard / "manifest.json").read_text(encoding="utf-8"))
        draft_path = self.shard / manifest["candidates"][0]["draft_path"]
        original = draft_path.read_bytes()
        draft = json.loads(original)
        draft["proposed_node"]["heading"] = "forged"
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            self._merge()
        draft_path.write_bytes(original)
        decision_path = self.decisions / f"{hashlib.sha256(manifest['candidates'][0]['candidate_record_id'].encode()).hexdigest()}.json"
        original_decision = decision_path.read_bytes()
        decision = json.loads(original_decision)
        decision["node"]["parent_logical_id"] = "outside-shard"
        decision_path.write_text(json.dumps(decision), encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            self._merge()
        decision_path.write_bytes(original_decision)
        self._merge()
        annotations = json.loads(self.annotations.read_text(encoding="utf-8"))
        annotations["nodes"][0]["heading"] = "forged"
        self.annotations.write_text(json.dumps(annotations), encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            compile_structured_page_pack_section(
                self.base, self.outline, self.annotations, self.root / "rejected",
                shard_directory=self.shard, decisions_directory=self.decisions,
            )
        self.assertFalse((self.root / "rejected").exists())

    def test_rejects_oversized_review_inputs_before_parsing(self) -> None:
        self._export()
        self._decide()
        decision_path = next(self.decisions.iterdir())
        decision_path.write_bytes(b"{" + b"x" * (8 * 1024 * 1024))
        with self.assertRaisesRegex(StandardsForgeError, "size limit"):
            self._merge()
        self.assertFalse(self.annotations.exists())
        annotations = self.root / "oversized-annotations.json"
        annotations.write_bytes(b"{" + b"x" * (32 * 1024 * 1024))
        with self.assertRaisesRegex(StandardsForgeError, "JSON size limit"):
            compile_structured_page_pack_section(
                self.base, self.outline, annotations, self.root / "oversized-rejected",
                shard_directory=self.shard, decisions_directory=self.decisions,
            )

    def test_selection_and_source_span_limits_fail_closed(self) -> None:
        selection = json.loads(self.selection.read_text(encoding="utf-8"))
        selection["record_ids"].append(selection["record_ids"][0])
        self.selection.write_text(json.dumps(selection), encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            self._export()
        selection["record_ids"] = [f"candidate-{index}" for index in range(257)]
        self.selection.write_text(json.dumps(selection), encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            self._export()
        selection["record_ids"] = [candidate["record_id"] for candidate in self.candidates]
        self.selection.write_text(json.dumps(selection), encoding="utf-8")
        self._export()
        self._decide()
        decision_path = next(self.decisions.iterdir())
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        span = decision["node"]["source_spans"][0]
        decision["node"]["source_spans"] = [span, copy.deepcopy(span)]
        decision["node"]["exact_text"] = decision["node"]["exact_text"] + "\n" + decision["node"]["exact_text"]
        decision["node"]["content_sha256"] = hashlib.sha256(decision["node"]["exact_text"].encode()).hexdigest()
        decision_path.write_text(json.dumps(decision), encoding="utf-8")
        with self.assertRaises(StandardsForgeError):
            self._merge()
        self.assertFalse(self.annotations.exists())


if __name__ == "__main__":
    unittest.main()
