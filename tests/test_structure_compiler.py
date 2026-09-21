from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.compiler import PYPDF_VERSION, _normalize_page_text  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.pack import validate_pack_directory  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402
from standardsforge.structure_compiler import compile_structured_pdf_section  # noqa: E402


class StructureCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-structure-test-")
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.pdf_path = self.sources / "MIL-STD-STRUCTA.pdf"
        self._write_pdf(self.pdf_path)
        pdf_bytes = self.pdf_path.read_bytes()
        self.document = {
            "document_id": "MIL-STD-STRUCT",
            "document_family_id": "test:mil-std-struct",
            "edition_id": "test:mil-std-struct:a:2026-01-01",
            "title": "Synthetic structural compiler test",
            "publisher": "Test publisher",
            "status": "Active",
            "revision": "A",
            "change": 0,
            "document_date": "2026-01-01",
            "distribution_statement": "A",
            "detail_url": "https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=2",
            "source_origin": "official_dla_assist_quick_search",
            "local_filename": self.pdf_path.name,
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "byte_length": len(pdf_bytes),
            "page_count": 1,
            "retrieved_at": "2026-09-21",
            "rights": {
                "access_basis": "Synthetic test metadata.",
                "repository_redistribution": "not_asserted",
            },
        }
        self.catalog_path = self.root / "catalog.json"
        self.catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "catalog_id": "test.structure-compiler",
                    "title": "Structure compiler test catalog",
                    "purpose": "Exercise reviewed structural compilation.",
                    "selection_basis": "Synthetic test fixture.",
                    "documents": [self.document],
                }
            ),
            encoding="utf-8",
        )
        page_text = _normalize_page_text(PdfReader(self.pdf_path, strict=True).pages[0].extract_text() or "")
        self.page_bytes = page_text.encode("utf-8")
        self.page_sha256 = hashlib.sha256(self.page_bytes).hexdigest()
        self.multibyte_start = self.page_bytes.index("°".encode("utf-8"))
        self.annotations_path = self.root / "annotations.json"
        self.annotations = self._annotations()
        self.annotations_path.write_text(json.dumps(self.annotations), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_pdf(path: Path) -> None:
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
        stream.set_data(b"BT /F1 12 Tf 72 720 Td (Synthetic environmental requirement. Temperature 25\\260C.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        with path.open("wb") as output:
            writer.write(output)

    def _span(self, exact_text: str) -> dict:
        quote = exact_text.encode("utf-8")
        start = self.page_bytes.index(quote)
        return {
            "physical_page": 1,
            "page_text_sha256": self.page_sha256,
            "start_byte": start,
            "end_byte": start + len(quote),
        }

    def _node(
        self,
        logical_id: str,
        kind: str,
        clause_reference: str,
        heading: str,
        exact_text: str,
        ordinal: int,
        parent: str | None = None,
    ) -> dict:
        node = {
            "logical_id": logical_id,
            "kind": kind,
            "ordinal": ordinal,
            "clause_reference": clause_reference,
            "heading": heading,
            "statement_role": "unclassified",
            "exact_text": exact_text,
            "source_spans": [self._span(exact_text)],
            "content_sha256": hashlib.sha256(exact_text.encode("utf-8")).hexdigest(),
            "derivation": {"method": "synthetic_agent_annotation", "review_status": "agent_reviewed"},
        }
        if parent is not None:
            node["parent_logical_id"] = parent
        return node

    def _annotations(self) -> dict:
        parent_text = "Synthetic"
        child_text = "environmental requirement."
        return {
            "schema_version": "0.1.0",
            "document_id": self.document["document_id"],
            "edition_id": self.document["edition_id"],
            "source_pdf_sha256": self.document["sha256"],
            "compiler": {"name": "pypdf", "version": PYPDF_VERSION},
            "extraction_mode": "simple",
            "text_encoding": "UTF-8",
            "offset_convention": "half_open_utf8_byte_offsets_per_physical_page",
            "review": {"reviewer_id": "synthetic-agent", "reviewer_type": "agent", "reviewed_at": "2026-09-21T12:00:00Z"},
            "nodes": [
                self._node("test:section:1", "section", "1", "Synthetic section", parent_text, 1),
                self._node("test:section:1:clause:a", "clause", "1.a", "Requirement", child_text, 1, "test:section:1"),
            ],
            "relationships": [
                {
                    "source_logical_id": "test:section:1:clause:a",
                    "relationship_type": "governed_by",
                    "target_status": "resolved",
                    "target_logical_id": "test:section:1",
                    "required": True,
                    "derivation": {"method": "synthetic_agent_annotation", "review_status": "agent_reviewed"},
                    "evidence_spans": [self._span(child_text)],
                }
            ],
            "unsupported_regions": [
                {
                    "region_id": "outside-selected-scope",
                    "reason_code": "outside_selected_scope",
                    "description": "Only two reviewed nodes are in scope.",
                    "source_spans": [self._span("requirement")],
                    "derivation": {"method": "synthetic_agent_annotation", "review_status": "agent_reviewed"},
                }
            ],
        }

    def test_compiles_installs_and_retrieves_source_spanned_tree(self) -> None:
        output = self.root / "structured"
        result = compile_structured_pdf_section(
            self.catalog_path,
            self.document["document_id"],
            self.sources,
            self.annotations_path,
            output,
        )
        pack = validate_pack_directory(output)
        policy_path = self.root / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "policy_version": "0.1.0",
                    "policy_id": "structure-test-policy",
                    "principal_id": "structure-test-user",
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
        packet = service.get_clause(digest, "1.a", "structure-test-user")

        self.assertEqual(result["package_digest"], digest)
        self.assertEqual(["1.a", "1"], [record["clause_reference"] for record in packet["evidence"]])
        child = packet["evidence"][0]
        self.assertEqual("test:section:1:clause:a", child["structure"]["logical_id"])
        self.assertEqual("test:section:1", child["structure"]["parent_logical_id"])
        self.assertEqual(hashlib.sha256(child["text"].encode("utf-8")).hexdigest(), child["structure"]["content_sha256"])
        self.assertEqual("governed_by", child["structure"]["relationships"][0]["relationship"])
        self.assertTrue(child["structure"]["relationships"][0]["required"])
        self.assertEqual("partial_reviewed_structural_section_only", packet["completeness"]["parsed_source_coverage"])
        self.assertFalse(packet["completeness"]["complete_for_requested_scope"])

        compact = service.get_clause(
            digest, "1.a", "structure-test-user", response_profile="compact_evidence_v1"
        )
        compact_child = compact["evidence"]["records"][0]
        self.assertEqual(child["record_id"], compact_child["record_id"])
        self.assertEqual(child["text"], compact_child["text"])
        self.assertEqual(child["structure"], compact_child["structure"])
        self.assertEqual(packet["completeness"], compact["completeness"])
        compact_source = compact["evidence"]["source_files"][0]
        self.assertEqual(child["citation"]["source_sha256"], compact_source["sha256"])
        self.assertEqual(child["citation"]["text_sha256"], compact_source["text_sha256"])
        self.assertTrue(compact_source["source_checks"]["source_digest_verified"])
        self.assertTrue(compact_source["source_checks"]["extracted_text_digest_verified"])
        self.assertTrue((output / "derivations" / "structure-annotations.json").is_file())
        self.assertTrue((output / "structure-report.json").is_file())

    def test_rejects_required_structural_relationship_missing_dependency_projection(self) -> None:
        output = self.root / "inconsistent-required-edge"
        compile_structured_pdf_section(
            self.catalog_path,
            self.document["document_id"],
            self.sources,
            self.annotations_path,
            output,
        )

        records_path = output / "records.json"
        records = json.loads(records_path.read_text(encoding="utf-8"))
        child = next(item for item in records["records"] if item["clause_reference"] == "1.a")
        self.assertEqual(1, len(child["structure"]["relationships"]))
        self.assertTrue(child["structure"]["relationships"][0]["required"])
        child["dependencies"] = []
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

    def test_retrieval_rechecks_relationship_only_sidecar_spans(self) -> None:
        output = self.root / "relationship-sidecar-pack"
        compile_structured_pdf_section(
            self.catalog_path,
            self.document["document_id"],
            self.sources,
            self.annotations_path,
            output,
        )

        relation_sidecar = "sources/pages/relationship-only.txt"
        original_sidecar = output / "sources" / "pages" / "physical-0001.txt"
        relation_bytes = original_sidecar.read_bytes()
        (output / relation_sidecar).write_bytes(relation_bytes)

        records_path = output / "records.json"
        records = json.loads(records_path.read_text(encoding="utf-8"))
        child = next(item for item in records["records"] if item["clause_reference"] == "1.a")
        relationship_span = child["structure"]["relationships"][0]["evidence_spans"][0]
        relationship_span["text_path"] = relation_sidecar
        records_path.write_text(json.dumps(records), encoding="utf-8")

        inventory_path = output / "inventory.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        record_entry = next(item for item in inventory["files"] if item["path"] == "records.json")
        record_bytes = records_path.read_bytes()
        record_entry.update({"sha256": hashlib.sha256(record_bytes).hexdigest(), "bytes": len(record_bytes)})
        inventory["files"].append(
            {
                "path": relation_sidecar,
                "sha256": hashlib.sha256(relation_bytes).hexdigest(),
                "bytes": len(relation_bytes),
            }
        )
        inventory["files"].sort(key=lambda item: item["path"])
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        validated = validate_pack_directory(output)
        policy_path = self.root / "relationship-sidecar-policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "policy_version": "0.1.0",
                    "policy_id": "relationship-sidecar-test-policy",
                    "principal_id": "relationship-sidecar-user",
                    "allow_admin_install": True,
                    "allow_serve": True,
                    "allowed_pack_ids": [validated.manifest["pack_id"]],
                    "allowed_content_classes": ["public_government_standard"],
                }
            ),
            encoding="utf-8",
        )
        service = StandardsForgeService(self.root / "relationship-memory.db", self.root / "relationship-objects")
        digest = service.install_pack(output, policy_path)["package_digest"]
        stored_sidecar = service.store.object_root / digest / relation_sidecar
        self.assertEqual("1.a", service.get_clause(digest, "1.a", "relationship-sidecar-user")["evidence"][0]["clause_reference"])
        stored_sidecar.write_bytes(relation_bytes + b" tampered")

        with self.assertRaises(StandardsForgeError) as caught:
            service.get_clause(digest, "1.a", "relationship-sidecar-user")
        self.assertEqual("source_integrity_failure", caught.exception.code)

    def test_rejects_changed_page_text_binding_and_span(self) -> None:
        changed_hash = json.loads(json.dumps(self.annotations))
        changed_hash["nodes"][0]["source_spans"][0]["page_text_sha256"] = "0" * 64
        self.annotations_path.write_text(json.dumps(changed_hash), encoding="utf-8")
        with self.assertRaises(StandardsForgeError) as caught:
            compile_structured_pdf_section(
                self.catalog_path,
                self.document["document_id"],
                self.sources,
                self.annotations_path,
                self.root / "changed-hash",
            )
        self.assertEqual("structure_span_mismatch", caught.exception.code)

        split_utf8 = json.loads(json.dumps(self.annotations))
        split_utf8["nodes"][0]["source_spans"][0]["start_byte"] = self.multibyte_start + 1
        split_utf8["nodes"][0]["source_spans"][0]["end_byte"] = self.multibyte_start + 2
        self.annotations_path.write_text(json.dumps(split_utf8), encoding="utf-8")
        with self.assertRaises(StandardsForgeError) as caught:
            compile_structured_pdf_section(
                self.catalog_path,
                self.document["document_id"],
                self.sources,
                self.annotations_path,
                self.root / "split-utf8",
            )
        self.assertEqual("invalid_structure_annotations", caught.exception.code)

        changed_span = json.loads(json.dumps(self.annotations))
        changed_span["nodes"][1]["source_spans"][0]["start_byte"] += 1
        self.annotations_path.write_text(json.dumps(changed_span), encoding="utf-8")
        with self.assertRaises(StandardsForgeError) as caught:
            compile_structured_pdf_section(
                self.catalog_path,
                self.document["document_id"],
                self.sources,
                self.annotations_path,
                self.root / "changed-span",
            )
        self.assertEqual("structure_span_mismatch", caught.exception.code)

    def test_rejects_unresolved_graph_and_false_review_provenance(self) -> None:
        cases: list[tuple[str, dict]] = []

        unresolved_parent = json.loads(json.dumps(self.annotations))
        unresolved_parent["nodes"][1]["parent_logical_id"] = "missing-parent"
        cases.append(("unresolved-parent", unresolved_parent))

        parent_cycle = json.loads(json.dumps(self.annotations))
        parent_cycle["nodes"][0]["parent_logical_id"] = parent_cycle["nodes"][1]["logical_id"]
        cases.append(("parent-cycle", parent_cycle))

        unresolved_target = json.loads(json.dumps(self.annotations))
        unresolved_target["relationships"][0]["target_logical_id"] = "missing-target"
        cases.append(("unresolved-target", unresolved_target))

        required_out_of_scope = json.loads(json.dumps(self.annotations))
        relationship = required_out_of_scope["relationships"][0]
        relationship["target_status"] = "out_of_scope"
        relationship["target_reference"] = "outside selected scope"
        relationship.pop("target_logical_id")
        cases.append(("required-out-of-scope", required_out_of_scope))

        false_human_review = json.loads(json.dumps(self.annotations))
        false_human_review["nodes"][0]["derivation"]["review_status"] = "human_reviewed"
        cases.append(("false-human-review", false_human_review))

        for name, annotations in cases:
            with self.subTest(name=name):
                self.annotations_path.write_text(json.dumps(annotations), encoding="utf-8")
                with self.assertRaises(StandardsForgeError) as caught:
                    compile_structured_pdf_section(
                        self.catalog_path,
                        self.document["document_id"],
                        self.sources,
                        self.annotations_path,
                        self.root / name,
                    )
                self.assertEqual("invalid_structure_annotations", caught.exception.code)

        mismatched_source = json.loads(json.dumps(self.annotations))
        mismatched_source["source_pdf_sha256"] = "0" * 64
        self.annotations_path.write_text(json.dumps(mismatched_source), encoding="utf-8")
        with self.assertRaises(StandardsForgeError) as caught:
            compile_structured_pdf_section(
                self.catalog_path,
                self.document["document_id"],
                self.sources,
                self.annotations_path,
                self.root / "mismatched-source",
            )
        self.assertEqual("structure_identity_mismatch", caught.exception.code)

if __name__ == "__main__":
    unittest.main()
