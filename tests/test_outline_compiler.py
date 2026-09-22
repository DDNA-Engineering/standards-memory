from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.outline_compiler import _candidate_matches, compile_derived_outline_pack  # noqa: E402
from standardsforge.pack import open_validated_pack, validate_pack_directory  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402


class OutlineCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-outline-test-")
        self.root = Path(self.temp.name)
        self.base_pack = self.root / "base-pack"
        self.base_pack.mkdir()
        self.page_text = (
            "SYNTHETIC STANDARD HEADER\n"
            "MET HOD 500.6\n"
            "1  Scope. This standard shall define the test scope.\n"
            "1.1  Detailed requirement. Equipment shall withstand the specified load.\n"
            " a. First listing applies under the stated condition.\n"
            "NOTE: Exercise caution during the test.\n"
            "TABLE I. Qualification limits\n"
            "2  22 (49.5) 32 (71.9) 43 (96.7)\n"
            "1  First table footnote applies.\n"
            "2  Second table footnote applies.\n"
            "FIGURE 1. Test arrangement\n"
        )
        self._write_base_page_pack()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _json_bytes(value: object) -> bytes:
        return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")

    def _write_json(self, path: Path, value: object) -> None:
        path.write_bytes(self._json_bytes(value))

    def _write_base_page_pack(self) -> None:
        sources = self.base_pack / "sources"
        sources.mkdir()
        pdf_bytes = b"%PDF-1.4\n% synthetic test source\n"
        text_bytes = self.page_text.encode("utf-8")
        (sources / "test.pdf").write_bytes(pdf_bytes)
        (sources / "test.extracted.txt").write_bytes(text_bytes)
        pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
        text_sha = hashlib.sha256(text_bytes).hexdigest()
        manifest = {
            "schema_version": "0.1.0",
            "pack_id": "test.page-text.1",
            "document_family_id": "test:standard",
            "edition_id": "test:standard:2026",
            "publisher": "Test Publisher",
            "identifier": "TEST-STD-1",
            "title": "Synthetic test standard",
            "revision": "2026",
            "publication_date": "2026-01-01",
            "category": "test_page_text",
            "representation": "page_text",
            "inventory_path": "inventory.json",
            "rights_path": "rights.json",
            "records_path": "records.json",
            "coverage": {
                "corpus_scope": "synthetic_test_page",
                "edition_composition": "complete",
                "parsed_source_coverage": "text_layer_extracted_for_1_of_1_physical_pages",
                "dependency_closure": "not_derived_for_page_records",
                "enumeration_traversal": "page_records_only_not_clause_or_obligation_complete",
                "output_budget_coverage": "computed_at_query_time",
            },
        }
        rights = {
            "rights_schema_version": "0.1.0",
            "content_class": "public_government_standard",
            "redistribution": "test_only",
            "processing": ["local_text_layer_extraction"],
            "model_use": "not_used",
            "statement": "Synthetic local test content.",
        }
        records = {
            "schema_version": "0.2.0",
            "records": [
                {
                    "record_id": "page-1",
                    "edition_id": "test:standard:2026",
                    "kind": "page",
                    "clause_reference": "pdf-page:0001",
                    "heading": "Physical PDF page 1",
                    "source": {
                        "path": "sources/test.pdf",
                        "sha256": pdf_sha,
                        "text_path": "sources/test.extracted.txt",
                        "text_sha256": text_sha,
                        "text_start_byte": 0,
                        "text_end_byte": len(text_bytes),
                        "page": 1,
                        "locator": "physical PDF page 1",
                        "quote_sha256": text_sha,
                    },
                    "derivation": {
                        "statement_role": "unclassified",
                        "method": "synthetic-page-text",
                        "review_status": "unreviewed",
                    },
                    "dependencies": [],
                }
            ],
        }
        self._write_json(self.base_pack / "manifest.json", manifest)
        self._write_json(self.base_pack / "rights.json", rights)
        self._write_json(self.base_pack / "records.json", records)
        files = []
        for relative in ("manifest.json", "records.json", "rights.json", "sources/test.extracted.txt", "sources/test.pdf"):
            data = (self.base_pack / relative).read_bytes()
            files.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        self._write_json(
            self.base_pack / "inventory.json",
            {"schema_version": "0.1.0", "algorithm": "sha256", "files": files},
        )
        validate_pack_directory(self.base_pack)

    def test_compiles_installs_resolves_and_retrieves_unreviewed_outline_offline(self) -> None:
        first_output = self.root / "derived-first"
        second_output = self.root / "derived-second"
        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")):
            first = compile_derived_outline_pack(self.base_pack, first_output)
            second = compile_derived_outline_pack(self.base_pack, second_output)
        self.assertEqual(first["package_digest"], second["package_digest"])
        self.assertEqual(4, first["unsupported_regions"])
        self.assertEqual(0, first["unsupported_pages"])

        with open_validated_pack(first_output) as pack:
            self.assertEqual("derived_structure", pack.manifest["representation"])
            self.assertTrue(all(record["derivation"]["statement_role"] == "unclassified" for record in pack.records))
            self.assertTrue(all(record["derivation"]["review_status"] == "automated_unreviewed" for record in pack.records))
            kinds = {record["kind"] for record in pack.records}
            self.assertTrue({"section", "clause", "list_item", "note", "table", "figure", "unsupported_region"} <= kinds)
            self.assertEqual(1, first["detected_kinds"]["method"])
            self.assertEqual(1, first["detected_kinds"]["section"])
            ambiguous_row = next(
                record
                for record in pack.records
                if record["kind"] == "unsupported_region" and "ambiguous-numbered" in record["clause_reference"]
            )
            self.assertIn("22 (49.5)", ambiguous_row["text"])
            self.assertFalse(
                any(
                    record["kind"] == "section" and record["heading"] == "First table footnote applies"
                    for record in pack.records
                )
            )
            clause = next(record for record in pack.records if record["kind"] == "clause")
            clause_reference = clause["clause_reference"]
            expected_digest = pack.package_digest
            span = clause["structure"]["source_spans"][0]
            sidecar = (pack.root / span["text_path"]).read_bytes()
            self.assertEqual(clause["text"], sidecar[span["start_byte"] : span["end_byte"]].decode("utf-8"))

        policy = self.root / "policy.json"
        self._write_json(
            policy,
            {
                "policy_version": "0.1.0",
                "policy_id": "outline-test-policy",
                "principal_id": "outline-user",
                "allow_admin_install": True,
                "allow_serve": True,
                "allowed_pack_ids": [first["pack_id"]],
                "allowed_content_classes": ["public_government_standard"],
            },
        )
        service = StandardsForgeService(self.root / "memory.db", self.root / "objects")
        installed = service.install_pack(first_output, policy)
        resolved = service.resolve_document(
            "TEST-STD-1", "outline-user", "test:standard:2026", "derived_structure"
        )
        packet = service.get_clause(expected_digest, clause_reference, "outline-user")
        enumeration = service.enumerate_obligations(expected_digest, "outline-user")
        self.assertEqual(expected_digest, installed["package_digest"])
        self.assertEqual(expected_digest, resolved["package_digest"])
        self.assertIn("shall withstand", packet["evidence"][0]["text"])
        self.assertFalse(packet["completeness"]["complete_for_requested_scope"])
        self.assertEqual(0, enumeration["page"]["declared_scope_total"])
        self.assertFalse(enumeration["completeness"]["complete_for_requested_scope"])

    def test_rejects_non_page_source_existing_output_and_tampering(self) -> None:
        output = self.root / "derived"
        compile_derived_outline_pack(self.base_pack, output)
        with self.assertRaises(StandardsForgeError) as caught:
            compile_derived_outline_pack(self.base_pack, output)
        self.assertEqual("compiler_output_exists", caught.exception.code)

        with self.assertRaises(StandardsForgeError) as caught:
            compile_derived_outline_pack(output, self.root / "derived-again")
        self.assertEqual("outline_source_not_page_text", caught.exception.code)

        sidecar = self.base_pack / "sources" / "test.extracted.txt"
        changed = bytearray(sidecar.read_bytes())
        changed[0] = ord("X")
        sidecar.write_bytes(bytes(changed))
        with self.assertRaises(StandardsForgeError) as caught:
            compile_derived_outline_pack(self.base_pack, self.root / "tampered-output")
        self.assertEqual("pack_hash_mismatch", caught.exception.code)

    def test_method_numbered_captions_keep_complete_distinct_source_bound_identity(self) -> None:
        class CaptionFixture(OutlineCompilerTests):
            def _write_base_page_pack(self) -> None:
                self.page_text = (
                    "METHOD 500.6\n"
                    "Table 500.6-I. First qualification limits.\n"
                    "Table 500.6-II. Second qualification limits.\n"
                    "Figure 500.6-1. Test arrangement.\n"
                    "Figure 514.8C-7. Instrument setup.\n"
                    "Table 501.7-                    III. High temperature cycles.\n"
                    "Figure 1-4a. Generalized lifecycle.\n"
                    "Table 500.6-III. TOC leaders ............ 42\n"
                    "Table 500.6-IV. Actual later caption.\n"
                )
                super()._write_base_page_pack()

        fixture = CaptionFixture(methodName="test_compiles_installs_resolves_and_retrieves_unreviewed_outline_offline")
        fixture.setUp()
        try:
            first = compile_derived_outline_pack(fixture.base_pack, fixture.root / "caption-first")
            second = compile_derived_outline_pack(fixture.base_pack, fixture.root / "caption-second")
            self.assertEqual(first["package_digest"], second["package_digest"])
            with open_validated_pack(fixture.root / "caption-first") as pack:
                self.assertTrue(pack.manifest["pack_id"].endswith(".outline-v3"))
                captions = [record for record in pack.records if record["kind"] in {"table", "figure"}]
                references = {record["clause_reference"].split(":")[-1] for record in captions}
                self.assertEqual({
                    "TABLE-500.6-I", "TABLE-500.6-II", "TABLE-500.6-IV", "FIGURE-500.6-1",
                    "FIGURE-514.8C-7", "TABLE-501.7-III", "FIGURE-1-4A",
                }, references)
                self.assertEqual(len(captions), len({record["structure"]["logical_id"] for record in captions}))
                self.assertTrue(all(record["derivation"]["review_status"] == "automated_unreviewed" for record in captions))
                self.assertTrue(all(record["derivation"]["statement_role"] == "unclassified" for record in captions))
                self.assertTrue(all("TOC leaders" not in record["text"] for record in captions))
                for record in captions:
                    span = record["structure"]["source_spans"][0]
                    sidecar = (pack.root / span["text_path"]).read_bytes()
                    self.assertEqual(record["text"], sidecar[span["start_byte"]:span["end_byte"]].decode("utf-8"))
        finally:
            fixture.tearDown()

    def test_caption_parser_rejects_partial_designator_and_toc_leaders(self) -> None:
        self.assertEqual([], _candidate_matches("Table 500.6-I-A. Unknown composite label"))
        self.assertEqual("toc_caption", _candidate_matches("Figure 500.6-1. Instrument setup ......... 42")[0]["type"])
        self.assertEqual([], _candidate_matches("Figure 500.6-1.\n"))
        candidates = _candidate_matches("2  22 (49.5) 32 (71.9) 43 (96.7)\n2.3.1  Equipment shall withstand 15 kPa.\n")
        self.assertEqual(["ambiguous_numbered", "numbered"], [candidate["type"] for candidate in candidates])

    def test_body_part_boundary_resets_method_scope_without_promoting_toc_or_header(self) -> None:
        class PartFixture(OutlineCompilerTests):
            def _write_base_page_pack(self) -> None:
                self.page_text = (
                    "METHOD 528.1\n"
                    "1.1  Previous method purpose.\n"
                    "P  AR T  THREE – WORLD CLIMATIC REGIONS – GUIDANCE\n"
                    "SECTION I - INTRODUCTION\n"
                    "1.1  Purpose. New part purpose.\n"
                    "1.2  Part Three Organization.\n"
                )
                super()._write_base_page_pack()

        fixture = PartFixture(methodName="test_compiles_installs_resolves_and_retrieves_unreviewed_outline_offline")
        fixture.setUp()
        try:
            first = compile_derived_outline_pack(fixture.base_pack, fixture.root / "part-first")
            second = compile_derived_outline_pack(fixture.base_pack, fixture.root / "part-second")
            self.assertEqual(first["package_digest"], second["package_digest"])
            with open_validated_pack(fixture.root / "part-first") as pack:
                self.assertTrue(pack.manifest["pack_id"].endswith(".outline-v3"))
                part = next(record for record in pack.records if record["clause_reference"].endswith(":PART-THREE"))
                self.assertEqual("section", part["kind"])
                self.assertIsNone(part["structure"]["parent_logical_id"])
                clauses = [record for record in pack.records if record["kind"] == "clause"]
                self.assertEqual(3, len(clauses))
                self.assertEqual(1, sum(":METHOD-528.1:" in record["clause_reference"] for record in clauses))
                part_clauses = [record for record in clauses if ":PART-THREE:" in record["clause_reference"]]
                self.assertEqual(2, len(part_clauses))
                self.assertTrue(all(record["structure"]["parent_logical_id"] == part["structure"]["logical_id"] for record in part_clauses))
                self.assertTrue(all(record["derivation"]["review_status"] == "automated_unreviewed" for record in part_clauses))
        finally:
            fixture.tearDown()

        self.assertFalse(any(item["type"] == "part" for item in _candidate_matches("P ART  THREE\n1.1  Purpose.\n")))
        self.assertFalse(any(item["type"] == "part" for item in _candidate_matches("PART THREE – WORLD CLIMATIC REGIONS\nCONTENTS\n")))
        self.assertFalse(any(item["type"] == "part" for item in _candidate_matches("PART THREE – WORLD CLIMATIC REGIONS\n1.1  Purpose ........ 5\n")))


if __name__ == "__main__":
    unittest.main()
