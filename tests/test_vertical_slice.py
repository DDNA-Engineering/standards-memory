from __future__ import annotations

import hashlib
import json
import shutil
import socket
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.cli import _parser  # noqa: E402
from standardsforge.pack import validate_pack_directory  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402


PACK_V1 = ROOT / "examples" / "packs" / "fictional-adapter-v1"
PACK_V2 = ROOT / "examples" / "packs" / "fictional-adapter-v2"
POLICY = ROOT / "examples" / "policies" / "local-synthetic.json"
DENY_POLICY = ROOT / "examples" / "policies" / "deny-install.json"


class VerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-test-")
        base = Path(self.temp.name)
        self.service = StandardsForgeService(base / "memory.db", base / "objects")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _install_v1(self) -> str:
        return self.service.install_pack(PACK_V1, POLICY)["package_digest"]

    @staticmethod
    def _rewrite_inventoried_json(pack_root: Path, relative: str, payload: dict) -> None:
        data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        (pack_root / relative).write_bytes(data)
        inventory_path = pack_root / "inventory.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        entry = next(item for item in inventory["files"] if item["path"] == relative)
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        entry["bytes"] = len(data)
        inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

    def test_install_resolve_and_retrieve_dependency_complete_packet(self) -> None:
        digest = self._install_v1()
        resolved = self.service.resolve_document(
            " example - spec - 100 ", "local-user", "example:spec-100:2025-a"
        )
        self.assertEqual(digest, resolved["package_digest"])
        self.assertEqual("example:spec-100", resolved["document_family_id"])

        packet = self.service.get_clause(digest, "4.2.1", "local-user")
        self.assertEqual(["clause", "note"], [item["kind"] for item in packet["evidence"]])
        self.assertIn("80 N", packet["evidence"][0]["text"])
        self.assertIn("23 °C", packet["evidence"][1]["text"])
        self.assertEqual("governed_by", packet["required_relationships"][0]["relationship"])
        self.assertTrue(packet["completeness"]["complete_for_requested_scope"])
        self.assertTrue(all(item["source_checks"]["source_digest_verified"] for item in packet["evidence"]))
        encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.assertEqual(len(encoded), packet["budget"]["used"])

    def test_compact_profile_preserves_exact_evidence_and_deduplicates_dictionaries(self) -> None:
        digest = self._install_v1()
        detailed = self.service.get_clause(digest, "4.2.1", "local-user")
        compact = self.service.get_clause(
            digest, "4.2.1", "local-user", response_profile="compact_evidence_v1"
        )
        self.assertEqual("compact_evidence_v1", compact["response_profile"])
        self.assertEqual(detailed["completeness"], compact["completeness"])
        self.assertEqual(detailed, self.service.get_clause(digest, "4.2.1", "local-user"))
        self.assertEqual(
            [item["record_id"] for item in detailed["evidence"]],
            [item["record_id"] for item in compact["evidence"]["records"]],
        )
        self.assertEqual(
            [item["text"] for item in detailed["evidence"]],
            [item["text"] for item in compact["evidence"]["records"]],
        )
        self.assertEqual(["e1", "e2"], [item["ref"] for item in compact["evidence"]["records"]])
        self.assertEqual(1, len(compact["evidence"]["source_files"]))
        self.assertEqual(2, len(compact["evidence"]["derivations"]))
        source = compact["evidence"]["source_files"][0]
        self.assertEqual("sources/example-spec-100a.txt", source["path"])
        self.assertTrue(source["source_checks"]["source_digest_verified"])
        for detailed_record, compact_record in zip(detailed["evidence"], compact["evidence"]["records"]):
            self.assertEqual(detailed_record["record_id"], compact_record["record_id"])
            self.assertEqual(detailed_record["text"], compact_record["text"])
            self.assertEqual(detailed_record["citation"]["page"], compact_record["page"])
            self.assertEqual(detailed_record["citation"]["locator"], compact_record["locator"])
            self.assertEqual(detailed_record["citation"]["quote_sha256"], compact_record["quote_sha256"])
            self.assertEqual(source["ref"], compact_record["source_ref"])
            self.assertTrue(compact_record["source_checks"]["quote_digest_verified"])
            self.assertTrue(compact_record["source_checks"]["exact_quote_present"])
            derivation = next(
                item for item in compact["evidence"]["derivations"] if item["ref"] == compact_record["derivation_ref"]
            )
            self.assertEqual(detailed_record["derivation"], {key: value for key, value in derivation.items() if key != "ref"})
        compact_ids = {item["record_id"]: item["ref"] for item in compact["evidence"]["records"]}
        self.assertEqual(
            [{"source_ref": compact_ids["clause-4.2.1"], "relationship": "governed_by", "target_ref": compact_ids["note-4.2.1-1"]}],
            compact["required_relationships"],
        )
        self.assertEqual(
            {"status": "unavailable", "reason": "no_local_tokenizer_configured"},
            compact["token_measurement"],
        )
        encoded = json.dumps(compact, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.assertEqual(len(encoded), compact["budget"]["used"])
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.get_clause(digest, "4.2.1", "local-user", max_bytes=100, response_profile="compact_evidence_v1")
        self.assertEqual("budget_too_small", caught.exception.code)
        self.assertGreater(caught.exception.details["required_bytes"], 100)
        self.assertEqual(
            compact,
            self.service.get_clause(digest, "4.2.1", "local-user", response_profile="compact_evidence_v1"),
        )

        detailed_context = self.service.build_context(digest, ["4.2.1", "4.2.2", "4.2.1"], "local-user")
        compact_context = self.service.build_context(
            digest,
            ["4.2.1", "4.2.2", "4.2.1"],
            "local-user",
            response_profile="compact_evidence_v1",
        )
        self.assertEqual(detailed_context["completeness"], compact_context["completeness"])
        self.assertEqual(
            [item["record_id"] for item in detailed_context["evidence"]],
            [item["record_id"] for item in compact_context["evidence"]["records"]],
        )
        context_record_ids = [item["record_id"] for item in compact_context["evidence"]["records"]]
        self.assertEqual(len(context_record_ids), len(set(context_record_ids)))
        self.assertEqual(1, len(compact_context["evidence"]["source_files"]))
        self.assertEqual(2, len(compact_context["evidence"]["derivations"]))

    def test_concise_profile_preserves_citations_completeness_and_reduces_bytes(self) -> None:
        digest = self._install_v1()
        detailed = self.service.get_clause(digest, "4.2.1", "local-user")
        concise = self.service.get_clause(
            digest, "4.2.1", "local-user", response_profile="concise_evidence_v1"
        )

        self.assertEqual("concise_evidence_v1", concise["response_profile"])
        self.assertEqual(detailed["package"], concise["package"])
        self.assertEqual(
            {"status": "authorized", "package_digest": digest},
            concise["authorization"],
        )
        self.assertEqual(
            detailed["completeness"]["declared_pack_coverage"],
            concise["coverage"]["declared"],
        )
        self.assertEqual(
            detailed["completeness"]["complete_for_requested_scope"],
            concise["coverage"]["complete_for_requested_scope"],
        )
        self.assertEqual(
            detailed["completeness"]["scope_interpretation"],
            concise["coverage"]["scope_interpretation"],
        )
        self.assertEqual(detailed["limitations"], concise["limitations"])
        self.assertEqual(
            [record["record_id"] for record in detailed["evidence"]],
            [record["record_id"] for record in concise["evidence"]],
        )
        for detailed_record, concise_record in zip(detailed["evidence"], concise["evidence"]):
            self.assertEqual(detailed_record["text"], concise_record["text"])
            self.assertEqual(detailed_record["kind"], concise_record["kind"])
            self.assertEqual(detailed_record["clause_reference"], concise_record["clause_reference"])
            self.assertEqual(detailed_record["heading"], concise_record["heading"])
            self.assertTrue(concise_record["citation"]["verified"])
            source = next(
                item for item in concise["provenance"]["sources"]
                if item["ref"] == concise_record["citation"]["source_ref"]
            )
            self.assertEqual(detailed_record["citation"]["source_path"], source["path"])
            self.assertEqual(detailed_record["citation"]["source_sha256"], source["sha256"])
            self.assertTrue(source["verified"])
            if "text_path" in detailed_record["citation"]:
                self.assertEqual(detailed_record["citation"]["text_path"], source["text_path"])
                self.assertEqual(detailed_record["citation"]["text_sha256"], source["text_sha256"])
            self.assertEqual(detailed_record["citation"]["page"], concise_record["citation"]["page"])
            self.assertEqual(detailed_record["citation"]["locator"], concise_record["citation"]["locator"])
            self.assertEqual(detailed_record["citation"]["quote_sha256"], concise_record["citation"]["quote_sha256"])

        refs_by_id = {record["record_id"]: record["ref"] for record in concise["evidence"]}
        self.assertEqual(
            [
                {
                    "source_ref": refs_by_id[edge["source_record_id"]],
                    "relationship": edge["relationship"],
                    "required": True,
                    "target_status": "resolved",
                    "target_ref": refs_by_id[edge["target_record_id"]],
                }
                for edge in detailed["required_relationships"]
            ],
            concise["relationships"],
        )
        detailed_size = len(json.dumps(detailed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        compact = self.service.get_clause(digest, "4.2.1", "local-user", response_profile="compact_evidence_v1")
        compact_size = len(json.dumps(compact, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        concise_size = len(json.dumps(concise, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        self.assertLess(concise_size, detailed_size)
        self.assertLess(concise_size, compact_size)
        self.assertEqual(concise, self.service.get_clause(digest, "4.2.1", "local-user", response_profile="concise_evidence_v1"))

        detailed_context = self.service.build_context(digest, ["4.2.1", "4.2.2"], "local-user")
        concise_context = self.service.build_context(
            digest, ["4.2.1", "4.2.2"], "local-user", response_profile="concise_evidence_v1"
        )
        self.assertEqual(detailed_context["requested_clause_references"], concise_context["requested_clause_references"])
        self.assertEqual(
            [record["record_id"] for record in detailed_context["evidence"]],
            [record["record_id"] for record in concise_context["evidence"]],
        )
        self.assertEqual(
            [record["text"] for record in detailed_context["evidence"]],
            [record["text"] for record in concise_context["evidence"]],
        )
        self.assertEqual(
            detailed_context["completeness"]["declared_pack_coverage"],
            concise_context["coverage"]["declared"],
        )

    def test_compact_profile_is_opt_in_validated_and_rechecks_tampered_source(self) -> None:
        digest = self._install_v1()
        detailed = self.service.get_clause(digest, "4.2.1", "local-user")
        self.assertNotIn("response_profile", detailed)
        self.assertEqual(
            detailed,
            self.service.get_clause(digest, "4.2.1", "local-user", response_profile="detailed_json_v1"),
        )
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.get_clause(digest, "4.2.1", "local-user", response_profile="unknown_profile")
        self.assertEqual("invalid_response_profile", caught.exception.code)

        object_path = Path(self.service.store.authorized_package("local-user", digest)["object_path"])
        source_path = object_path / "sources" / "example-spec-100a.txt"
        source_path.write_bytes(source_path.read_bytes() + b" tampered")
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.get_clause(digest, "4.2.1", "local-user", response_profile="compact_evidence_v1")
        self.assertEqual("source_integrity_failure", caught.exception.code)

    def test_cli_accepts_versioned_profiles_only_on_exact_retrieval_operations(self) -> None:
        args = _parser().parse_args(
            [
                "get-clause",
                "a" * 64,
                "4.2.1",
                "--principal",
                "local-user",
                "--response-profile",
                "concise_evidence_v1",
            ]
        )
        self.assertEqual("concise_evidence_v1", args.response_profile)
        context = _parser().parse_args(
            [
                "build-context",
                "a" * 64,
                "4.2.1",
                "4.2.2",
                "--principal",
                "local-user",
                "--response-profile",
                "concise_evidence_v1",
            ]
        )
        self.assertEqual("concise_evidence_v1", context.response_profile)

    def test_concise_profile_keeps_unresolved_and_ambiguous_relationship_meaning(self) -> None:
        digest = "a" * 64
        source_sha = "b" * 64
        text_sha = "c" * 64
        quote_sha = "d" * 64
        span = {
            "path": "sources/spec.pdf",
            "sha256": source_sha,
            "text_path": "sources/pages/physical-0001.txt",
            "text_sha256": text_sha,
            "physical_page": 1,
            "start_byte": 0,
            "end_byte": 10,
            "quote_sha256": quote_sha,
        }
        packet = {
            "schema_version": "0.1.0",
            "operation": "get_clause",
            "retrieval_mode": "exact_pinned_clause",
            "package": {
                "package_digest": digest,
                "pack_id": "fixture",
                "document_family_id": "test:fixture",
                "edition_id": "test:fixture:2026",
                "identifier": "TEST-1",
                "revision": "A",
                "title": "Fixture",
            },
            "evidence": [
                {
                    "record_id": "record-1",
                    "kind": "clause",
                    "clause_reference": "1",
                    "heading": "Requirement",
                    "text": "Exact text",
                    "citation": {
                        "source_path": span["path"],
                        "source_sha256": source_sha,
                        "text_path": span["text_path"],
                        "text_sha256": text_sha,
                        "page": 1,
                        "locator": "physical PDF page 1; UTF-8 bytes 0:9",
                        "quote_sha256": quote_sha,
                        "text_start_byte": 0,
                        "text_end_byte": 10,
                    },
                    "source_checks": {
                        "source_digest_verified": True,
                        "extracted_text_digest_verified": True,
                        "quote_digest_verified": True,
                        "exact_quote_present": True,
                    },
                    "derivation": {"statement_role": "unclassified", "method": "review", "review_status": "agent_reviewed"},
                    "structure": {
                        "logical_id": "test:fixture:1",
                        "content_sha256": quote_sha,
                        "parent_logical_id": None,
                        "ordinal": 1,
                        "source_spans": [span],
                        "relationships": [
                            {
                                "relationship": "governed_by",
                                "target_status": "resolved",
                                "target_logical_id": "test:fixture:target",
                                "target_locator": None,
                                "candidate_logical_ids": [],
                                "required": True,
                                "method": "review",
                                "review_status": "agent_reviewed",
                                "evidence_spans": [span],
                            },
                            {
                                "relationship": "references",
                                "target_status": "out_of_scope",
                                "target_logical_id": None,
                                "target_locator": "Annex Z",
                                "candidate_logical_ids": [],
                                "required": False,
                                "method": "review",
                                "review_status": "agent_reviewed",
                                "evidence_spans": [span],
                            },
                            {
                                "relationship": "selects_method",
                                "target_status": "ambiguous",
                                "target_logical_id": None,
                                "target_locator": None,
                                "candidate_logical_ids": ["method-a", "method-b"],
                                "required": False,
                                "method": "review",
                                "review_status": "agent_reviewed",
                                "evidence_spans": [span],
                            },
                            {
                                "relationship": "selects_method",
                                "target_status": "ambiguous",
                                "target_logical_id": None,
                                "target_locator": None,
                                "candidate_logical_ids": ["method-c", "method-d"],
                                "required": False,
                                "method": "review",
                                "review_status": "agent_reviewed",
                                "evidence_spans": [span],
                            },
                            {
                                "relationship": "selects_method",
                                "target_status": "ambiguous",
                                "target_logical_id": None,
                                "target_locator": None,
                                "candidate_logical_ids": ["method-c", "method-d"],
                                "required": False,
                                "method": "cross_reference_review",
                                "review_status": "agent_reviewed",
                                "evidence_spans": [span],
                            },
                        ],
                    },
                }
            ],
            "required_relationships": [
                {"source_record_id": "record-1", "relationship": "governed_by", "target_record_id": "record-2"}
            ],
            "completeness": {
                "complete_for_requested_scope": False,
                "scope_interpretation": "selected record only",
                "declared_pack_coverage": {
                    "corpus_scope": "one record",
                    "edition_composition": "exact edition",
                    "parsed_source_coverage": "partial",
                    "dependency_closure": "partial",
                    "enumeration_traversal": "not evaluated",
                    "output_budget_coverage": "computed at query time",
                },
                "dimensions": {
                    "source_interpretation": {"complete": False, "status": "incomplete"},
                    "required_dependencies": {
                        "identification_complete": False,
                        "identification_status": "incomplete",
                        "retrieval_complete": True,
                        "retrieval_status": "complete_for_returned_required_graph",
                    },
                    "database_traversal": {"complete": None, "status": "not_requested"},
                    "response_fit": {"complete": True, "status": "complete", "unit": "bytes"},
                },
            },
            "limitations": [],
        }
        target_record = json.loads(json.dumps(packet["evidence"][0]))
        target_record["record_id"] = "record-2"
        target_record["clause_reference"] = "2"
        target_record["heading"] = "Governing note"
        target_record["derivation"] = {
            "statement_role": "governing_note",
            "method": "review",
            "review_status": "agent_reviewed",
        }
        target_record["structure"] = {
            "logical_id": "test:fixture:target",
            "content_sha256": quote_sha,
            "parent_logical_id": None,
            "ordinal": 2,
            "source_spans": [span],
            "relationships": [],
        }
        packet["evidence"].append(target_record)
        concise = StandardsForgeService._render_response_profile(packet, "concise_evidence_v1")
        self.assertEqual(5, len(concise["relationships"]))
        self.assertEqual(1, len(concise["provenance"]["spans"]))
        self.assertEqual(0, concise["evidence"][0]["citation"]["text_start_byte"])
        self.assertEqual(10, concise["evidence"][0]["citation"]["text_end_byte"])
        resolved = next(edge for edge in concise["relationships"] if edge["relationship"] == "governed_by")
        self.assertTrue(resolved["required"])
        self.assertEqual("resolved", resolved["target_status"])
        self.assertEqual("e2", resolved["target_ref"])
        self.assertEqual(["p1"], resolved["evidence_span_refs"])
        out_of_scope = next(edge for edge in concise["relationships"] if edge["relationship"] == "references")
        ambiguous = next(edge for edge in concise["relationships"] if edge["relationship"] == "selects_method")
        self.assertEqual("out_of_scope", out_of_scope["target_status"])
        self.assertEqual("Annex Z", out_of_scope["target_locator"])
        self.assertEqual("ambiguous", ambiguous["target_status"])
        self.assertEqual(["method-a", "method-b"], ambiguous["candidate_logical_ids"])
        ambiguous_edges = [
            edge for edge in concise["relationships"] if edge["relationship"] == "selects_method"
        ]
        self.assertEqual(3, len(ambiguous_edges))
        self.assertEqual(
            [
                ["method-a", "method-b"],
                ["method-c", "method-d"],
                ["method-c", "method-d"],
            ],
            [edge["candidate_logical_ids"] for edge in ambiguous_edges],
        )
        derivations_by_ref = {
            item["ref"]: (item["method"], item["review_status"])
            for item in concise["provenance"]["derivations"]
        }
        self.assertEqual(
            [
                ("review", "agent_reviewed"),
                ("review", "agent_reviewed"),
                ("cross_reference_review", "agent_reviewed"),
            ],
            [derivations_by_ref[edge["derivation_ref"]] for edge in ambiguous_edges],
        )
        self.assertTrue(all(edge["evidence_span_refs"] == ["p1"] for edge in concise["relationships"]))
        self.assertEqual(
            concise,
            StandardsForgeService._render_response_profile(packet, "concise_evidence_v1"),
        )

    def test_full_workflow_operates_when_network_sockets_are_denied(self) -> None:
        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")):
            digest = self._install_v1()
            second_digest = self.service.install_pack(PACK_V2, POLICY)["package_digest"]
            resolved = self.service.resolve_document(
                "EXAMPLE-SPEC-100", "local-user", "example:spec-100:2025-a"
            )
            packet = self.service.get_clause(digest, "4.2.1", "local-user")
            context = self.service.build_context(digest, ["4.2.1", "4.2.2"], "local-user")
            enumeration = self.service.enumerate_obligations(digest, "local-user", scope_prefix="4.2")
            comparison = self.service.diff_editions(digest, second_digest, "local-user")
            search = self.service.search("axial load", "local-user")
        self.assertEqual(digest, resolved["package_digest"])
        self.assertEqual("exact_pinned_clause", packet["retrieval_mode"])
        self.assertEqual(3, len(context["evidence"]))
        self.assertEqual(2, enumeration["page"]["declared_scope_total"])
        self.assertEqual("modified", comparison["changes"][0]["status"])
        self.assertTrue(search["results"])

    def test_second_edition_does_not_change_first_pinned_evidence(self) -> None:
        first_digest = self._install_v1()
        before = self.service.get_clause(first_digest, "4.2.1", "local-user")
        second_digest = self.service.install_pack(PACK_V2, POLICY)["package_digest"]
        self.assertNotEqual(first_digest, second_digest)

        with self.assertRaises(StandardsForgeError) as caught:
            self.service.resolve_document("EXAMPLE-SPEC-100", "local-user")
        self.assertEqual("ambiguous_document", caught.exception.code)

        after = self.service.get_clause(first_digest, "4.2.1", "local-user")
        second = self.service.get_clause(second_digest, "4.2.1", "local-user")
        self.assertEqual(before["evidence"], after["evidence"])
        self.assertIn("80 N", after["evidence"][0]["text"])
        self.assertIn("100 N", second["evidence"][0]["text"])

    def test_tampered_source_is_rejected_before_install(self) -> None:
        candidate = Path(self.temp.name) / "tampered"
        shutil.copytree(PACK_V1, candidate)
        with (candidate / "sources" / "example-spec-100a.txt").open("a", encoding="utf-8") as stream:
            stream.write("tamper")
        with self.assertRaises(StandardsForgeError) as caught:
            validate_pack_directory(candidate)
        self.assertIn(caught.exception.code, {"pack_size_mismatch", "pack_hash_mismatch"})

    def test_untracked_executable_content_is_rejected(self) -> None:
        candidate = Path(self.temp.name) / "untracked"
        shutil.copytree(PACK_V1, candidate)
        (candidate / "payload.py").write_text("raise SystemExit", encoding="utf-8")
        with self.assertRaises(StandardsForgeError) as caught:
            validate_pack_directory(candidate)
        self.assertEqual("untracked_pack_content", caught.exception.code)

    def test_portable_zip_pack_validates_to_same_content_digest(self) -> None:
        directory_digest = validate_pack_directory(PACK_V1).package_digest
        archive_path = Path(self.temp.name) / "fictional-adapter-v1.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(PACK_V1.rglob("*")):
                archive.write(path, path.relative_to(PACK_V1).as_posix())
        verified = self.service.verify_pack(archive_path)
        self.assertEqual(directory_digest, verified["package_digest"])

    def test_pack_rights_claim_does_not_override_operator_denial(self) -> None:
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.install_pack(PACK_V1, DENY_POLICY)
        self.assertEqual("policy_denied", caught.exception.code)

    def test_atomic_evidence_is_not_truncated_to_fit_budget(self) -> None:
        digest = self._install_v1()
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.get_clause(digest, "4.2.1", "local-user", max_bytes=100)
        self.assertEqual("budget_too_small", caught.exception.code)
        self.assertGreater(caught.exception.details["required_bytes"], 100)

    def test_revocation_is_checked_on_next_read(self) -> None:
        digest = self._install_v1()
        self.assertTrue(self.service.revoke(digest, "local-user")["revoked"])
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.get_clause(digest, "4.2.1", "local-user")
        self.assertEqual("not_found", caught.exception.code)

    def test_lexical_search_returns_only_authorized_installed_records(self) -> None:
        digest = self._install_v1()
        results = self.service.search("axial load", "local-user")["results"]
        self.assertEqual(1, len(results))
        self.assertEqual(digest, results[0]["package_digest"])
        self.assertEqual("4.2.1", results[0]["clause_reference"])
        self.assertEqual([], self.service.search("axial load", "unknown-principal")["results"])

    def test_search_can_be_pinned_and_scoped_without_fallback(self) -> None:
        first_digest = self._install_v1()
        second_digest = self.service.install_pack(PACK_V2, POLICY)["package_digest"]

        scoped = self.service.search(
            "adapter",
            "local-user",
            package_digest=first_digest,
            scope_prefix="4.2.2",
        )
        self.assertEqual(
            {"package_digest": first_digest, "scope_prefix": "4.2.2"},
            scoped["filters"],
        )
        self.assertEqual(["4.2.2"], [item["clause_reference"] for item in scoped["results"]])
        self.assertTrue(all(item["package_digest"] == first_digest for item in scoped["results"]))

        other_edition = self.service.search("adapter", "local-user", package_digest=second_digest)
        self.assertTrue(other_edition["results"])
        self.assertTrue(all(item["package_digest"] == second_digest for item in other_edition["results"]))

        with self.assertRaises(StandardsForgeError) as caught:
            self.service.search("adapter", "unknown-principal", package_digest=first_digest)
        self.assertEqual("not_found", caught.exception.code)

    def test_discovered_note_is_directly_retrievable_and_preserves_declared_coverage(self) -> None:
        digest = self._install_v1()
        results = self.service.search("conditioning", "local-user")["results"]
        note = next(item for item in results if item["kind"] == "note")
        self.assertEqual(
            {
                "operation": "get_clause",
                "package_digest": digest,
                "record_id": note["record_id"],
                "clause_reference": note["clause_reference"],
            },
            note["evidence_selector"],
        )
        selector_arguments = {
            key: value
            for key, value in note["evidence_selector"].items()
            if key != "operation"
        }
        selector_packet = self.service.get_clause(**selector_arguments, principal_id="local-user")
        packet = self.service.get_clause(digest, note["clause_reference"], "local-user")
        self.assertEqual(packet, selector_packet)
        record_id_only_packet = self.service.get_clause(
            package_digest=digest,
            principal_id="local-user",
            record_id=note["record_id"],
        )
        self.assertEqual(packet, record_id_only_packet)
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.get_clause(
                digest,
                note["clause_reference"],
                "local-user",
                record_id="different-record",
            )
        self.assertEqual("record_selector_mismatch", caught.exception.code)
        self.assertEqual("note", packet["evidence"][0]["kind"])
        declared = json.loads((PACK_V1 / "manifest.json").read_text(encoding="utf-8"))["coverage"]
        self.assertEqual(declared, packet["completeness"]["declared_pack_coverage"])
        self.assertEqual(declared["parsed_source_coverage"], packet["completeness"]["parsed_source_coverage"])
        self.assertEqual(
            "selected_record_and_required_dependencies_only_not_corpus_completeness",
            packet["completeness"]["scope_interpretation"],
        )

    def test_incomplete_interpretation_remains_incomplete_through_search_retrieval_and_enumeration(self) -> None:
        candidate = Path(self.temp.name) / "incomplete-coverage"
        shutil.copytree(PACK_V1, candidate)
        manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
        manifest["coverage"].update(
            {
                "edition_composition": "incomplete_annexes",
                "parsed_source_coverage": "partial_missing_tables",
                "dependency_closure": "not_derived",
                "enumeration_traversal": "not_evaluated",
            }
        )
        self._rewrite_inventoried_json(candidate, "manifest.json", manifest)
        records = json.loads((candidate / "records.json").read_text(encoding="utf-8"))
        for record in records["records"]:
            record["derivation"]["statement_role"] = "informative"
        self._rewrite_inventoried_json(candidate, "records.json", records)

        digest = self.service.install_pack(candidate, POLICY)["package_digest"]
        search = self.service.search("axial load", "local-user")
        search_dimensions = search["coverage_by_package"][digest]["dimensions"]
        self.assertFalse(search_dimensions["source_interpretation"]["complete"])
        self.assertFalse(search_dimensions["required_dependencies"]["identification_complete"])

        packet = self.service.get_clause(digest, "4.2.1", "local-user")
        dimensions = packet["completeness"]["dimensions"]
        self.assertFalse(dimensions["source_interpretation"]["complete"])
        self.assertFalse(dimensions["required_dependencies"]["identification_complete"])
        self.assertTrue(dimensions["required_dependencies"]["retrieval_complete"])
        self.assertFalse(packet["completeness"]["complete_for_requested_scope"])

        enumeration = self.service.enumerate_obligations(digest, "local-user")
        self.assertEqual(0, enumeration["page"]["declared_scope_total"])
        self.assertTrue(enumeration["completeness"]["dimensions"]["database_traversal"]["complete"])
        self.assertFalse(enumeration["completeness"]["complete_for_requested_scope"])

    def test_duplicate_record_references_are_rejected(self) -> None:
        candidate = Path(self.temp.name) / "duplicate-record-reference"
        shutil.copytree(PACK_V1, candidate)
        records = json.loads((candidate / "records.json").read_text(encoding="utf-8"))
        records["records"][1]["clause_reference"] = records["records"][0]["clause_reference"]
        self._rewrite_inventoried_json(candidate, "records.json", records)
        with self.assertRaises(StandardsForgeError) as caught:
            validate_pack_directory(candidate)
        self.assertEqual("invalid_record", caught.exception.code)

    def test_build_context_deduplicates_dependencies_and_refuses_partial_budget(self) -> None:
        digest = self._install_v1()
        packet = self.service.build_context(digest, ["4.2.1", "4.2.2", "4.2.1"], "local-user")
        self.assertEqual(["4.2.1", "4.2.2"], packet["requested_clause_references"])
        self.assertEqual(
            ["clause-4.2.1", "note-4.2.1-1", "clause-4.2.2"],
            [item["record_id"] for item in packet["evidence"]],
        )
        self.assertEqual("obligation", packet["evidence"][0]["derivation"]["statement_role"])
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.build_context(digest, ["4.2.1", "4.2.2"], "local-user", max_bytes=200)
        self.assertEqual("budget_too_small", caught.exception.code)

    def test_obligation_enumeration_uses_policy_bound_stable_cursors(self) -> None:
        digest = self._install_v1()
        first = self.service.enumerate_obligations(digest, "local-user", scope_prefix="4.2", limit=1)
        self.assertEqual("4.2.1", first["obligations"][0]["clause_reference"])
        self.assertTrue(first["page"]["has_more"])
        self.assertFalse(first["completeness"]["complete_for_requested_scope"])
        cursor = first["page"]["next_cursor"]

        second = self.service.enumerate_obligations(
            digest, "local-user", scope_prefix="4.2", limit=1, cursor=cursor
        )
        self.assertEqual("4.2.2", second["obligations"][0]["clause_reference"])
        self.assertFalse(second["page"]["has_more"])
        self.assertTrue(second["completeness"]["complete_for_requested_scope"])

        tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.enumerate_obligations(
                digest, "local-user", scope_prefix="4.2", limit=1, cursor=tampered
            )
        self.assertEqual("invalid_cursor", caught.exception.code)

        replacement_policy = Path(self.temp.name) / "replacement-policy.json"
        policy_data = json.loads(POLICY.read_text(encoding="utf-8"))
        policy_data["policy_id"] = "replacement-policy"
        replacement_policy.write_text(json.dumps(policy_data), encoding="utf-8")
        self.service.install_pack(PACK_V1, replacement_policy)
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.enumerate_obligations(
                digest, "local-user", scope_prefix="4.2", limit=1, cursor=cursor
            )
        self.assertEqual("cursor_policy_changed", caught.exception.code)

    def test_diff_editions_reports_direct_and_dependency_context_changes(self) -> None:
        first_digest = self._install_v1()
        second_digest = self.service.install_pack(PACK_V2, POLICY)["package_digest"]
        packet = self.service.diff_editions(first_digest, second_digest, "local-user")
        statuses = {change["record_id"]: change["status"] for change in packet["changes"]}
        self.assertEqual("modified", statuses["clause-4.2.1"])
        self.assertEqual("modified", statuses["note-4.2.1-1"])
        self.assertEqual("unchanged", statuses["clause-4.2.2"])
        self.assertIn("clause-4.2.1", packet["dependency_context_impacts"])
        impact = next(
            item
            for item in packet["dependency_impact_paths"]
            if item["record_id"] == "clause-4.2.1"
        )
        self.assertEqual(
            ["note-4.2.1-1"],
            [edge["target_record_id"] for edge in impact["path"]],
        )
        self.assertEqual("target_record_changed", impact["cause"]["type"])
        self.assertEqual([], packet["dependency_edges_added"])
        self.assertEqual([], packet["dependency_edges_removed"])

    def test_diff_editions_reports_transitive_dependency_impact_path(self) -> None:
        candidates = []
        for name, source in (("before", PACK_V1), ("after", PACK_V2)):
            candidate = Path(self.temp.name) / f"transitive-{name}"
            shutil.copytree(source, candidate)
            records = json.loads((candidate / "records.json").read_text(encoding="utf-8"))
            sealing = next(
                record for record in records["records"] if record["record_id"] == "clause-4.2.2"
            )
            sealing["dependencies"] = [
                {
                    "relationship": "governed_by",
                    "target_record_id": "note-4.2.1-1",
                    "required": True,
                }
            ]
            downstream = json.loads(json.dumps(sealing))
            downstream.update(
                {
                    "record_id": "clause-4.2.3",
                    "clause_reference": "4.2.3",
                    "heading": "Downstream system requirement",
                    "dependencies": [
                        {
                            "relationship": "governed_by",
                            "target_record_id": "clause-4.2.2",
                            "required": True,
                        }
                    ],
                }
            )
            records["records"].append(downstream)
            self._rewrite_inventoried_json(candidate, "records.json", records)
            candidates.append(candidate)

        before_digest = self.service.install_pack(candidates[0], POLICY)["package_digest"]
        after_digest = self.service.install_pack(candidates[1], POLICY)["package_digest"]
        packet = self.service.diff_editions(before_digest, after_digest, "local-user")
        impacts = [
            item
            for item in packet["dependency_impact_paths"]
            if item["record_id"] == "clause-4.2.3"
        ]
        self.assertEqual({"before", "after"}, {item["side"] for item in impacts})
        self.assertEqual(2, len(impacts))
        for impact in impacts:
            self.assertEqual(
                [
                    ("clause-4.2.3", "clause-4.2.2"),
                    ("clause-4.2.2", "note-4.2.1-1"),
                ],
                [
                    (edge["source_record_id"], edge["target_record_id"])
                    for edge in impact["path"]
                ],
            )
            self.assertEqual(
                {
                    "type": "target_record_changed",
                    "record_id": "note-4.2.1-1",
                    "status": "modified",
                },
                impact["cause"],
            )

    def test_diff_editions_reports_source_only_move_without_content_change(self) -> None:
        candidate = Path(self.temp.name) / "moved-v1"
        shutil.copytree(PACK_V1, candidate)
        records = json.loads((candidate / "records.json").read_text(encoding="utf-8"))
        moved = next(
            record for record in records["records"] if record["record_id"] == "clause-4.2.2"
        )
        moved["source"]["page"] = 2
        moved["source"]["locator"] = "page 2 / 4.2.2"
        self._rewrite_inventoried_json(candidate, "records.json", records)

        before_digest = self._install_v1()
        after_digest = self.service.install_pack(candidate, POLICY)["package_digest"]
        packet = self.service.diff_editions(before_digest, after_digest, "local-user")
        change = next(
            item for item in packet["changes"] if item["record_id"] == "clause-4.2.2"
        )
        self.assertEqual("moved", change["status"])
        self.assertTrue(change["source_location_changed"])
        self.assertEqual(
            {"added": 0, "removed": 0, "modified": 0, "moved": 1, "unchanged": 2},
            packet["change_counts"],
        )

        moved["heading"] = "Relocated and substantively revised interface sealing"
        moved["derivation"]["review_status"] = "synthetic_fixture_revised"
        self._rewrite_inventoried_json(candidate, "records.json", records)
        revised_digest = self.service.install_pack(candidate, POLICY)["package_digest"]
        revised_packet = self.service.diff_editions(
            before_digest, revised_digest, "local-user"
        )
        revised_change = next(
            item
            for item in revised_packet["changes"]
            if item["record_id"] == "clause-4.2.2"
        )
        self.assertEqual("modified", revised_change["status"])
        self.assertTrue(revised_change["source_location_changed"])

    def test_diff_editions_reports_added_required_edge_on_after_graph(self) -> None:
        candidate = Path(self.temp.name) / "added-edge-v1"
        shutil.copytree(PACK_V1, candidate)
        records = json.loads((candidate / "records.json").read_text(encoding="utf-8"))
        sealing = next(
            record for record in records["records"] if record["record_id"] == "clause-4.2.2"
        )
        sealing["dependencies"] = [
            {
                "relationship": "governed_by",
                "target_record_id": "note-4.2.1-1",
                "required": True,
            },
            {
                "relationship": "references",
                "target_record_id": "note-4.2.1-1",
                "required": True,
            }
        ]
        self._rewrite_inventoried_json(candidate, "records.json", records)

        before_digest = self._install_v1()
        after_digest = self.service.install_pack(candidate, POLICY)["package_digest"]
        packet = self.service.diff_editions(before_digest, after_digest, "local-user")
        impacts = [
            item
            for item in packet["dependency_impact_paths"]
            if item["record_id"] == "clause-4.2.2"
        ]
        self.assertEqual(2, len(impacts))
        self.assertEqual({"after"}, {impact["side"] for impact in impacts})
        self.assertEqual(
            {"governed_by", "references"},
            {impact["path"][-1]["relationship"] for impact in impacts},
        )
        self.assertTrue(
            all(
                impact["cause"]
                == {"type": "dependency_edge_added", "record_id": "note-4.2.1-1"}
                for impact in impacts
            )
        )
        self.assertEqual(
            [
                ["clause-4.2.2", "governed_by", "note-4.2.1-1", True],
                ["clause-4.2.2", "references", "note-4.2.1-1", True],
            ],
            packet["dependency_edges_added"],
        )

    def test_diff_editions_never_traverses_a_mixed_edition_graph(self) -> None:
        before = Path(self.temp.name) / "split-graph-before"
        after = Path(self.temp.name) / "split-graph-after"
        shutil.copytree(PACK_V1, before)
        shutil.copytree(PACK_V2, after)

        before_records = json.loads((before / "records.json").read_text(encoding="utf-8"))
        before_by_id = {record["record_id"]: record for record in before_records["records"]}
        before_by_id["clause-4.2.2"]["dependencies"] = [
            {
                "relationship": "governed_by",
                "target_record_id": "clause-4.2.1",
                "required": True,
            }
        ]
        before_by_id["clause-4.2.1"]["dependencies"] = []
        self._rewrite_inventoried_json(before, "records.json", before_records)

        before_digest = self.service.install_pack(before, POLICY)["package_digest"]
        after_digest = self.service.install_pack(after, POLICY)["package_digest"]
        packet = self.service.diff_editions(before_digest, after_digest, "local-user")

        fabricated = [
            item
            for item in packet["dependency_impact_paths"]
            if item["record_id"] == "clause-4.2.2"
            and item["cause"]["record_id"] == "note-4.2.1-1"
        ]
        self.assertEqual([], fabricated)
        direct = [
            item
            for item in packet["dependency_impact_paths"]
            if item["record_id"] == "clause-4.2.2"
        ]
        self.assertEqual(1, len(direct))
        self.assertEqual("before", direct[0]["side"])
        self.assertEqual("dependency_edge_removed", direct[0]["cause"]["type"])
        self.assertEqual(1, len(direct[0]["path"]))

    def test_diff_alignment_candidates_do_not_change_authoritative_identity(self) -> None:
        candidate = Path(self.temp.name) / "content-addressed-v2"
        shutil.copytree(PACK_V2, candidate)
        records = json.loads((candidate / "records.json").read_text(encoding="utf-8"))
        id_map = {
            record["record_id"]: f"content-2026-{index}"
            for index, record in enumerate(records["records"], start=1)
        }
        for record in records["records"]:
            record["record_id"] = id_map[record["record_id"]]
            for dependency in record["dependencies"]:
                dependency["target_record_id"] = id_map[dependency["target_record_id"]]
        self._rewrite_inventoried_json(candidate, "records.json", records)

        first_digest = self._install_v1()
        second_digest = self.service.install_pack(candidate, POLICY)["package_digest"]
        packet = self.service.diff_editions(first_digest, second_digest, "local-user")

        self.assertEqual(
            "exact_record_id_only_with_non_authoritative_candidates_v1",
            packet["alignment_mode"],
        )
        self.assertEqual(
            {"added": 3, "removed": 3, "modified": 0, "moved": 0, "unchanged": 0},
            packet["change_counts"],
        )
        self.assertEqual(3, len(packet["alignment_candidates"]))
        self.assertTrue(
            all(
                item["review_status"] == "review_required"
                for item in packet["alignment_candidates"]
            )
        )
        self.assertTrue(packet["dependency_edges_added"])
        self.assertTrue(packet["dependency_edges_removed"])

    def test_schema_version_one_migrates_without_reclassifying_legacy_records(self) -> None:
        migration_root = Path(self.temp.name) / "migration"
        migration_root.mkdir()
        db_path = migration_root / "legacy.db"
        with closing(sqlite3.connect(db_path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO metadata(key, value) VALUES('schema_version', '1');
                CREATE TABLE records (
                    package_digest TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    edition_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    clause_reference TEXT NOT NULL,
                    heading TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    PRIMARY KEY(package_digest, record_id)
                );
                """
            )
        StandardsForgeService(db_path, migration_root / "objects")
        with closing(sqlite3.connect(db_path)) as connection, connection:
            version = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()[0]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(records)")}
        self.assertEqual("4", version)
        self.assertIn("statement_role", columns)
        self.assertIn("derivation_json", columns)
        self.assertIn("structure_json", columns)


if __name__ == "__main__":
    unittest.main()
