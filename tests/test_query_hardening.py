from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge import store as store_module  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.identity import normalize_identifier  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402
from standardsforge.store import read_only_database_uri  # noqa: E402


PACK_V1 = ROOT / "examples" / "packs" / "fictional-adapter-v1"
PACK_V2 = ROOT / "examples" / "packs" / "fictional-adapter-v2"
POLICY = ROOT / "examples" / "policies" / "local-synthetic.json"
PRINCIPAL = "local-user"


def _variant_pack(destination: Path, references: dict[str, str]) -> Path:
    """Copy the synthetic pack with replaced clause references and a recomputed inventory."""

    shutil.copytree(PACK_V1, destination)
    records_path = destination / "records.json"
    records = json.loads(records_path.read_text(encoding="utf-8"))
    for record in records["records"]:
        if record["record_id"] in references:
            record["clause_reference"] = references[record["record_id"]]
            record["source"]["locator"] = references[record["record_id"]]
    records_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    inventory_path = destination / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for entry in inventory["files"]:
        data = (destination / entry["path"]).read_bytes()
        entry["sha256"], entry["bytes"] = hashlib.sha256(data).hexdigest(), len(data)
    inventory_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return destination


class _ServiceFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-hardening-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.admin = StandardsForgeService(self.base / "memory.db", self.base / "objects")

    def install(self, pack: Path) -> str:
        return self.admin.install_pack(pack, POLICY)["package_digest"]

    def read_only(self) -> StandardsForgeService:
        return StandardsForgeService.open_read_only(self.base / "memory.db", self.base / "objects")

    def assert_code(self, code: str, call: Callable[[], Any]) -> None:
        with self.assertRaises(StandardsForgeError) as caught:
            call()
        self.assertEqual(code, caught.exception.code)


class ScopePrefixCaseTests(_ServiceFixture):
    def setUp(self) -> None:
        super().setUp()
        pack = _variant_pack(self.base / "case-pack", {"clause-4.2.1": "A", "note-4.2.1-1": "A.1", "clause-4.2.2": "a.1"})
        self.digest = self.install(pack)
        self.service = self.read_only()

    def test_descendant_scope_is_exact_and_case_sensitive_across_operations(self) -> None:
        enumerated = self.service.enumerate_obligations(self.digest, PRINCIPAL, scope_prefix="A")
        self.assertEqual(["A"], [item["clause_reference"] for item in enumerated["obligations"]])
        self.assertEqual(1, enumerated["page"]["declared_scope_total"])
        browsed = self.service.browse_records(self.digest, PRINCIPAL, scope_prefix="A")
        self.assertEqual(["A", "A.1"], [item["clause_reference"] for item in browsed["records"]])
        self.assertEqual(2, browsed["page"]["matching_record_count"])
        searched = self.service.search("adapter", PRINCIPAL, scope_prefix="A")
        self.assertEqual(["A"], [item["clause_reference"] for item in searched["results"]])
        lower = self.service.enumerate_obligations(self.digest, PRINCIPAL, scope_prefix="a")
        self.assertEqual(["a.1"], [item["clause_reference"] for item in lower["obligations"]])
        self.assertEqual(1, lower["page"]["declared_scope_total"])

    def test_like_metacharacters_in_scope_match_nothing(self) -> None:
        for scope in ("_", "%", "A%", "\\", "[A]", "*"):
            with self.subTest(scope=scope):
                self.assertEqual([], self.service.search("adapter", PRINCIPAL, scope_prefix=scope)["results"])
                self.assertEqual([], self.service.browse_records(self.digest, PRINCIPAL, scope_prefix=scope)["records"])


