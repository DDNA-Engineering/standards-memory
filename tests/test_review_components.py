import copy
import hashlib
import json
from pathlib import Path
import unittest

import test_corpus_compiler as fixtures
from standardsforge.corpus_compiler import compile_mil_std_corpus
from standardsforge.errors import StandardsForgeError
from standardsforge.pack import open_validated_pack, validate_pack_directory
from standardsforge.structure_compiler import compile_reviewed_page_section


class ReviewComponentTests(unittest.TestCase):
    def test_exact_component_selection_with_overlapping_page_numbers(self):
        fixture = fixtures.CorpusCompilerTests()
        fixture.setUp(); self.addCleanup(fixture.tearDown)
        second = fixture.sources / "101/notice.pdf"
        fixture._write_pdf(second, "A separate notice on physical page one.")
        component = fixture.manifest["records"][0]["current_components"][0]
        component.update(acquisition_status="downloaded", distribution_statement="A", local_path="101/notice.pdf",
                         sha256=hashlib.sha256(second.read_bytes()).hexdigest(), byte_length=second.stat().st_size, page_count=1)
        fixture.manifest_path.write_text(json.dumps(fixture.manifest), encoding="utf-8")
        output = fixture.root / "corpus"
        compile_mil_std_corpus(fixture.manifest_path, fixture.sources, output)
        entry = json.loads((output / "corpus.json").read_text(encoding="utf-8"))["entries"][0]
        with open_validated_pack(output / entry["archive_path"]) as pack:
            selected = next(r for r in pack.records if r["source"]["sha256"] == component["sha256"])
            text = selected["text"]
            derivation = {"method": "Synthetic component fixture.", "review_status": "agent_reviewed"}
            annotation = {"schema_version": "0.6.0", "document_id": pack.manifest["identifier"], "edition_id": pack.manifest["edition_id"],
                "source_pdf_sha256": component["sha256"], "source_page_pack_digest": pack.package_digest,
                "compiler": {"name": "verified_page_pack", "version": "0.1.0"}, "extraction_mode": "verified_page_text",
                "text_encoding": "UTF-8", "offset_convention": "half_open_utf8_byte_offsets_per_physical_page",
                "review": {"reviewer_id": "test", "reviewer_type": "agent", "reviewed_at": "2026-10-08", "method": "fixture",
                    "tool": {"name": "test", "version": "1", "configuration_sha256": None}, "unresolved_issues": [],
                    "attestation": "extraction_review_not_project_applicability_or_approval"},
                "nodes": [{"logical_id": "notice", "kind": "clause", "ordinal": 1, "clause_reference": "notice", "heading": "Selected notice",
                    "statement_role": "informative", "exact_text": text, "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "source_spans": [{"physical_page": 1, "page_text_sha256": hashlib.sha256(text.encode()).hexdigest(), "start_byte": 0, "end_byte": len(text.encode())}],
                    "derivation": derivation}], "relationships": [], "unsupported_regions": []}
            path = fixture.root / "annotations.json"; path.write_text(json.dumps(annotation), encoding="utf-8")
            compile_reviewed_page_section(pack.root, path, fixture.root / "reviewed")
            reviewed = validate_pack_directory(fixture.root / "reviewed")
            self.assertEqual(text, reviewed.records[0]["text"])
            self.assertEqual(component["sha256"], reviewed.records[0]["source"]["sha256"])
            self.assertEqual(pack.manifest["edition_id"], reviewed.manifest["edition_id"])
            report = json.loads((reviewed.root / "structure-report.json").read_text(encoding="utf-8"))
            self.assertIn("other_components_remain_unreviewed", report["limitations"]["component_scope"])
            for pin in ("0" * 64, next(r["source"]["sha256"] for r in pack.records if r["source"]["sha256"] != component["sha256"])):
                bad = copy.deepcopy(annotation); bad["source_pdf_sha256"] = pin
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(StandardsForgeError):
                    compile_reviewed_page_section(pack.root, path, fixture.root / "invalid")
