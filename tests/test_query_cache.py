from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.query_cache import VersionedLRUCache  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402
from standardsforge import service as service_module  # noqa: E402


PACK_V1 = ROOT / "examples" / "packs" / "fictional-adapter-v1"
POLICY = ROOT / "examples" / "policies" / "local-synthetic.json"


class QueryCacheAndBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-cache-test-")
        base = Path(self.temp.name)
        self.service = StandardsForgeService(base / "memory.db", base / "objects")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_batched_graph_preserves_existing_order_in_one_connection(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        with patch.object(self.service.store, "connect", wraps=self.service.store.connect) as connect:
            rows, relationships, missing = self.service.store.evidence_graph(
                digest, ["4.2.1", "4.2.2", "4.2.1"]
            )
        self.assertEqual(1, connect.call_count)
        self.assertEqual([], missing)
        self.assertEqual(
            ["clause-4.2.1", "note-4.2.1-1", "clause-4.2.2"],
            [row["record_id"] for row in rows],
        )
        self.assertEqual(
            [{"source_record_id": "clause-4.2.1", "relationship": "governed_by", "target_record_id": "note-4.2.1-1"}],
            relationships,
        )

    def test_cache_envelope_is_versioned_bounded_and_corruption_is_a_miss(self) -> None:
        cache = VersionedLRUCache("closure", "1", max_entries=2, max_bytes=2048)
        first = cache.key({"package_digest": "a" * 64, "roots": ["4.2.1"]})
        changed = cache.key({"package_digest": "a" * 64, "roots": ["4.2.2"]})
        self.assertNotEqual(first, changed)
        cache.put(first, {"record_ids": ["clause-4.2.1"]})
        self.assertEqual({"record_ids": ["clause-4.2.1"]}, cache.get(first))

        payload, checksum = cache._entries[first]
        cache._entries[first] = (payload + b" ", checksum)
        self.assertIsNone(cache.get(first))
        self.assertEqual(0, cache.stats()["entries"])

        cache.put(first, json.loads('{"value": 1}'))
        cache.put(changed, {"value": 2})
        third = cache.key({"package_digest": "b" * 64, "roots": ["4.2.1"]})
        cache.put(third, {"value": 3})
        self.assertEqual(2, cache.stats()["entries"])
        self.assertIsNone(cache.get(first))

    def test_cache_generations_change_on_install_grant_and_revocation(self) -> None:
        before = self.service.store.cache_state("local-user")
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        installed = self.service.store.cache_state("local-user")
        self.assertGreater(int(installed["corpus_generation"]), int(before["corpus_generation"]))
        self.assertGreater(int(installed["authorization_generation"]), int(before["authorization_generation"]))
        self.assertNotEqual(before["visibility_fingerprint"], installed["visibility_fingerprint"])

        self.service.install_pack(PACK_V1, POLICY)
        regranted = self.service.store.cache_state("local-user")
        self.assertEqual(installed["corpus_generation"], regranted["corpus_generation"])
        self.assertGreater(int(regranted["authorization_generation"]), int(installed["authorization_generation"]))

        self.service.revoke(digest, "local-user")
        revoked = self.service.store.cache_state("local-user")
        self.assertGreater(int(revoked["authorization_generation"]), int(regranted["authorization_generation"]))
        self.assertEqual(before["visibility_fingerprint"], revoked["visibility_fingerprint"])

    def test_request_memo_reads_shared_source_once_and_warm_closure_rechecks_tampering(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        original_read_bytes = Path.read_bytes
        reads: list[Path] = []

        def tracked_read_bytes(path: Path) -> bytes:
            reads.append(path)
            return original_read_bytes(path)

        with patch.object(Path, "read_bytes", tracked_read_bytes):
            self.service.build_context(digest, ["4.2.1", "4.2.2"], "local-user")
        source_reads = [path for path in reads if path.suffix == ".txt"]
        self.assertEqual(1, len(source_reads))
        self.assertEqual(1, self.service._closure_cache.stats()["entries"])

        source_path = self.service.store.object_root / digest / "sources" / "example-spec-100a.txt"
        source_path.write_bytes(source_path.read_bytes() + b"tamper")
        with self.assertRaises(StandardsForgeError) as caught:
            self.service.build_context(digest, ["4.2.1", "4.2.2"], "local-user")
        self.assertEqual("source_integrity_failure", caught.exception.code)
        self.assertGreaterEqual(self.service._closure_cache.stats()["hits"], 1)

    def test_search_cache_is_visibility_versioned_and_reauthorized(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        with patch.object(self.service.store, "search", wraps=self.service.store.search) as search:
            first = self.service.search("axial load", "local-user")
            second = self.service.search("axial load", "local-user")
            self.assertEqual(first, second)
            self.assertEqual(1, search.call_count)

            self.assertEqual([], self.service.search("axial load", "other-user")["results"])
            self.assertEqual(2, search.call_count)

            self.service.revoke(digest, "local-user")
            self.assertEqual([], self.service.search("axial load", "local-user")["results"])
            self.assertEqual(3, search.call_count)

    def test_search_cache_echoes_exact_request_and_keeps_unpinned_filters_unpinned(self) -> None:
        pack_v1_digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        pack_v2 = ROOT / "examples" / "packs" / "fictional-adapter-v2"
        pack_v2_digest = self.service.install_pack(pack_v2, POLICY)["package_digest"]

        first = self.service.search("adapter", "local-user")
        second = self.service.search("adapter!", "local-user")
        self.assertIsNone(first["filters"]["package_digest"])
        self.assertIsNone(second["filters"]["package_digest"])
        self.assertEqual("adapter!", second["query"])
        self.assertEqual(
            {pack_v1_digest, pack_v2_digest},
            {result["package_digest"] for result in first["results"]},
        )

        self.service.search("adapter", "local-user", scope_prefix="4.2.2")
        scoped = self.service.search("adapter!", "local-user", scope_prefix=" 4.2.2 ")
        self.assertEqual({"package_digest": None, "scope_prefix": " 4.2.2 "}, scoped["filters"])

    def test_search_rejects_queries_over_the_term_limit_without_truncating(self) -> None:
        query = " ".join(f"term{index}" for index in range(33))
        with patch.object(self.service.store, "search", wraps=self.service.store.search) as lexical_search:
            with self.assertRaises(StandardsForgeError) as caught:
                self.service.search(query, "local-user")

        self.assertEqual("invalid_query", caught.exception.code)
        self.assertEqual({"max_terms": 32, "actual_terms": 33}, caught.exception.details)
        lexical_search.assert_not_called()

    def test_search_rejects_oversized_text_and_terms_before_store_access(self) -> None:
        cases = (
            "x" * 4097,
            "é" * 4096,
            "x" * 257,
        )
        with patch.object(self.service.store, "search", wraps=self.service.store.search) as lexical_search:
            for query in cases:
                with self.subTest(length=len(query), bytes=len(query.encode("utf-8"))):
                    with self.assertRaises(StandardsForgeError) as caught:
                        self.service.search(query, "local-user")
                    self.assertEqual("invalid_query", caught.exception.code)
        lexical_search.assert_not_called()

    def test_search_modes_are_explicit_distinct_and_cache_separated(self) -> None:
        self.service.install_pack(PACK_V1, POLICY)

        default_all = self.service.search("axial ingress", "local-user")
        explicit_all = self.service.search(
            "axial ingress", "local-user", query_mode="all_terms"
        )
        any_terms = self.service.search(
            "axial ingress", "local-user", query_mode="any_terms"
        )
        exact_phrase = self.service.search(
            "steady axial load", "local-user", query_mode="exact_phrase"
        )
        reversed_phrase = self.service.search(
            "axial steady load", "local-user", query_mode="exact_phrase"
        )
        natural = self.service.search(
            "How should connectors be retained under loads?",
            "local-user",
            query_mode="natural_language",
        )

        self.assertEqual(default_all, explicit_all)
        self.assertEqual([], default_all["results"])
        self.assertEqual(
            {"clause-4.2.1", "clause-4.2.2"},
            {item["record_id"] for item in any_terms["results"]},
        )
        self.assertEqual(
            ["clause-4.2.1"],
            [item["record_id"] for item in exact_phrase["results"]],
        )
        self.assertEqual([], reversed_phrase["results"])
        self.assertEqual(
            {"clause-4.2.1", "note-4.2.1-1"},
            {item["record_id"] for item in natural["results"]},
        )
        self.assertEqual("stemmed_any_terms", natural["query_interpretation"]["selected_strategy"])
        self.assertEqual(
            ["should", "connectors", "retained", "under", "loads"],
            natural["query_interpretation"]["effective_terms"],
        )
        self.assertEqual(
            {
                "mode": "any_terms",
                "normalized_query": "axial ingress",
                "parsed_terms": ["axial", "ingress"],
            },
            any_terms["query_interpretation"],
        )

        identifier_chunks = self.service.search(
            "4.2.1 water", "local-user", query_mode="any_terms"
        )
        self.assertEqual(
            {"clause-4.2.1", "note-4.2.1-1", "clause-4.2.2"},
            {item["record_id"] for item in identifier_chunks["results"]},
        )

        with patch.object(
            self.service.store, "search", wraps=self.service.store.search
        ) as lexical_search:
            for mode in ("exact_phrase", "all_terms", "any_terms", "natural_language"):
                packet = self.service.search("adapter", "local-user", query_mode=mode)
                self.assertEqual(mode, packet["query_interpretation"]["mode"])
            self.assertEqual(4, lexical_search.call_count)
            self.service.search("adapter", "local-user", query_mode="all_terms")
            self.assertEqual(4, lexical_search.call_count)

        for invalid_mode in ("", "implicit", "ALL_TERMS", " all_terms ", None, [], {}):
            with self.subTest(query_mode=invalid_mode):
                with self.assertRaises(StandardsForgeError) as caught:
                    self.service.search(
                        "axial load", "local-user", query_mode=invalid_mode  # type: ignore[arg-type]
                    )
                self.assertEqual("invalid_query_mode", caught.exception.code)

    def test_natural_language_relaxation_is_bounded_and_disclosed(self) -> None:
        self.service.install_pack(PACK_V1, POLICY)
        with patch.object(self.service.store, "search", wraps=self.service.store.search) as lexical_search:
            packet = self.service.search(
                "axial nonexistenttopic", "local-user", query_mode="natural_language"
            )
        self.assertEqual(2, lexical_search.call_count)
        self.assertEqual(
            ["stemmed_all_terms", "stemmed_any_terms"],
            packet["query_interpretation"]["attempted_strategies"],
        )
        self.assertEqual("stemmed_any_terms", packet["query_interpretation"]["selected_strategy"])
        self.assertTrue(packet["results"])
        self.assertIn("disclosed relaxed strategy", packet["limitations"][-1])

    def test_natural_language_preserves_modality_conditions_and_request_echo_on_cache_hit(self) -> None:
        self.service.install_pack(PACK_V1, POLICY)
        first = self.service.search(
            "how shall connector be retained under load",
            "local-user",
            query_mode="natural_language",
        )
        second = self.service.search(
            "what shall connector be retained under load",
            "local-user",
            query_mode="natural_language",
        )
        self.assertEqual(
            ["shall", "connector", "retained", "under", "load"],
            second["query_interpretation"]["effective_terms"],
        )
        self.assertEqual("what shall connector be retained under load", second["query_interpretation"]["normalized_query"])
        self.assertEqual(first["query_interpretation"]["selected_strategy"], second["query_interpretation"]["selected_strategy"])
        self.assertIn("what", second["query_interpretation"]["ignored_terms"])
        self.assertNotIn("how", second["query_interpretation"]["ignored_terms"])

    def test_natural_language_rejects_scaffolding_only_without_store_access(self) -> None:
        with patch.object(self.service.store, "search", wraps=self.service.store.search) as lexical_search:
            with self.assertRaises(StandardsForgeError) as caught:
                self.service.search(
                    "what does the standard say",
                    "local-user",
                    query_mode="natural_language",
                )
        self.assertEqual("invalid_query", caught.exception.code)
        lexical_search.assert_not_called()

    def test_natural_language_prefixes_identifiers_but_not_quantities(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        connection = self.service.store.connect()
        try:
            connection.execute(
                "UPDATE records SET text = ? WHERE package_digest = ? AND record_id = ?",
                ("MIL-STD-810H uses a threshold of 800 N.", digest, "clause-4.2.2"),
            )
            connection.commit()
        finally:
            connection.close()
        identifier = self.service.search(
            "MIL-STD-810", "local-user", query_mode="natural_language"
        )
        quantity = self.service.search("80", "local-user", query_mode="natural_language")
        self.assertEqual(["clause-4.2.2"], [item["record_id"] for item in identifier["results"]])
        self.assertEqual(["clause-4.2.1"], [item["record_id"] for item in quantity["results"]])

    def test_unauthorized_rows_do_not_change_visible_search_scores_or_order(self) -> None:
        first_digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        before = self.service.search("adapter", "local-user", query_mode="any_terms")
        second_digest = self.service.install_pack(
            ROOT / "examples" / "packs" / "fictional-adapter-v2", POLICY
        )["package_digest"]
        self.service.revoke(second_digest, "local-user")
        after = self.service.search("adapter", "local-user", query_mode="any_terms")
        self.assertEqual(first_digest, before["results"][0]["package_digest"])
        self.assertEqual(
            [(item["record_id"], item["score"]) for item in before["results"]],
            [(item["record_id"], item["score"]) for item in after["results"]],
        )

    def test_natural_language_retries_when_authorization_changes_between_strategies(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        original_search = self.service.store.search
        calls = 0

        def search_with_revocation(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            rows = original_search(*args, **kwargs)
            if calls == 1:
                self.service.revoke(digest, "local-user")
            return rows

        with patch.object(self.service.store, "search", side_effect=search_with_revocation):
            packet = self.service.search(
                "axial nonexistenttopic", "local-user", query_mode="natural_language"
            )
        self.assertEqual([], packet["results"])
        self.assertGreaterEqual(calls, 3)

    def test_search_returns_source_linked_snippets_and_structural_heading_ancestry(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        structures = {
            "clause-4.2.1": {"logical_id": "target", "parent_logical_id": "section"},
            "clause-4.2.2": {"logical_id": "section", "parent_logical_id": "root"},
            "note-4.2.1-1": {"logical_id": "root", "parent_logical_id": None},
        }
        connection = self.service.store.connect()
        try:
            for record_id, structure in structures.items():
                connection.execute(
                    "UPDATE records SET structure_json = ? WHERE package_digest = ? AND record_id = ?",
                    (json.dumps(structure, sort_keys=True), digest, record_id),
                )
            connection.commit()
        finally:
            connection.close()

        packet = self.service.search("axial load", "local-user")
        result = packet["results"][0]
        records = json.loads((PACK_V1 / "records.json").read_text(encoding="utf-8"))["records"]
        source = next(record["source"] for record in records if record["record_id"] == "clause-4.2.1")
        self.assertEqual(source, result["source"])
        self.assertEqual({"start": "⟦", "end": "⟧"}, packet["snippet_markers"])
        self.assertEqual(
            "The adapter shall retain the connector under a steady axial load of 80 N for 60 seconds.",
            result["matched_snippet"].replace("⟦", "").replace("⟧", ""),
        )
        self.assertEqual(
            [
                {
                    "record_id": "note-4.2.1-1",
                    "clause_reference": "4.2.1 NOTE 1",
                    "heading": "Governing condition",
                },
                {
                    "record_id": "clause-4.2.2",
                    "clause_reference": "4.2.2",
                    "heading": "Interface sealing",
                },
            ],
            result["heading_ancestry"],
        )

    def test_enumeration_batches_graph_and_shares_one_verification_context(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        expected = {
            reference: self.service.get_clause(digest, reference, "local-user")
            for reference in ("4.2.1", "4.2.2")
        }
        original_read_bytes = Path.read_bytes
        reads: list[Path] = []

        def tracked_read_bytes(path: Path) -> bytes:
            reads.append(path)
            return original_read_bytes(path)

        with (
            patch.object(self.service, "get_clause", side_effect=AssertionError("enumeration must batch roots")),
            patch.object(self.service.store, "connect", wraps=self.service.store.connect) as connect,
            patch.object(Path, "read_bytes", tracked_read_bytes),
            patch.object(service_module, "_decode_utf8", wraps=service_module._decode_utf8) as decode,
        ):
            packet = self.service.enumerate_obligations(digest, "local-user", limit=100)

        self.assertEqual(5, connect.call_count)
        self.assertEqual(1, decode.call_count)
        self.assertEqual(
            1,
            len([path for path in reads if path.name == "example-spec-100a.txt"]),
        )
        self.assertEqual(["4.2.1", "4.2.2"], [item["clause_reference"] for item in packet["obligations"]])
        for obligation in packet["obligations"]:
            legacy = expected[obligation["clause_reference"]]
            self.assertEqual(legacy["evidence"], obligation["evidence"])
            self.assertEqual(legacy["required_relationships"], obligation["required_relationships"])

    def test_edition_diff_verifies_each_package_source_once(self) -> None:
        before_digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        after_digest = self.service.install_pack(
            ROOT / "examples" / "packs" / "fictional-adapter-v2", POLICY
        )["package_digest"]
        expected = self.service.diff_editions(before_digest, after_digest, "local-user")
        original_read_bytes = Path.read_bytes
        reads: list[Path] = []

        def tracked_read_bytes(path: Path) -> bytes:
            reads.append(path)
            return original_read_bytes(path)

        with (
            patch.object(Path, "read_bytes", tracked_read_bytes),
            patch.object(service_module, "_decode_utf8", wraps=service_module._decode_utf8) as decode,
        ):
            packet = self.service.diff_editions(before_digest, after_digest, "local-user")

        source_reads = [path for path in reads if path.suffix == ".txt"]
        reads_by_package = {
            digest: sum(1 for path in source_reads if path.parent.parent.name == digest)
            for digest in (before_digest, after_digest)
        }
        self.assertEqual({before_digest: 1, after_digest: 1}, reads_by_package)
        self.assertEqual(2, decode.call_count)
        self.assertEqual(expected, packet)


if __name__ == "__main__":
    unittest.main()
