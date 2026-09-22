from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from jsonschema.validators import validator_for


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.compiler import compile_pdf_to_pack  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.pack import validate_pack_directory  # noqa: E402
from standardsforge.pack import open_validated_pack, write_pack_archive  # noqa: E402
import standardsforge.service as service_module  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402


class PDFCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-compiler-test-")
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.pdf_path = self.sources / "MIL-STD-TESTA.pdf"
        self._write_pdf(self.pdf_path)
        pdf_bytes = self.pdf_path.read_bytes()
        self.catalog_path = self.root / "catalog.json"
        self.catalog = {
            "schema_version": "0.1.0",
            "catalog_id": "test.compiler",
            "title": "Compiler test catalog",
            "purpose": "Exercise deterministic PDF compilation.",
            "selection_basis": "Synthetic test fixture.",
            "documents": [
                {
                    "document_id": "MIL-STD-TEST",
                    "document_family_id": "test:mil-std-test",
                    "edition_id": "test:mil-std-test:a:2026-01-01",
                    "title": "Synthetic compiler test",
                    "publisher": "Test publisher",
                    "status": "Active",
                    "revision": "A",
                    "change": 0,
                    "document_date": "2026-01-01",
                    "distribution_statement": "A",
                    "detail_url": "https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=1",
                    "source_origin": "official_dla_assist_quick_search",
                    "local_filename": self.pdf_path.name,
                    "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                    "byte_length": len(pdf_bytes),
                    "page_count": 2,
                    "retrieved_at": "2026-09-21",
                    "rights": {
                        "access_basis": "Synthetic test metadata.",
                        "repository_redistribution": "not_asserted",
                    },
                }
            ],
        }
        self.catalog_path.write_text(json.dumps(self.catalog), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_pdf(path: Path, password: str | None = None) -> None:
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_reference = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_reference}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 72 720 Td (Synthetic environmental requirement.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.add_blank_page(width=612, height=792)
        if password is not None:
            writer.encrypt(password)
        with path.open("wb") as output:
            writer.write(output)

    def test_compiles_installs_and_retrieves_pdf_backed_page_offline(self) -> None:
        output = self.root / "compiled"
        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")):
            result = compile_pdf_to_pack(self.catalog_path, "MIL-STD-TEST", self.sources, output)
            report = json.loads((output / "extraction-report.json").read_text(encoding="utf-8"))
            report_schema = json.loads(
                (ROOT / "contracts" / "extraction-report.schema.json").read_text(encoding="utf-8")
            )
            validator_for(report_schema)(report_schema).validate(report)
            pack = validate_pack_directory(output)
            policy_path = self.root / "policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "policy_version": "0.1.0",
                        "policy_id": "compiler-test-policy",
                        "principal_id": "local-compiler-test",
                        "allow_admin_install": True,
                        "allow_serve": True,
                        "allowed_pack_ids": [pack.manifest["pack_id"]],
                        "allowed_content_classes": ["public_government_standard"],
                    }
                ),
                encoding="utf-8",
            )
            service = StandardsForgeService(self.root / "memory.db", self.root / "objects")
            digest = service.install_pack(output, policy_path)["package_digest"]
            packet = service.get_clause(digest, "pdf-page:0001", "local-compiler-test")
            with patch.object(
                service_module,
                "_decode_utf8",
                side_effect=AssertionError("page-offset retrieval decoded the full text sidecar"),
            ):
                offset_packet = service.get_clause(digest, "pdf-page:0001", "local-compiler-test")

        self.assertEqual(result["package_digest"], digest)
        self.assertEqual(packet, offset_packet)
        self.assertEqual(2, result["physical_pages"])
        self.assertEqual(1, result["page_records"])
        self.assertEqual(1, result["pages_without_text_records"])
        self.assertIn("Synthetic environmental requirement", packet["evidence"][0]["text"])
        self.assertTrue(packet["evidence"][0]["citation"]["source_path"].endswith(".pdf"))
        self.assertTrue(packet["evidence"][0]["citation"]["text_path"].endswith(".txt"))
        self.assertTrue(packet["evidence"][0]["source_checks"]["extracted_text_digest_verified"])
        self.assertEqual("unreviewed", packet["evidence"][0]["derivation"]["review_status"])
        self.assertIn(
            "page_records_only_not_clause_or_obligation_complete",
            packet["completeness"]["declared_pack_coverage"]["enumeration_traversal"],
        )
        self.assertEqual("not_interpreted", result["limitations"]["tables"])
        self.assertEqual(self.catalog["documents"][0]["sha256"], hashlib.sha256((output / "sources" / self.pdf_path.name).read_bytes()).hexdigest())
        page_record = json.loads((output / "records.json").read_text(encoding="utf-8"))["records"][0]
        self.assertNotIn("text", page_record)
        self.assertEqual(
            page_record["source"]["text_start_byte"],
            packet["evidence"][0]["citation"]["text_start_byte"],
        )
        self.assertEqual(
            page_record["source"]["text_end_byte"],
            packet["evidence"][0]["citation"]["text_end_byte"],
        )
        sidecar = (output / page_record["source"]["text_path"]).read_bytes()
        quote = sidecar[page_record["source"]["text_start_byte"]:page_record["source"]["text_end_byte"]]
        self.assertEqual(packet["evidence"][0]["text"].encode("utf-8"), quote)
        self.assertEqual(page_record["source"]["quote_sha256"], hashlib.sha256(quote).hexdigest())

        object_path = Path(service.store.authorized_package("local-compiler-test", digest)["object_path"])
        stored_pdf = object_path / page_record["source"]["path"]
        original_pdf = stored_pdf.read_bytes()
        stored_pdf.write_bytes(original_pdf + b"tampered")
        with self.assertRaises(StandardsForgeError) as caught:
            service.get_clause(digest, "pdf-page:0001", "local-compiler-test")
        self.assertEqual("source_integrity_failure", caught.exception.code)
        stored_pdf.write_bytes(original_pdf)
        stored_sidecar = object_path / page_record["source"]["text_path"]
        stored_sidecar.write_bytes(stored_sidecar.read_bytes() + b"tampered")
        with self.assertRaises(StandardsForgeError) as caught:
            service.get_clause(digest, "pdf-page:0001", "local-compiler-test")
        self.assertEqual("source_integrity_failure", caught.exception.code)

    def test_rejects_page_offsets_outside_the_text_sidecar(self) -> None:
        output = self.root / "invalid-offsets"
        compile_pdf_to_pack(self.catalog_path, "MIL-STD-TEST", self.sources, output)

        records_path = output / "records.json"
        records = json.loads(records_path.read_text(encoding="utf-8"))
        records["records"][0]["source"]["text_end_byte"] = 10**9
        records_bytes = json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")
        records_path.write_bytes(records_bytes)

        inventory_path = output / "inventory.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        records_entry = next(item for item in inventory["files"] if item["path"] == "records.json")
        records_entry.update({"sha256": hashlib.sha256(records_bytes).hexdigest(), "bytes": len(records_bytes)})
        inventory_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")

        with self.assertRaises(StandardsForgeError) as caught:
            validate_pack_directory(output)
        self.assertEqual("invalid_record", caught.exception.code)

    def test_offset_backed_pack_has_deterministic_compressed_transport(self) -> None:
        output = self.root / "compressed-source"
        compile_pdf_to_pack(self.catalog_path, "MIL-STD-TEST", self.sources, output)
        first = self.root / "first.zip"
        second = self.root / "second.zip"
        first_result = write_pack_archive(output, first)
        second_result = write_pack_archive(output, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with open_validated_pack(first) as archived:
            self.assertEqual(first_result["package_digest"], archived.package_digest)
            self.assertIn("Synthetic environmental requirement", archived.records[0]["text"])
        self.assertEqual(first.stat().st_size, first_result["archive_bytes"])

    def test_rejects_encrypted_pdf_and_existing_output(self) -> None:
        encrypted_path = self.sources / self.pdf_path.name
        self._write_pdf(encrypted_path, password="test-only")
        pdf_bytes = encrypted_path.read_bytes()
        self.catalog["documents"][0]["sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
        self.catalog["documents"][0]["byte_length"] = len(pdf_bytes)
        self.catalog_path.write_text(json.dumps(self.catalog), encoding="utf-8")
        with self.assertRaises(StandardsForgeError) as caught:
            compile_pdf_to_pack(self.catalog_path, "MIL-STD-TEST", self.sources, self.root / "encrypted-output")
        self.assertEqual("encrypted_pdf", caught.exception.code)

        self._write_pdf(encrypted_path)
        pdf_bytes = encrypted_path.read_bytes()
        self.catalog["documents"][0]["sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
        self.catalog["documents"][0]["byte_length"] = len(pdf_bytes)
        self.catalog_path.write_text(json.dumps(self.catalog), encoding="utf-8")
        existing = self.root / "existing"
        existing.mkdir()
        with self.assertRaises(StandardsForgeError) as caught:
            compile_pdf_to_pack(self.catalog_path, "MIL-STD-TEST", self.sources, existing)
        self.assertEqual("compiler_output_exists", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
