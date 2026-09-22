from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.errors import StandardsForgeError
from standardsforge.service import StandardsForgeService


PACK_V1 = ROOT / "examples" / "packs" / "fictional-adapter-v1"
PACK_V2 = ROOT / "examples" / "packs" / "fictional-adapter-v2"
POLICY = ROOT / "examples" / "policies" / "local-synthetic.json"


class DocumentDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-discovery-")
        base = Path(self.temp.name)
        self.service = StandardsForgeService(base / "memory.db", base / "objects")
        self.first_digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        self.second_digest = self.service.install_pack(PACK_V2, POLICY)["package_digest"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_lists_exact_authorized_metadata_with_stable_pagination(self) -> None:
        first = self.service.list_documents("local-user", " example - spec ", limit=1)
        self.assertEqual("list_documents", first["operation"])
        self.assertEqual("EXAMPLE-SPEC", first["filters"]["normalized_identifier_prefix"])
        self.assertEqual(1, first["page"]["returned"])
        self.assertEqual(2, first["page"]["matching_authorized_package_count"])
        self.assertTrue(first["page"]["has_more"])
        document = first["documents"][0]
        self.assertEqual(self.first_digest, document["package_digest"])
        self.assertEqual(3, document["record_count"])
        self.assertEqual("complete_for_fixture", document["declared_coverage"]["parsed_source_coverage"])

        final = self.service.list_documents(
            "local-user", "EXAMPLE-SPEC", limit=1, cursor=first["page"]["next_cursor"]
        )
        self.assertEqual(self.second_digest, final["documents"][0]["package_digest"])
        self.assertEqual(1, final["page"]["previously_returned"])
        self.assertEqual(2, final["page"]["cumulative_returned"])
        self.assertFalse(final["page"]["has_more"])
        self.assertIsNone(final["page"]["next_cursor"])

    def test_empty_or_revoked_principal_does_not_leak_documents_or_hints(self) -> None:
        self.assertEqual([], self.service.list_documents("unknown-user")["documents"])
        self.service.revoke(self.first_digest, "local-user")
        remaining = self.service.list_documents("local-user")
        self.assertEqual([self.second_digest], [item["package_digest"] for item in remaining["documents"]])

        with self.assertRaises(StandardsForgeError) as caught:
            self.service.resolve_document("EXAMPLE-SPEC-100", "unknown-user", "missing-edition")
        self.assertEqual("not_found", caught.exception.code)
        self.assertEqual([], caught.exception.details["candidates"])

    def test_near_matches_are_bounded_authorized_and_replayable(self) -> None:
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.resolve_document("EXAMPLE-SPEC", "local-user")
        self.assertEqual("not_found", caught.exception.code)
        details = caught.exception.details
        self.assertEqual("list_documents", details["discovery_operation"])
        self.assertEqual(2, len(details["candidates"]))
        self.assertTrue(all(item["match_basis"] == "identifier_prefix" for item in details["candidates"]))
        for candidate in details["candidates"]:
            selector = candidate["resolve_selector"]
            resolved = self.service.resolve_document(
                selector["identifier"], "local-user", selector["edition_id"], selector["representation"]
            )
            self.assertEqual(candidate["package_digest"], resolved["package_digest"])

        with self.assertRaises(StandardsForgeError) as wrong_edition:
            self.service.resolve_document(
                "EXAMPLE-SPEC-100", "local-user", "example:spec-100:missing"
            )
        self.assertTrue(
            all(
                candidate["match_basis"] == "exact_identifier_alternate_selector"
                for candidate in wrong_edition.exception.details["candidates"]
            )
        )

    def test_rejects_invalid_tampered_or_mismatched_cursors(self) -> None:
        for limit in (True, 0, 101):
            with self.subTest(limit=limit), self.assertRaises(StandardsForgeError) as caught:
                self.service.list_documents("local-user", limit=limit)
            self.assertEqual("invalid_limit", caught.exception.code)

        first = self.service.list_documents("local-user", limit=1)
        cursor = first["page"]["next_cursor"]
        assert cursor is not None
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.list_documents("local-user", limit=1, cursor=cursor[:-1] + ("A" if cursor[-1] != "A" else "B"))
        self.assertEqual("invalid_cursor", caught.exception.code)
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.list_documents("local-user", "EXAMPLE-SPEC-100", limit=1, cursor=cursor)
        self.assertEqual("cursor_scope_mismatch", caught.exception.code)

        self.service.revoke(self.second_digest, "local-user")
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.list_documents("local-user", limit=1, cursor=cursor)
        self.assertEqual("cursor_inventory_changed", caught.exception.code)

    def test_near_matches_fail_if_authorization_changes_during_assembly(self) -> None:
        original = self.service._resolve_candidates

        def revoke_after_building(*args):
            result = original(*args)
            self.service.revoke(self.first_digest, "local-user")
            return result

        with patch.object(self.service, "_resolve_candidates", side_effect=revoke_after_building):
            with self.assertRaises(StandardsForgeError) as caught:
                self.service.resolve_document("EXAMPLE-SPEC", "local-user")
        self.assertEqual("authorization_changed", caught.exception.code)
        self.assertEqual({}, caught.exception.details)


if __name__ == "__main__":
    unittest.main()
