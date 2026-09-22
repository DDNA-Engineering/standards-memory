from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema.validators import validator_for
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.corpus_compiler import (  # noqa: E402
    compile_mil_std_corpus,
    install_compiled_corpus,
    write_corpus_policy,
)
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.pack import open_validated_pack  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402
import standardsforge.store as store_module  # noqa: E402
import standardsforge.corpus_compiler as corpus_compiler_module  # noqa: E402


class CorpusCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report_schema = json.loads(
            (ROOT / "contracts" / "corpus-extraction-report.schema.json").read_text(encoding="utf-8")
        )
        validator_for(cls.report_schema).check_schema(cls.report_schema)
        cls.report_validator = validator_for(cls.report_schema)(cls.report_schema)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-corpus-test-")
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        (self.sources / "101").mkdir(parents=True)
        self.pdf = self.sources / "101" / "Revision_A__2026-01-01__1001.pdf"
        self._write_pdf(self.pdf, "Public current component evidence.")
        pdf_bytes = self.pdf.read_bytes()
        self.manifest_path = self.sources / "manifest.json"
        self.manifest = {
            "schema_version": "0.1.0",
            "catalog_id": "dla-active-mil-std-current",
            "records": [
                {
                    "ident_number": "101",
                    "document_id": "MIL-STD-TESTA(1) NOT 1",
                    "title": "Synthetic mixed composition",
                    "document_date": "2026-02-01",
                    "detail_url": "https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=101",
                    "status": "A",
                    "fsc_area": "TEST",
                    "current_components": [
                        {
                            "acquisition_status": "restricted_distribution",
                            "description": "Revision A Notice 1",
                            "distribution_statement": "D",
                            "document_date": "2026-02-01",
                            "token": "1002.101",
                        },
                        {
                            "acquisition_status": "downloaded",
                            "description": "Revision A",
                            "distribution_statement": "A",
                            "document_date": "2026-01-01",
                            "token": "1001.101",
                            "local_path": "101/Revision_A__2026-01-01__1001.pdf",
                            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                            "byte_length": len(pdf_bytes),
                            "page_count": 1,
                        },
                    ],
                },
                {
                    "ident_number": "102",
                    "document_id": "MIL-STD-RESTRICTED",
                    "title": "Synthetic restricted-only composition",
                    "document_date": "2026-01-01",
                    "detail_url": "https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=102",
                    "status": "A",
                    "fsc_area": "TEST",
                    "current_components": [
                        {
                            "acquisition_status": "restricted_distribution",
                            "description": "Revision A",
                            "distribution_statement": "D",
                            "document_date": "2026-01-01",
                            "token": "1003.102",
                        }
                    ],
                },
            ],
        }
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_pdf(path: Path, text: str, *, password: str | None = None) -> None:
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
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
        if password is not None:
            writer.encrypt(password)
        with path.open("wb") as output:
            writer.write(output)

    def test_compiles_resumes_installs_and_retrieves_mixed_composition(self) -> None:
        output = self.root / "compiled-corpus"
        real_corpus_replace = corpus_compiler_module.os.replace
        compilation_activation_attempts = 0

        def transient_compilation_activation(source: str | Path, destination: str | Path) -> None:
            nonlocal compilation_activation_attempts
            if Path(source).name.startswith(".standardsforge-corpus-compile-") and compilation_activation_attempts == 0:
                compilation_activation_attempts += 1
                raise PermissionError(5, "synthetic OneDrive sharing lock")
            real_corpus_replace(source, destination)

        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")), patch.object(
            corpus_compiler_module.os, "replace", side_effect=transient_compilation_activation
        ):
            first = compile_mil_std_corpus(self.manifest_path, self.sources, output)
            index_bytes = (output / "corpus.json").read_bytes()
            archive = next((output / "packs").glob("*.zip"))
            archive_bytes = archive.read_bytes()
            second = compile_mil_std_corpus(self.manifest_path, self.sources, output)

        self.assertEqual("complete", first["status"])
        self.assertEqual(1, first["compiled_record_count"])
        self.assertEqual(1, first["restricted_only_record_count"])
        self.assertEqual(1, compilation_activation_attempts)
        self.assertEqual(first, second)
        self.assertEqual(index_bytes, (output / "corpus.json").read_bytes())
        self.assertEqual(archive_bytes, archive.read_bytes())

        with open_validated_pack(archive) as pack:
            self.assertTrue(pack.manifest["coverage"]["edition_composition"].startswith("partial_"))
            composition = json.loads((pack.root / "component-manifest.json").read_text(encoding="utf-8"))
            report = json.loads((pack.root / "extraction-report.json").read_text(encoding="utf-8"))
            self.report_validator.validate(report)
            self.assertFalse(composition["complete"])
            self.assertEqual(["1002.101", "1001.101"], [item["token"] for item in composition["components"]])
            self.assertEqual(1, len(pack.records))
            self.assertEqual("unclassified", pack.records[0]["derivation"]["statement_role"])
            self.assertTrue(pack.records[0]["clause_reference"].startswith("pdf-component:1001-101-"))
            clause_reference = pack.records[0]["clause_reference"]
            expected_digest = pack.package_digest

        policy = self.root / "policy.json"
        policy_result = write_corpus_policy(output / "corpus.json", policy, "corpus-test-user")
        real_replace = store_module.os.replace
        activation_attempts = 0

        def transient_activation(source: str | Path, destination: str | Path) -> None:
            nonlocal activation_attempts
            if Path(source).name.startswith(".candidate-") and activation_attempts == 0:
                activation_attempts += 1
                raise PermissionError(5, "synthetic sharing lock")
            real_replace(source, destination)

        with patch.object(store_module.os, "replace", side_effect=transient_activation):
            install_result = install_compiled_corpus(
                output / "corpus.json",
                policy,
                self.root / "memory.db",
                self.root / "objects",
            )
        service = StandardsForgeService(self.root / "memory.db", self.root / "objects")
        digest = expected_digest
        resolved = service.resolve_document("MIL-STD-TESTA(1) NOT 1", "corpus-test-user")
        packet = service.get_clause(digest, clause_reference, "corpus-test-user")
        self.assertEqual(1, policy_result["allowed_pack_count"])
        self.assertEqual(1, install_result["installed_pack_count"])
        self.assertEqual(0, install_result["revoked_obsolete_pack_count"])
        self.assertEqual(1, activation_attempts)
        self.assertEqual(expected_digest, digest)
        self.assertEqual(digest, resolved["package_digest"])
        self.assertIn("Public current component evidence", packet["evidence"][0]["text"])
        self.assertTrue(
            packet["completeness"]["declared_pack_coverage"]["edition_composition"].startswith("partial_")
        )
        self.assertEqual(
            "incomplete",
            packet["completeness"]["dimensions"]["source_interpretation"]["status"],
        )

    def test_accepts_empty_password_pdf_and_rejects_corrupt_checkpoint_archive(self) -> None:
        self._write_pdf(self.pdf, "Empty password evidence.", password="")
        pdf_bytes = self.pdf.read_bytes()
        component = self.manifest["records"][0]["current_components"][1]
        component.update(
            {
                "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                "byte_length": len(pdf_bytes),
            }
        )
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        output = self.root / "encrypted-corpus"
        compile_mil_std_corpus(self.manifest_path, self.sources, output)
        archive = next((output / "packs").glob("*.zip"))
        with open_validated_pack(archive) as pack:
            report = json.loads((pack.root / "extraction-report.json").read_text(encoding="utf-8"))
            self.report_validator.validate(report)
            self.assertEqual("empty_password_decrypted_for_extraction", report["components"][0]["encryption_status"])

        archive.write_bytes(archive.read_bytes() + b"corrupt")
        with self.assertRaises(StandardsForgeError) as caught:
            compile_mil_std_corpus(self.manifest_path, self.sources, output)
        self.assertEqual("corpus_compile_incomplete", caught.exception.code)
        index = json.loads((output / "corpus.json").read_text(encoding="utf-8"))
        self.assertEqual(1, index["summary"]["failed_record_count"])
        self.assertEqual(0, index["summary"]["compiled_record_count"])

    def test_rejects_restricted_distribution_relabelled_as_downloaded(self) -> None:
        public = self.manifest["records"][0]["current_components"][1]
        restricted = self.manifest["records"][0]["current_components"][0]
        restricted.update(
            {
                "acquisition_status": "downloaded",
                "local_path": public["local_path"],
                "sha256": public["sha256"],
                "byte_length": public["byte_length"],
                "page_count": public["page_count"],
            }
        )
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

        with self.assertRaises(StandardsForgeError) as caught:
            compile_mil_std_corpus(self.manifest_path, self.sources, self.root / "restricted-corpus")
        self.assertEqual("acquisition_verification_failed", caught.exception.code)
        self.assertEqual(
            "downloaded_non_public_distribution",
            caught.exception.details["errors"][0]["error"],
        )

    def test_parser_failure_forces_incomplete_corpus_instead_of_no_text(self) -> None:
        output = self.root / "parser-failure-corpus"
        failure = StandardsForgeError(
            "parser_worker_terminated",
            "The parser worker terminated without a valid result.",
            {"termination_reason": "resource_limit_or_crash"},
        )
        with patch.object(corpus_compiler_module, "isolated_pdf_pages", side_effect=failure):
            with self.assertRaises(StandardsForgeError) as caught:
                compile_mil_std_corpus(self.manifest_path, self.sources, output)
        self.assertEqual("corpus_compile_incomplete", caught.exception.code)
        index = json.loads((output / "corpus.json").read_text(encoding="utf-8"))
        self.assertEqual("incomplete", index["summary"]["status"])
        self.assertEqual(1, index["summary"]["failed_record_count"])
        self.assertEqual(0, index["summary"]["compiled_record_count"])
        self.assertEqual("parser_worker_terminated", index["failures"][0]["code"])
        self.assertEqual(0, index["summary"]["pages_without_text_records"])

    def test_rejects_stale_valid_archive_during_uncheckpointed_resume(self) -> None:
        output = self.root / "stale-corpus"
        compile_mil_std_corpus(self.manifest_path, self.sources, output)
        (output / "corpus.json").unlink()

        with patch.object(corpus_compiler_module, "CORPUS_COMPILER_VERSION", "99.0.0"):
            with self.assertRaises(StandardsForgeError) as caught:
                compile_mil_std_corpus(self.manifest_path, self.sources, output)
        self.assertEqual("corpus_compile_incomplete", caught.exception.code)
        index = json.loads((output / "corpus.json").read_text(encoding="utf-8"))
        self.assertEqual("corpus_archive_mismatch", index["failures"][0]["code"])

    def test_install_reconciles_obsolete_grant_for_same_pack_identity(self) -> None:
        first_output = self.root / "first-corpus"
        compile_mil_std_corpus(self.manifest_path, self.sources, first_output)
        first_index = json.loads((first_output / "corpus.json").read_text(encoding="utf-8"))
        first_entry = first_index["entries"][0]
        first_policy = self.root / "first-policy.json"
        write_corpus_policy(first_output / "corpus.json", first_policy, "corpus-test-user")
        database = self.root / "memory.db"
        objects = self.root / "objects"
        install_compiled_corpus(first_output / "corpus.json", first_policy, database, objects)

        second_output = self.root / "second-corpus"
        with patch.object(corpus_compiler_module, "COMPILER_VERSION", "99.0.0"), patch.object(
            corpus_compiler_module, "CORPUS_COMPILER_VERSION", "99.0.0"
        ):
            compile_mil_std_corpus(self.manifest_path, self.sources, second_output)
            second_index = json.loads((second_output / "corpus.json").read_text(encoding="utf-8"))
            second_entry = second_index["entries"][0]
            second_policy = self.root / "second-policy.json"
            write_corpus_policy(second_output / "corpus.json", second_policy, "corpus-test-user")
            result = install_compiled_corpus(second_output / "corpus.json", second_policy, database, objects)

        self.assertNotEqual(first_entry["package_digest"], second_entry["package_digest"])
        self.assertEqual(1, result["revoked_obsolete_pack_count"])
        active = store_module.LocalStore(database, objects).active_grants_for_pack_ids(
            "corpus-test-user", [first_entry["pack_id"]]
        )
        self.assertEqual([second_entry["package_digest"]], [grant["package_digest"] for grant in active])


if __name__ == "__main__":
    unittest.main()
