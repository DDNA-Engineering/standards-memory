from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest

import test_structure_compiler as fixtures
from standardsforge.compiler import compile_pdf_to_pack
from standardsforge.coverage_ledger import digest, link_semantic_evidence, page_ledger
from standardsforge.errors import StandardsForgeError
from standardsforge.pack import validate_pack_directory
from standardsforge.policy import write_pack_policy
from standardsforge.service import StandardsForgeService
from standardsforge.structure_compiler import compile_reviewed_page_section
from standardsforge.transcription import compile_page_transcription


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StructureCompilerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.base = self.root / "base"
        compile_pdf_to_pack(self.fixture.catalog_path, self.fixture.document["document_id"], self.fixture.sources, self.base)
        pack = validate_pack_directory(self.base)
        self.rasters = self.root / "rasters"
        self.rasters.mkdir()
        # This tiny synthetic raster qualifies identity checking, not OCR accuracy.
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jFh8AAAAASUVORK5CYII=")
        pages = []
        for n in (1, 2):
            (self.rasters / f"page-{n:04d}.png").write_bytes(png)
            pages.append({"physical_page": n, "text": f"Reviewed synthetic page {n}. Keep the exception.",
                          "raster_sha256": hashlib.sha256(png).hexdigest(), "review_notes": "Synthetic identity fixture, not visual qualification."})
        body = {"source_package_digest": pack.package_digest, "source_pdf_sha256": self.fixture.document["sha256"],
                "renderer": "synthetic fixture", "text_method": "explicit synthetic transcription", "pages": pages}
        self.document = {"schema_version": "0.1.0", "transcription": body,
                         "review": {"transcription_sha256": digest(body), "reviewer_type": "agent", "reviewer_id": "test",
                                    "reviewed_at": "2026-10-08T00:00:00Z", "attestation": "Synthetic fixture only."}}
        self.path = self.root / "review.json"

    def compile(self, document=None, name="transcribed"):
        self.path.write_text(json.dumps(document or self.document), encoding="utf-8")
        return compile_page_transcription(self.base, self.path, self.rasters, self.root / name)

    def test_deterministic_recovery_preserves_pdf_and_review_boundary(self):
        first = self.compile()
        self.assertEqual(first["package_digest"], self.compile(name="replay")["package_digest"])
        pack = validate_pack_directory(self.root / "transcribed")
        self.assertEqual((pack.root / "sources/original.pdf").read_bytes(), self.fixture.pdf_path.read_bytes())
        self.assertEqual(len(pack.records), 2)
        self.assertEqual(pack.manifest["edition_id"], self.fixture.document["edition_id"])
        self.assertEqual(pack.records[0]["derivation"]["statement_role"], "unclassified")
        ledger = page_ledger(pack)["ledger"]
        self.assertEqual(ledger["pages_without_text"], 0)
        self.assertEqual(ledger["semantic_qualification"], "not_established")
        self.assertEqual(ledger["pages"][0]["visual_review"], "agent_reviewed")

    def test_reviewed_blank_page_preserves_evidence_without_inventing_text(self):
        document = copy.deepcopy(self.document)
        document["schema_version"] = "0.2.0"
        for page in document["transcription"]["pages"]:
            page["disposition"] = "transcribed_text"
        blank = document["transcription"]["pages"][1]
        blank.update(text="", disposition="reviewed_blank", review_notes="Reviewed raster is blank; no source text.")
        document["review"]["transcription_sha256"] = digest(document["transcription"])
        from jsonschema import Draft202012Validator
        schema = json.loads((fixtures.ROOT / "contracts/page-transcription.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        validator.validate(self.document)
        validator.validate(document)
        result = self.compile(document)
        self.assertEqual(result["physical_pages"], 2)
        self.assertEqual(result["package_digest"], self.compile(document, name="blank-replay")["package_digest"])
        pack = validate_pack_directory(self.root / "transcribed")
        self.assertEqual(len(pack.records), 1)
        self.assertEqual((pack.root / "sources/page-0002.txt").read_bytes(), b"")
        self.assertEqual((pack.root / "evidence/page-0002.png").read_bytes(), (self.rasters / "page-0002.png").read_bytes())
        ledger = page_ledger(pack)["ledger"]
        self.assertEqual(ledger["physical_pages"], 2)
        self.assertEqual(ledger["pages_without_text"], 1)
        self.assertEqual(ledger["pages"][1]["extraction_status"], "reviewed_blank")
        self.assertEqual(ledger["pages"][1]["visual_review"], "agent_reviewed")
        self.assertIsNone(ledger["pages"][1]["record_id"])
        self.assertEqual(ledger["pages"][1]["text_bytes"], 0)
        self.assertEqual(ledger["semantic_qualification"], "not_established")
        policy = self.root / "blank-policy.json"
        write_pack_policy(pack.root, policy, "test", pack.rights["content_class"])
        service = StandardsForgeService(self.root / "memory.db", self.root / "objects")
        service.install_pack(pack.root, policy)
        packet = StandardsForgeService.open_read_only(self.root / "memory.db", self.root / "objects").get_clause(
            package_digest=pack.package_digest, record_id=pack.records[0]["record_id"], principal_id="test")
        self.assertEqual([r["text"] for r in packet["evidence"]], [pack.records[0]["text"]])
        for name, mutate, resign in [
            ("invented", lambda p: p.update(text="Blank page"), True),
            ("whitespace", lambda p: p.update(text="\n"), True),
            ("missing-disposition", lambda p: p.pop("disposition"), True),
            ("unreviewed-empty", lambda p: p.update(disposition="transcribed_text"), True),
            ("stale-blank-review", lambda p: p.update(review_notes="Changed review"), False),
        ]:
            with self.subTest(name=name):
                invalid = copy.deepcopy(document)
                mutate(invalid["transcription"]["pages"][1])
                if resign:
                    invalid["review"]["transcription_sha256"] = digest(invalid["transcription"])
                    self.assertTrue(list(validator.iter_errors(invalid)))
                with self.assertRaises(StandardsForgeError):
                    self.compile(invalid, name=name)
                self.assertFalse((self.root / name).exists())

    def test_stale_text_missing_page_wrong_source_and_changed_raster_fail_before_activation(self):
        for name, mutate, resign in [
            ("stale", lambda d: d["transcription"]["pages"][0].update(text="Changed"), False),
            ("missing", lambda d: d["transcription"]["pages"].pop(), True),
            ("wrong-source", lambda d: d["transcription"].update(source_pdf_sha256="0" * 64), True),
            ("duplicate", lambda d: d["transcription"]["pages"][1].update(physical_page=1), True),
        ]:
            with self.subTest(name=name):
                document = copy.deepcopy(self.document)
                mutate(document)
                if resign:
                    document["review"]["transcription_sha256"] = digest(document["transcription"])
                with self.assertRaises(StandardsForgeError):
                    self.compile(document, name=name)
                self.assertFalse((self.root / name).exists())
        (self.rasters / "page-0002.png").write_bytes(b"changed")
        with self.assertRaisesRegex(StandardsForgeError, "Rendered evidence differs"):
            self.compile()
        self.assertFalse((self.root / "transcribed").exists())

    def test_direct_review_links_exact_transcription_and_rejects_stale_spans(self):
        self.compile()
        pack = validate_pack_directory(self.root / "transcribed")
        text = pack.records[0]["text"]
        annotations = {"schema_version": "0.6.0", "document_id": pack.manifest["identifier"], "edition_id": pack.manifest["edition_id"],
            "source_pdf_sha256": self.fixture.document["sha256"], "source_page_pack_digest": pack.package_digest,
            "compiler": {"name": "verified_page_pack", "version": "0.1.0"}, "extraction_mode": "verified_page_text",
            "text_encoding": "UTF-8", "offset_convention": "half_open_utf8_byte_offsets_per_physical_page",
            "review": {"reviewer_id": "test", "reviewer_type": "agent", "reviewed_at": "2026-10-08T00:00:00Z", "method": "fixture",
                "tool": {"name": "test", "version": "1", "configuration_sha256": None}, "unresolved_issues": [],
                "attestation": "extraction_review_not_project_applicability_or_approval"},
            "nodes": [{"logical_id": "test", "kind": "clause", "ordinal": 1, "clause_reference": "1", "heading": "Fixture", "statement_role": "informative",
                "exact_text": text, "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "source_spans": [{"physical_page": 1, "page_text_sha256": hashlib.sha256(text.encode()).hexdigest(), "start_byte": 0, "end_byte": len(text.encode())}],
                "derivation": {"method": "fixture", "review_status": "agent_reviewed"},
                "semantics": {"schema_version": "0.1.0", "content_role": "prose", "normativity": "informative", "statement": None,
                    "qualifiers": [], "quantities": [], "unresolved_issues": [], "project_applicability": "not_decided"}}],
            "relationships": [], "unsupported_regions": []}
        path = self.root / "annotations.json"
        path.write_text(json.dumps(annotations), encoding="utf-8")
        compile_reviewed_page_section(pack.root, path, self.root / "structured")
        structured = validate_pack_directory(self.root / "structured")
        self.assertTrue((structured.root / "derivations/source-transcription/evidence/page-0001.png").exists())
        ledger = link_semantic_evidence(pack, structured, page_ledger(pack))["ledger"]
        self.assertEqual(ledger["pages"][0]["semantically_linked_bytes"], len(text.encode()))
        self.assertEqual(ledger["pages"][1]["semantically_linked_bytes"], 0)
        self.assertEqual(ledger["semantic_qualification"], "not_established")
        annotations["nodes"][0]["source_spans"][0]["page_text_sha256"] = "0" * 64
        path.write_text(json.dumps(annotations), encoding="utf-8")
        with self.assertRaisesRegex(StandardsForgeError, "page-text digest changed"):
            compile_reviewed_page_section(pack.root, path, self.root / "invalid")
        with self.assertRaisesRegex(StandardsForgeError, "source pack"):
            link_semantic_evidence(validate_pack_directory(self.base), structured, page_ledger(pack))