class ExactClauseReferenceTests(_ServiceFixture):
    def setUp(self) -> None:
        super().setUp()
        self.digest = self.install(_variant_pack(self.base / "space-pack", {"clause-4.2.2": "4.2.1 "}))
        self.service = self.read_only()

    @staticmethod
    def root(packet: dict[str, Any]) -> str:
        return packet["evidence"][0]["record_id"]

    def test_record_id_path_preserves_trailing_space_reference(self) -> None:
        packet = self.service.get_clause(self.digest, principal_id=PRINCIPAL, record_id="clause-4.2.2")
        self.assertEqual("clause-4.2.2", self.root(packet))
        self.assertEqual("4.2.1 ", packet["evidence"][0]["clause_reference"])
        selector = self.service.search("water ingress", PRINCIPAL)["results"][0]["evidence_selector"]
        self.assertEqual("4.2.1 ", selector["clause_reference"])
        replay = self.service.get_clause(self.digest, selector["clause_reference"], PRINCIPAL, record_id=selector["record_id"])
        self.assertEqual("clause-4.2.2", self.root(replay))
        selected = self.service.select_evidence(self.digest, "clause-4.2.2", PRINCIPAL)
        self.assertIn('"clause-4.2.2"', json.dumps(selected["evidence"]))
        self.assertNotIn('"clause-4.2.1"', json.dumps(selected["evidence"]))

    def test_colliding_whitespace_references_resolve_exactly(self) -> None:
        self.assertEqual("clause-4.2.1", self.root(self.service.get_clause(self.digest, "4.2.1", PRINCIPAL)))
        self.assertEqual("clause-4.2.2", self.root(self.service.get_clause(self.digest, "4.2.1 ", PRINCIPAL)))
        self.assert_code("not_found", lambda: self.service.get_clause(self.digest, " 4.2.1", PRINCIPAL))
        self.assert_code("record_selector_mismatch",
                         lambda: self.service.get_clause(self.digest, "4.2.1", PRINCIPAL, record_id="clause-4.2.2"))
        built = self.service.build_context(self.digest, ["4.2.1 ", "4.2.1"], PRINCIPAL)
        self.assertEqual(["4.2.1 ", "4.2.1"], built["requested_clause_references"])
        self.assertEqual({"clause-4.2.1", "note-4.2.1-1", "clause-4.2.2"}, {item["record_id"] for item in built["evidence"]})
        only_padded = self.service.build_context(self.digest, ["4.2.1 "], PRINCIPAL)
        self.assertEqual(["clause-4.2.2"], [item["record_id"] for item in only_padded["evidence"]])
        self.assert_code("not_found", lambda: self.service.build_context(self.digest, ["4.2.2 "], PRINCIPAL))


