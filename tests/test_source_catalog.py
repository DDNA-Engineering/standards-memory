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
from standardsforge.source_catalog import load_source_catalog, verify_source_set  # noqa: E402


class SourceCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-source-test-")
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.pdf_bytes = b"%PDF-1.7\nsynthetic fixture\n%%EOF\n"
        self.filename = "MIL-STD-TEST.pdf"
        (self.sources / self.filename).write_bytes(self.pdf_bytes)
        self.manifest = self.root / "catalog.json"
        self.catalog = {
            "schema_version": "0.1.0",
            "catalog_id": "test.catalog",
            "title": "Test catalog",
            "purpose": "Exercise the offline verifier.",
            "selection_basis": "Synthetic unit-test fixture.",
            "documents": [
                {
                    "document_id": "MIL-STD-TEST",
                    "document_family_id": "test:mil-std-test",
                    "edition_id": "test:mil-std-test:a:2026-01-01",
                    "title": "Synthetic test document",
                    "publisher": "Test publisher",
                    "status": "Active",
                    "revision": "A",
                    "change": 0,
                    "document_date": "2026-01-01",
                    "distribution_statement": "A",
                    "detail_url": "https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=1",
                    "source_origin": "official_dla_assist_quick_search",
                    "local_filename": self.filename,
                    "sha256": hashlib.sha256(self.pdf_bytes).hexdigest(),
                    "byte_length": len(self.pdf_bytes),
                    "page_count": 1,
                    "retrieved_at": "2026-09-21",
                    "rights": {
                        "access_basis": "Synthetic test metadata.",
                        "repository_redistribution": "not_asserted",
                    },
                }
            ],
        }
        self._write_catalog()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_catalog(self) -> None:
        self.manifest.write_text(json.dumps(self.catalog), encoding="utf-8")

    def test_verifies_closed_source_set_without_network_access(self) -> None:
        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")):
            result = verify_source_set(self.manifest, self.sources)
        self.assertEqual("test.catalog", result["catalog_id"])
        self.assertEqual(1, result["document_count"])
        self.assertEqual(len(self.pdf_bytes), result["total_bytes"])
        self.assertEqual("not_used", result["network_access"])
        self.assertEqual(
            ["directory_closure", "regular_file", "pdf_signature", "byte_length", "sha256"],
            result["documents"][0]["verified_dimensions"],
        )

    def test_rejects_tampered_source(self) -> None:
        (self.sources / self.filename).write_bytes(self.pdf_bytes[:-1] + b"x")
        with self.assertRaises(StandardsForgeError) as caught:
            verify_source_set(self.manifest, self.sources)
        self.assertEqual("source_hash_mismatch", caught.exception.code)

    def test_rejects_path_traversal_and_unknown_fields(self) -> None:
        self.catalog["documents"][0]["local_filename"] = "../MIL-STD-TEST.pdf"
        self._write_catalog()
        with self.assertRaises(StandardsForgeError) as caught:
            load_source_catalog(self.manifest)
        self.assertEqual("invalid_source_path", caught.exception.code)

        self.catalog["documents"][0]["local_filename"] = self.filename
        self.catalog["documents"][0]["download_command"] = "not allowed"
        self._write_catalog()
        with self.assertRaises(StandardsForgeError) as caught:
            load_source_catalog(self.manifest)
        self.assertEqual("invalid_source_catalog", caught.exception.code)

    def test_rejects_unexpected_files_and_non_pdf_content(self) -> None:
        (self.sources / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        with self.assertRaises(StandardsForgeError) as caught:
            verify_source_set(self.manifest, self.sources)
        self.assertEqual("source_set_mismatch", caught.exception.code)

        (self.sources / "unexpected.txt").unlink()
        (self.sources / self.filename).write_bytes(b"not a pdf")
        self.catalog["documents"][0]["byte_length"] = len(b"not a pdf")
        self.catalog["documents"][0]["sha256"] = hashlib.sha256(b"not a pdf").hexdigest()
        self._write_catalog()
        with self.assertRaises(StandardsForgeError) as caught:
            verify_source_set(self.manifest, self.sources)
        self.assertEqual("invalid_source_format", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
