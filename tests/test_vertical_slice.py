from __future__ import annotations

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
        self.assertEqual([], packet["dependency_edges_added"])
        self.assertEqual([], packet["dependency_edges_removed"])

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
        self.assertEqual("2", version)
        self.assertIn("statement_role", columns)
        self.assertIn("derivation_json", columns)


if __name__ == "__main__":
    unittest.main()
