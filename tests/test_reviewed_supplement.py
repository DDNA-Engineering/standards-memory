"""Builder tests for the agent-reviewed semantic supplement, using fictional fixtures only."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_reviewed_supplement as builder  # noqa: E402
import test_corpus_compiler as corpus_fixtures  # noqa: E402
from standardsforge.corpus_compiler import compile_mil_std_corpus  # noqa: E402
from standardsforge.coverage_ledger import digest  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.pack import open_validated_pack  # noqa: E402
from standardsforge.structure_compiler import compile_reviewed_page_section  # noqa: E402

TEXTS = {
    "201": "4.1 The operator shall record each result unless the test is waived.",
    "202": "5.2 Records shall be retained as described in FICT-STD-201 and FICT-STD-999.",
}
REVIEW = {"reviewer_id": "fixture-agent", "reviewer_type": "agent", "reviewed_at": "2026-10-09T00:00:00Z", "method": "fixture review",
          "tool": {"name": "fixture", "version": "1", "configuration_sha256": None}, "unresolved_issues": [],
          "attestation": "extraction_review_not_project_applicability_or_approval"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReviewedSupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="standardsforge-supplement-test-")
        root = Path(cls.temp.name)
        sources = root / "sources"
        records = []
        for ident, text in TEXTS.items():
            pdf = sources / ident / f"Revision_A__2026-01-01__{ident}.pdf"
            pdf.parent.mkdir(parents=True)
            corpus_fixtures.CorpusCompilerTests._write_pdf(pdf, text)
            data = pdf.read_bytes()
            records.append({
                "ident_number": ident, "document_id": f"FICT-STD-{ident}A", "title": f"Fictional standard {ident}",
                "document_date": "2026-01-01", "detail_url": f"https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number={ident}",
                "status": "A", "fsc_area": "TEST",
                "current_components": [{"acquisition_status": "downloaded", "description": "Revision A", "distribution_statement": "A",
                                        "document_date": "2026-01-01", "token": f"9{ident}.{ident}", "local_path": f"{ident}/{pdf.name}",
                                        "sha256": _sha(data), "byte_length": len(data), "page_count": 1}],
            })
        manifest = sources / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": "0.1.0", "catalog_id": "dla-active-mil-std-current", "records": records}), encoding="utf-8")
        cls.corpus = root / "corpus"
        compile_mil_std_corpus(manifest, sources, cls.corpus)
        cls.template = root / "template"
        cls._write_reviews(cls.template)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    @classmethod
    def _write_reviews(cls, directory: Path) -> None:
        corpus_index = json.loads((cls.corpus / "corpus.json").read_text(encoding="utf-8"))
        entries = {entry["ident_number"]: entry for entry in corpus_index["entries"]}
        directory.mkdir(parents=True)
        packs, selectors = [], {}
        for ident, slug, needle, statement, qualifiers in (
            ("201", "fict-std-201-recording", "4.1 The operator shall record each result unless the test is waived.",
             {"subject": "The operator", "action": "record each result", "modality": "shall", "polarity": "affirmative"},
             [{"kind": "exception", "exact_text": "unless the test is waived."}]),
            ("202", "fict-std-202-retention", "5.2 Records shall be retained as described in FICT-STD-201 and FICT-STD-999.",
             {"subject": "Records", "action": "be retained", "modality": "shall", "polarity": "affirmative"}, []),
        ):
            entry = entries[ident]
            with open_validated_pack(cls.corpus / entry["archive_path"]) as pack:
                record = pack.records[0]
                page = record["text"].encode("utf-8")
                start = page.index(needle.encode("utf-8"))
                pdf_sha = record["source"]["sha256"]
                pack_digest, edition = pack.package_digest, pack.manifest["edition_id"]
            span = {"physical_page": 1, "page_text_sha256": _sha(page), "start_byte": start, "end_byte": start + len(needle.encode("utf-8"))}
            semantics = {"schema_version": "0.1.0", "content_role": "requirement_candidate", "normativity": "normative",
                         "statement": {**statement, "exact_text": needle, "span_indices": [0]},
                         "qualifiers": [{**q, "span_indices": [0]} for q in qualifiers], "quantities": [], "unresolved_issues": [],
                         "project_applicability": "not_decided"}
            lid = needle.split()[0]
            annotation = {"schema_version": "0.6.0", "document_id": entry["document_id"], "edition_id": edition, "source_pdf_sha256": pdf_sha,
                          "source_page_pack_digest": pack_digest, "compiler": {"name": "verified_page_pack", "version": "0.1.0"},
                          "extraction_mode": "verified_page_text", "text_encoding": "UTF-8",
                          "offset_convention": "half_open_utf8_byte_offsets_per_physical_page", "review": REVIEW,
                          "nodes": [{"logical_id": lid, "kind": "clause", "ordinal": 1, "clause_reference": lid, "heading": f"{lid} fictional",
                                     "statement_role": "obligation", "exact_text": needle, "content_sha256": _sha(needle.encode()),
                                     "source_spans": [span], "derivation": {"method": "fixture", "review_status": "agent_reviewed"},
                                     "semantics": semantics}],
                          "relationships": [], "unsupported_regions": []}
            (directory / slug).mkdir()
            annotation_path = directory / slug / "annotations.json"
            annotation_path.write_text(json.dumps(annotation, indent=1), encoding="utf-8")
            with tempfile.TemporaryDirectory() as scratch:
                compiled = compile_reviewed_page_section(cls.corpus / entry["archive_path"], annotation_path, Path(scratch) / "pack")
                with open_validated_pack(Path(scratch) / "pack") as reviewed:
                    reviewed_record = reviewed.records[0]
            record_id = reviewed_record["record_id"]
            selectors[ident] = {"package_digest": compiled["package_digest"], "edition_id": edition, "record_id": record_id,
                                "quote_sha256": reviewed_record["source"]["quote_sha256"], "text": needle}
            suite = {"suite_id": f"{slug}-fixture", "qualification": "bounded_real_document_regression",
                     "package_digest": compiled["package_digest"], "edition_id": edition,
                     "cases": [{"case_id": f"review-{lid}", "operation": "get_clause", "request": {"record_id": record_id},
                                "expected": {"record_ids": [record_id], "forbidden_record_ids": [],
                                             "citations": [{"record_id": record_id, "page": 1, "source_sha256": pdf_sha,
                                                            "quote_sha256": _sha(needle.encode())}],
                                             "critical_facts": [qualifiers[0]["exact_text"]] if qualifiers else [needle],
                                             "complete_for_requested_scope": False,
                                             "semantic_assertions": [{"record_id": record_id, "content_role": "requirement_candidate",
                                                                      "statement": semantics["statement"], "qualifiers": semantics["qualifiers"]}]}}]}
            suite_document = {"suite": suite, "review": {"kind": "agent", "identity": "fixture self-review", "reviewed_at": "2026-10-09T00:00:00Z",
                                                         "suite_sha256": digest(suite)}}
            suite_path = directory / f"{slug}-suite.json"
            suite_path.write_text(json.dumps(suite_document, indent=1), encoding="utf-8")
            packs.append({"slug": slug, "content_class": "public_government_standard", "annotations": f"{slug}/annotations.json",
                          "annotations_sha256": _sha(annotation_path.read_bytes()), "suite": suite_path.name,
                          "suite_sha256": _sha(suite_path.read_bytes()), "expected_package_digest": compiled["package_digest"],
                          "source": {"ident_number": ident, "document_id": entry["document_id"], "edition_id": edition, "package_digest": pack_digest,
                                     "archive_path": entry["archive_path"], "archive_sha256": entry["archive_sha256"], "source_pdf_sha256": pdf_sha}})
        bindings = []
        text = selectors["202"]["text"].encode("utf-8")
        for binding_id, citation, target in (("resolved", b"FICT-STD-201", selectors["201"]), ("unresolved", b"FICT-STD-999", None)):
            start = text.index(citation)
            binding = {"binding_id": binding_id, "source": {k: selectors["202"][k] for k in ("package_digest", "edition_id", "record_id", "quote_sha256")},
                       "reference": {"start_byte": start, "end_byte": start + len(citation), "exact_text": citation.decode()},
                       "target": None if target is None else {k: target[k] for k in ("package_digest", "edition_id", "record_id", "quote_sha256")},
                       "status": "resolved" if target else "unresolved",
                       "edition_basis": "reviewer_selected_navigation_edition" if target else "unresolved",
                       "rationale": "Fictional fixture navigation only."}
            binding["review"] = {"kind": "agent", "identity": "fixture self-review", "reviewed_at": "2026-10-09T00:00:00Z",
                                 "binding_sha256": digest(binding)}
            bindings.append(binding)
        body = {"binding_set_id": "fixture", "bindings": bindings, "scope": "reviewed_navigation_only", "project_applicability": "not_decided"}
        bindings_path = directory / "reference-bindings.json"
        bindings_path.write_text(json.dumps({"schema_version": "0.1.0", "binding_set": body, "binding_set_sha256": digest(body)}), encoding="utf-8")
        index = {"schema_version": "0.1.0", "batch_id": "fixture-review",
                 "review": {"kind": "agent", "independence_claim": "self_review", "attestation": "extraction_review_not_project_applicability_or_approval"},
                 "corpus": {k: corpus_index[k] for k in ("corpus_id", "acquisition_manifest_sha256", "compiler_version")},
                 "packs": packs, "reference_bindings": {"path": "reference-bindings.json", "sha256": _sha(bindings_path.read_bytes())}}
        (directory / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")

    def setUp(self) -> None:
        self.work = tempfile.TemporaryDirectory(prefix="standardsforge-supplement-case-")
        self.root = Path(self.work.name)
        self.reviews = self.root / "reviews"
        shutil.copytree(self.template, self.reviews)
        self.corpus = self.root / "corpus"
        shutil.copytree(type(self).corpus, self.corpus)

    def tearDown(self) -> None:
        self.work.cleanup()

    def build(self, name: str = "out") -> Path:
        output = self.root / name
        builder.build_supplement(self.corpus, output, index_path=self.reviews / "index.json")
        return output

    def index(self) -> dict:
        return json.loads((self.reviews / "index.json").read_text(encoding="utf-8"))

    def write_index(self, index: dict) -> None:
        (self.reviews / "index.json").write_text(json.dumps(index), encoding="utf-8")

    def assert_fails(self, code: str) -> None:
        with self.assertRaises(StandardsForgeError) as caught:
            self.build("failed")
        self.assertEqual(code, caught.exception.code)
        self.assertFalse((self.root / "failed").exists())
        self.assertEqual([], [p.name for p in self.root.iterdir() if p.name.startswith(".reviewed-supplement-")])

    def test_builds_exact_layout_and_is_byte_reproducible(self) -> None:
        first, second = self.build("first"), self.build("second")
        supplement = json.loads((first / "supplement.json").read_text(encoding="utf-8"))
        self.assertEqual({"agent"}, {supplement["review"]["kind"]})
        self.assertEqual("self_review", supplement["review"]["independence_claim"])
        expected = {"supplement.json", "reference-bindings.json"}
        for pack in supplement["packs"]:
            slug = pack["slug"]
            expected |= {f"packs/{slug}.zip", f"policies/{slug}.json", f"qualification/{slug}-suite.json",
                         f"qualification/{slug}-run.json", f"qualification/{slug}-coverage.json"}
            self.assertEqual(0, pack["real_suite_metrics"]["failed_cases"])
            policy = json.loads((first / pack["policy"]).read_text(encoding="utf-8"))
            self.assertEqual([pack["pack_id"]], policy["allowed_pack_ids"])
            self.assertEqual("local-user", policy["principal_id"])
            with open_validated_pack(first / pack["pack"]) as reviewed:
                self.assertEqual(pack["package_digest"], reviewed.package_digest)
        files = {p.relative_to(first).as_posix() for p in first.rglob("*") if p.is_file()}
        self.assertEqual(expected, files)
        for relative in sorted(files):
            self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes(), relative)
        self.assertEqual({"bindings": 2, "followed": 2, "resolved": 1, "unresolved": 1, "source_records": 1},
                         {k: supplement["reference_bindings"][k] for k in ("bindings", "followed", "resolved", "unresolved", "source_records")})
        self.assertEqual(_sha((first / "reference-bindings.json").read_bytes()), supplement["reference_bindings"]["sha256"])

    def test_existing_output_is_never_overwritten(self) -> None:
        (self.root / "failed").mkdir()
        with self.assertRaises(StandardsForgeError) as caught:
            self.build("failed")
        self.assertEqual("supplement_output_exists", caught.exception.code)

    def test_changed_source_archive_fails_closed(self) -> None:
        archive = self.corpus / self.index()["packs"][0]["source"]["archive_path"]
        archive.write_bytes(archive.read_bytes() + b"\0")
        self.assert_fails("supplement_source_changed")

    def test_stale_source_digest_pin_fails_closed(self) -> None:
        index = self.index()
        index["packs"][0]["source"]["archive_sha256"] = "0" * 64
        self.write_index(index)
        self.assert_fails("supplement_source_changed")

    def test_changed_corpus_identity_fails_closed(self) -> None:
        index = self.index()
        index["corpus"]["acquisition_manifest_sha256"] = "1" * 64
        self.write_index(index)
        self.assert_fails("supplement_source_changed")

    def test_missing_source_archive_fails_closed(self) -> None:
        (self.corpus / self.index()["packs"][1]["source"]["archive_path"]).unlink()
        self.assert_fails("supplement_source_missing")

    def test_tampered_annotation_fails_closed(self) -> None:
        path = self.reviews / self.index()["packs"][0]["annotations"]
        annotation = json.loads(path.read_text(encoding="utf-8"))
        annotation["nodes"][0]["semantics"]["qualifiers"] = []
        path.write_text(json.dumps(annotation), encoding="utf-8")
        self.assert_fails("supplement_review_stale")

    def test_repinned_annotation_change_is_stale_against_reviewed_digest(self) -> None:
        index = self.index()
        path = self.reviews / index["packs"][0]["annotations"]
        annotation = json.loads(path.read_text(encoding="utf-8"))
        annotation["nodes"][0]["semantics"]["qualifiers"] = []
        path.write_text(json.dumps(annotation), encoding="utf-8")
        index["packs"][0]["annotations_sha256"] = _sha(path.read_bytes())
        self.write_index(index)
        self.assert_fails("supplement_review_stale")

    def test_failing_suite_fails_closed(self) -> None:
        index = self.index()
        path = self.reviews / index["packs"][0]["suite"]
        document = json.loads(path.read_text(encoding="utf-8"))
        document["suite"]["cases"][0]["expected"]["critical_facts"] = ["unless the operator objects"]
        document["review"]["suite_sha256"] = digest(document["suite"])
        path.write_text(json.dumps(document), encoding="utf-8")
        index["packs"][0]["suite_sha256"] = _sha(path.read_bytes())
        self.write_index(index)
        self.assert_fails("supplement_suite_failed")

    def test_dropped_exception_in_suite_expectation_fails_closed(self) -> None:
        index = self.index()
        path = self.reviews / index["packs"][0]["suite"]
        document = json.loads(path.read_text(encoding="utf-8"))
        document["suite"]["cases"][0]["expected"]["semantic_assertions"][0]["qualifiers"] = []
        document["review"]["suite_sha256"] = digest(document["suite"])
        path.write_text(json.dumps(document), encoding="utf-8")
        index["packs"][0]["suite_sha256"] = _sha(path.read_bytes())
        self.write_index(index)
        self.assert_fails("supplement_suite_failed")

    def test_wrong_edition_suite_fails_closed(self) -> None:
        index = self.index()
        path = self.reviews / index["packs"][0]["suite"]
        document = json.loads(path.read_text(encoding="utf-8"))
        document["suite"]["edition_id"] = "fictional:wrong-edition"
        document["review"]["suite_sha256"] = digest(document["suite"])
        path.write_text(json.dumps(document), encoding="utf-8")
        index["packs"][0]["suite_sha256"] = _sha(path.read_bytes())
        self.write_index(index)
        self.assert_fails("supplement_review_stale")

    def test_tampered_suite_or_bindings_fail_closed(self) -> None:
        index = self.index()
        suite = self.reviews / index["packs"][1]["suite"]
        suite.write_bytes(suite.read_bytes() + b"\n")
        self.assert_fails("supplement_review_stale")
        shutil.rmtree(self.reviews)
        shutil.copytree(self.template, self.reviews)
        bindings = self.reviews / "reference-bindings.json"
        bindings.write_bytes(bindings.read_bytes() + b"\n")
        self.assert_fails("supplement_review_stale")

    def test_binding_to_package_outside_supplement_fails_closed(self) -> None:
        index = self.index()
        path = self.reviews / "reference-bindings.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        binding = document["binding_set"]["bindings"][0]
        binding["target"]["package_digest"] = "2" * 64
        binding["review"]["binding_sha256"] = digest({k: v for k, v in binding.items() if k != "review"})
        document["binding_set_sha256"] = digest(document["binding_set"])
        path.write_text(json.dumps(document), encoding="utf-8")
        index["reference_bindings"]["sha256"] = _sha(path.read_bytes())
        self.write_index(index)
        self.assert_fails("supplement_review_stale")

    def test_index_must_declare_agent_self_review_and_valid_slugs(self) -> None:
        for mutate in (lambda i: i["review"].update(independence_claim="separate_reviewer"),
                       lambda i: i["review"].update(kind="human"),
                       lambda i: i["packs"][0].update(slug="Bad_Slug"),
                       lambda i: i["packs"][1].update(slug=i["packs"][0]["slug"])):
            index = self.index()
            mutate(index)
            self.write_index(index)
            with self.subTest(index=index["review"]):
                self.assert_fails("invalid_supplement_index")


class CommittedReviewInputTests(unittest.TestCase):
    """The committed agent-review inputs stay pinned and mutually consistent (no corpus needed)."""

    def test_committed_index_pins_annotations_suites_and_bindings(self) -> None:
        from standardsforge.real_benchmark import validate_suite
        from standardsforge.reference_bindings import validate_bindings
        from standardsforge.structure_compiler import load_structure_annotations

        index, base = builder.load_index(builder.DEFAULT_INDEX)
        self.assertEqual({"kind": "agent", "independence_claim": "self_review",
                          "attestation": "extraction_review_not_project_applicability_or_approval"}, index["review"])
        packages = {}
        for pack in index["packs"]:
            annotation_path = base / pack["annotations"]
            suite_path = (base / pack["suite"]).resolve()
            self.assertEqual(pack["annotations_sha256"], _sha(annotation_path.read_bytes()), pack["slug"])
            self.assertEqual(pack["suite_sha256"], _sha(suite_path.read_bytes()), pack["slug"])
            self.assertEqual(ROOT / "benchmarks" / "real" / f"{pack['slug']}.json", suite_path)
            annotation = load_structure_annotations(annotation_path)
            self.assertEqual("agent", annotation["review"]["reviewer_type"])
            self.assertEqual("extraction_review_not_project_applicability_or_approval", annotation["review"]["attestation"])
            self.assertTrue(all(node["derivation"]["review_status"] == "agent_reviewed" for node in annotation["nodes"]))
            for key in ("edition_id", "source_pdf_sha256"):
                self.assertEqual(pack["source"][key], annotation[key])
            self.assertEqual(pack["source"]["package_digest"], annotation["source_page_pack_digest"])
            suite = validate_suite(json.loads(suite_path.read_text(encoding="utf-8")))
            self.assertEqual(pack["expected_package_digest"], suite["package_digest"])
            self.assertEqual(pack["source"]["edition_id"], suite["edition_id"])
            packages[suite["package_digest"]] = suite["edition_id"]
        bindings_path = base / index["reference_bindings"]["path"]
        self.assertEqual(index["reference_bindings"]["sha256"], _sha(bindings_path.read_bytes()))
        body = validate_bindings(json.loads(bindings_path.read_text(encoding="utf-8")))
        for binding in body["bindings"]:
            self.assertEqual("agent", binding["review"]["kind"])
            for selector in [binding["source"]] + ([binding["target"]] if binding["target"] else []):
                self.assertEqual(packages[selector["package_digest"]], selector["edition_id"])
            if binding["status"] == "unresolved":
                self.assertIsNone(binding["target"])


if __name__ == "__main__":
    unittest.main()