class InstalledSyntheticTests(_ServiceFixture):
    def setUp(self) -> None:
        super().setUp()
        self.first = self.install(PACK_V1)
        self.second = self.install(PACK_V2)
        self.service = self.read_only()

    def test_punctuation_only_tokens_are_not_search_terms(self) -> None:
        for mode, first, second in (("all_terms", "connector", "axial"), ("any_terms", "connector", "axial"),
                                    ("natural_language", "connector", "axial"), ("exact_phrase", "axial", "load")):
            with self.subTest(mode=mode):
                plain = self.service.search(f"{first} {second}", PRINCIPAL, query_mode=mode)
                for separator in (" / ", " - ", " _ ", " . ", " -/- "):
                    punctuated = self.service.search(first + separator + second, PRINCIPAL, query_mode=mode)
                    self.assertEqual([r["record_id"] for r in plain["results"]],
                                     [r["record_id"] for r in punctuated["results"]])
                    self.assertEqual([first, second], punctuated["query_interpretation"]["parsed_terms"])
                    if mode == "natural_language":
                        self.assertEqual("stemmed_all_terms", punctuated["query_interpretation"]["selected_strategy"])
                self.assertTrue(plain["results"])
        for query in ("-", "/ . _", "--- ///"):
            with self.subTest(query=query):
                self.assert_code("invalid_query", lambda: self.service.search(query, PRINCIPAL))
        # Punctuation is removed before the term-count limit; real terms still count.
        self.assertTrue(self.service.search("adapter " + "- " * 40, PRINCIPAL)["results"])
        self.assert_code("invalid_query", lambda: self.service.search(" ".join(["adapter"] * 33), PRINCIPAL))

    def test_browse_strips_scope_like_search_and_enumerate(self) -> None:
        padded = self.service.browse_records(self.first, PRINCIPAL, scope_prefix=" 4.2.1 ")
        exact = self.service.browse_records(self.first, PRINCIPAL, scope_prefix="4.2.1")
        self.assertEqual([r["record_id"] for r in exact["records"]], [r["record_id"] for r in padded["records"]])
        self.assertEqual(["clause-4.2.1"], [r["record_id"] for r in padded["records"]])
        self.assertEqual("4.2.1", padded["filters"]["scope_prefix"])
        searched = self.service.search("adapter", PRINCIPAL, package_digest=self.first, scope_prefix=" 4.2.1 ")
        self.assertEqual(["clause-4.2.1"], [r["record_id"] for r in searched["results"]])
        self.assert_code("invalid_selector", lambda: self.service.browse_records(self.first, PRINCIPAL, scope_prefix="   "))

    def test_list_documents_accepts_single_character_prefix_only_for_listing(self) -> None:
        listed = self.service.list_documents(PRINCIPAL, "e")
        self.assertEqual("E", listed["filters"]["normalized_identifier_prefix"])
        self.assertEqual(2, listed["page"]["matching_authorized_package_count"])
        self.assertEqual(0, self.service.list_documents(PRINCIPAL, "Z")["page"]["matching_authorized_package_count"])
        following = self.service.list_documents(PRINCIPAL, "E", limit=1)
        resumed = self.service.list_documents(PRINCIPAL, "E", limit=1, cursor=following["page"]["next_cursor"])
        self.assertEqual(1, resumed["page"]["returned"])
        self.assert_code("invalid_identifier", lambda: self.service.list_documents(PRINCIPAL, "-"))
        self.assert_code("invalid_identifier", lambda: self.service.list_documents(PRINCIPAL, " "))
        self.assert_code("invalid_identifier", lambda: self.service.resolve_document("E", PRINCIPAL))
        self.assert_code("invalid_identifier", lambda: normalize_identifier("E"))
        self.assertEqual("E", normalize_identifier("e", prefix=True))

    def test_lone_surrogates_raise_typed_errors(self) -> None:
        bad = "\ud800"
        cases = {
            "invalid_query": [lambda: self.service.search(bad, PRINCIPAL),
                              lambda: self.service.search("adapter " + bad, PRINCIPAL)],
            "invalid_scope": [lambda: self.service.search("adapter", PRINCIPAL, scope_prefix=bad),
                              lambda: self.service.enumerate_obligations(self.first, PRINCIPAL, scope_prefix=bad)],
            "invalid_clause_reference": [lambda: self.service.get_clause(self.first, bad, PRINCIPAL),
                                         lambda: self.service.get_clause(self.first, "4.2.1" + bad, PRINCIPAL),
                                         lambda: self.service.build_context(self.first, ["4.2.1", bad], PRINCIPAL)],
            "invalid_record_id": [lambda: self.service.get_clause(self.first, principal_id=PRINCIPAL, record_id=bad),
                                  lambda: self.service.select_evidence(self.first, bad, PRINCIPAL)],
            "invalid_selector": [lambda: self.service.browse_records(self.first, PRINCIPAL, scope_prefix=bad),
                                 lambda: self.service.browse_records(self.first, PRINCIPAL, relation="children", record_id=bad),
                                 lambda: self.service.resolve_document("EXAMPLE-SPEC-100", PRINCIPAL, edition_id=bad)],
            "invalid_identifier": [lambda: self.service.list_documents(PRINCIPAL, bad)],
        }
        for code, calls in cases.items():
            for index, call in enumerate(calls):
                with self.subTest(code=code, index=index):
                    self.assert_code(code, call)


