from __future__ import annotations

import copy
import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from standardsforge.service import StandardsForgeService

SCRIPT = ROOT / "plugins/standardsforge/skills/standardsforge/scripts/render_evidence.py"
SPEC = importlib.util.spec_from_file_location("evidence_reader", SCRIPT)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


class ReaderDocument(HTMLParser):
    def __init__(self, document):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.quotes = []
        self.in_quote = False
        self.audit = False
        self.visible = []
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "blockquote":
            self.in_quote = True
            self.quotes.append("")
        if tag == "details":
            self.audit = True

    def handle_endtag(self, tag):
        if tag == "blockquote":
            self.in_quote = False
        if tag == "details":
            self.audit = False

    def handle_data(self, data):
        if self.in_quote:
            self.quotes[-1] += data
        if not self.audit:
            self.visible.append(data)


class EvidenceReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        service = StandardsForgeService(root / "memory.db", root / "objects")
        installed = service.install_pack(ROOT / "examples/packs/fictional-adapter-v1", ROOT / "examples/policies/local-synthetic.json")
        self.packet = service.get_clause(installed["package_digest"], principal_id="local-user", record_id="clause-4.2.1")
        self.service = service

    def test_preserves_real_query_passages_context_and_optional_audit(self):
        before = json.dumps(self.packet, sort_keys=True)
        parsed = ReaderDocument(reader.render({"ok": True, "result": self.packet}))
        self.assertGreater(len(parsed.quotes), 1)
        self.assertEqual([record["text"] for record in self.packet["evidence"]], parsed.quotes)
        self.assertNotIn(self.packet["package"]["package_digest"], "".join(parsed.visible))
        self.assertIn("Governing context", "".join(parsed.visible))
        self.assertTrue(all("open" not in attrs for tag, attrs in parsed.tags if tag == "details"))
        self.assertEqual(before, json.dumps(self.packet, sort_keys=True))

    def test_source_and_title_markup_cannot_become_active_content(self):
        packet = copy.deepcopy(self.packet)
        payload = '<script>alert(1)</script><img src="https://example.test/leak" onerror="alert(2)">'
        record = packet["evidence"][0]
        record["text"] = payload
        record["citation"]["quote_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
        packet["limitations"].append(payload)
        parsed = ReaderDocument(reader.render(packet, payload))
        self.assertEqual(payload, parsed.quotes[0])
        self.assertFalse({"script", "img", "iframe", "form"}.intersection(tag for tag, _ in parsed.tags))
        self.assertFalse(any(key.startswith("on") for _, attrs in parsed.tags for key in attrs))

    def test_multiple_packets_and_context_queries_keep_every_passage(self):
        context = self.service.build_context(self.packet["package"]["package_digest"], ["4.2.1", "4.2.2"], "local-user")
        parsed = ReaderDocument(reader.render([self.packet, {"ok": True, "result": context}]))
        self.assertEqual([r["text"] for p in (self.packet, context) for r in p["evidence"]], parsed.quotes)

    def test_incomplete_and_unknown_coverage_remains_visible(self):
        self.packet["completeness"]["complete_for_requested_scope"] = False
        self.packet["completeness"]["dimensions"] = {"required_dependencies": {"identification_status": "unknown"}}
        self.packet["limitations"] = ["A governing footnote has not been resolved."]
        visible = "".join(ReaderDocument(reader.render(self.packet)).visible)
        for text in ("Complete for requested scope", "No", "unknown", "A governing footnote has not been resolved."):
            self.assertIn(text, visible)

    def test_rejects_changed_quote_errors_and_projected_packets(self):
        changed = copy.deepcopy(self.packet)
        changed["evidence"][0]["text"] += " Changed meaning."
        for value in (changed, {"ok": False, "error": {}}, {**self.packet, "response_profile": "concise_evidence_v1"}, []):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                reader.render(value)

    def test_original_page_preview_keeps_all_text_and_rejects_stale_bindings(self):
        record = self.packet["evidence"][0]
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aC1sAAAAASUVORK5CYII=")
        root = Path(self.temporary.name)
        (root / "page.png").write_bytes(png)
        entry = {"package_digest": self.packet["package"]["package_digest"], "record_id": record["record_id"],
                 "source_sha256": record["citation"]["source_sha256"], "page": record["citation"]["page"],
                 "png_path": "page.png", "png_sha256": hashlib.sha256(png).hexdigest()}
        mapping = root / "previews.json"
        mapping.write_text(json.dumps([entry]), encoding="utf-8")
        previews = reader.load_previews(mapping)
        parsed = ReaderDocument(reader.render(self.packet, previews=previews))
        self.assertEqual([r["text"] for r in self.packet["evidence"]], parsed.quotes)
        images = [attrs for tag, attrs in parsed.tags if tag == "img"]
        self.assertEqual(1, len(images))
        self.assertTrue(images[0]["src"].startswith("data:image/png;base64,"))
        for field, value in (("page", 9999), ("source_sha256", "0" * 64)):
            stale = copy.deepcopy(previews)
            next(iter(stale.values()))[field] = value
            with self.assertRaises(ValueError):
                reader.render(self.packet, previews=stale)
        (root / "page.png").write_bytes(b"not the preview")
        with self.assertRaises(ValueError):
            reader.load_previews(mapping)


if __name__ == "__main__":
    unittest.main()