class ConcurrentObjectActivationTests(_ServiceFixture):
    def collide_on_replace(self, error: OSError, *, alter_existing: bool = False) -> Callable[..., None]:
        def replace(source: Any, destination: Any) -> None:
            shutil.copytree(source, destination)
            if alter_existing:
                (Path(destination) / "rights.json").write_text("{}", encoding="utf-8")
            raise error
        return replace

    def test_enotempty_rename_reuses_identical_concurrent_object(self) -> None:
        for code in (errno.ENOTEMPTY, errno.EEXIST):
            with self.subTest(errno=code):
                temp = tempfile.TemporaryDirectory(prefix="standardsforge-activation-")
                self.addCleanup(temp.cleanup)
                admin = StandardsForgeService(Path(temp.name) / "memory.db", Path(temp.name) / "objects")
                failure = OSError(code, os.strerror(code))
                with patch.object(store_module.os, "replace", side_effect=self.collide_on_replace(failure)):
                    digest = admin.install_pack(PACK_V1, POLICY)["package_digest"]
                objects = Path(temp.name) / "objects"
                self.assertEqual([digest], [entry.name for entry in objects.iterdir()])
                self.assertEqual("clause-4.2.1", admin.get_clause(digest, "4.2.1", PRINCIPAL)["evidence"][0]["record_id"])

    def test_enotempty_with_different_content_or_other_errno_fails_closed(self) -> None:
        failure = OSError(errno.ENOTEMPTY, os.strerror(errno.ENOTEMPTY))
        with patch.object(store_module.os, "replace", side_effect=self.collide_on_replace(failure, alter_existing=True)):
            with self.assertRaises(StandardsForgeError):
                self.install(PACK_V1)
        self.assertEqual([], self.admin.list_documents(PRINCIPAL)["documents"])
        other = self.base / "other"
        admin = StandardsForgeService(other / "memory.db", other / "objects")
        with patch.object(store_module.os, "replace", side_effect=OSError(errno.EIO, os.strerror(errno.EIO))):
            with self.assertRaises(OSError) as caught:
                admin.install_pack(PACK_V1, POLICY)
        self.assertEqual(errno.EIO, caught.exception.errno)
        self.assertEqual([], list((other / "objects").iterdir()))


# "?" must be percent-encoded in a URI but is not a valid Windows file-name character.
_QUESTION = "" if os.name == "nt" else "?"


class ReadOnlyDatabaseUriTests(unittest.TestCase):
    def test_posix_drive_and_unc_paths(self) -> None:
        cases = [
            (PurePosixPath("/var/lib/sf/memory.db"), "file:///var/lib/sf/memory.db?mode=ro"),
            (PurePosixPath("/tmp/a b/x#y?z%/ü.db"), "file:///tmp/a%20b/x%23y%3Fz%25/%C3%BC.db?mode=ro"),
            (PureWindowsPath(r"C:\Data Store\memory.db"), "file:///C:/Data%20Store/memory.db?mode=ro"),
            (PureWindowsPath(r"\\server\share\sf #1\mémoire.db"),
             "file:////server/share/sf%20%231/m%C3%A9moire.db?mode=ro"),
        ]
        for path, expected in cases:
            with self.subTest(path=str(path)):
                self.assertEqual(expected, read_only_database_uri(path))
        for relative in (PurePosixPath("memory.db"), PureWindowsPath("C:memory.db"), PureWindowsPath(r"data\memory.db")):
            with self.subTest(relative=str(relative)):
                with self.assertRaises(ValueError):
                    read_only_database_uri(relative)

    def test_round_trip_opens_read_only_database_with_special_characters(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-uri-") as temp:
            directory = Path(temp) / f"store dir #1 {_QUESTION}x %41 ünï"
            directory.mkdir()
            path = directory / "memory db#ü.sqlite"
            with closing(sqlite3.connect(path)) as writer, writer:
                writer.execute("CREATE TABLE probe(value TEXT)")
                writer.execute("INSERT INTO probe VALUES ('ok')")
            with closing(sqlite3.connect(read_only_database_uri(path), uri=True)) as reader:
                self.assertEqual("ok", reader.execute("SELECT value FROM probe").fetchone()[0])
                with self.assertRaises(sqlite3.OperationalError):
                    reader.execute("INSERT INTO probe VALUES ('no')")
            self.assertEqual(["memory db#ü.sqlite"], [entry.name for entry in directory.iterdir()])

    def test_read_only_service_opens_store_under_special_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-uri-") as temp:
            base = Path(temp) / f"sf #state {_QUESTION}ü"
            digest = StandardsForgeService(base / "memory.db", base / "objects").install_pack(PACK_V1, POLICY)["package_digest"]
            service = StandardsForgeService.open_read_only(base / "memory.db", base / "objects")
            self.assertEqual("clause-4.2.1", service.get_clause(digest, "4.2.1", PRINCIPAL)["evidence"][0]["record_id"])


if __name__ == "__main__":
    unittest.main()
