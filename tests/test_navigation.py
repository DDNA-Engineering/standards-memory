from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_structure_compiler as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import validate_contracts as contracts
from standardsforge.errors import StandardsForgeError
from standardsforge.service import StandardsForgeService
from standardsforge.structure_compiler import compile_structured_pdf_section


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StructureCompilerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        root = self.fixture.root
        output = root / "pack"
        compile_structured_pdf_section(self.fixture.catalog_path, self.fixture.document["document_id"],
                                       self.fixture.sources, self.fixture.annotations_path, output)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        policy = root / "policy.json"
        policy.write_text(json.dumps({"policy_version": "0.1.0", "policy_id": "navigation-test",
            "principal_id": "local-user", "allow_admin_install": True, "allow_serve": True,
            "allowed_pack_ids": [manifest["pack_id"]], "allowed_content_classes": ["public_government_standard"]}), encoding="utf-8")
        self.db, self.objects = root / "memory.db", root / "objects"
        self.admin = StandardsForgeService(self.db, self.objects)
        self.digest = self.admin.install_pack(output, policy)["package_digest"]
        self.service = StandardsForgeService.open_read_only(self.db, self.objects)
        self.rows = self.service.store.all_records(self.digest)
        self.parent, self.child = [r["record_id"] for r in self.rows]

    def browse(self, **kwargs):
        return self.service.browse_records(self.digest, "local-user", **kwargs)

    def test_complete_navigation_schema_and_offline_read_only(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        schemas = contracts.load_schemas()
        registry = contracts.check_schema_documents(schemas)
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            first = self.browse(limit=1)
            last = self.browse(limit=1, cursor=first["page"]["next_cursor"])
            self.assertEqual(0, first["records"][0]["ordinal"])
            self.assertEqual([self.parent, self.child], [p["records"][0]["record_id"] for p in (first, last)])
            self.assertTrue(last["coverage"]["traversal_complete"])
            self.assertEqual(2, last["page"]["matching_record_count"])
            cases = [("roots", None, [self.parent]), ("children", self.parent, [self.child]),
                     ("parent", self.child, [self.parent]), ("parent", self.parent, []),
                     ("adjacent", self.parent, [self.child]), ("adjacent", self.child, [self.parent]),
                     ("outgoing", self.child, [self.parent]), ("incoming", self.parent, [self.child])]
            for relation, anchor, expected in cases:
                packet = self.browse(relation=relation, record_id=anchor)
                self.assertEqual(expected, [r["record_id"] for r in packet["records"]], relation)
                contracts.validate_with_schema(schemas, registry, "query-response.schema.json", packet)
                for record in packet["records"]:
                    self.assertEqual("unclassified", record["statement_role"])
                    self.assertTrue(all(record["source_checks"].values()))
                if relation in {"incoming", "outgoing"}:
                    self.assertEqual("governed_by", packet["records"][0]["traversed_relationships"][0]["relationship"])
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_cursor_filters_tampering_and_revocation(self):
        cursor = self.browse(limit=1)["page"]["next_cursor"]
        for kwargs in ({"cursor": cursor, "kind": "clause"}, {"cursor": cursor, "relation": "roots"},
                       {"cursor": cursor[:-3] + "abc"}, {"relation": "children"},
                       {"record_id": self.parent}, {"limit": True}, {"kind": "*"}, {"max_bytes": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(StandardsForgeError):
                self.browse(**kwargs)
        with self.assertRaises(StandardsForgeError):
            self.service.browse_records(self.digest, "other-user", cursor=cursor)
        self.admin.revoke(self.digest, "local-user")
        with self.assertRaises(StandardsForgeError):
            self.browse(cursor=cursor)

    def test_source_tampering_and_midflight_revocation(self):
        original = self.service.store.navigation_page
        def revoked(*args):
            result = original(*args)
            self.admin.revoke(self.digest, "local-user")
            return result
        with patch.object(self.service.store, "navigation_page", side_effect=revoked), self.assertRaises(StandardsForgeError):
            self.browse()

    def test_source_tampering_on_both_anchor_and_result(self):
        package = self.service.store.authorized_package("local-user", self.digest)
        source = json.loads(self.rows[0]["source_json"])
        path = Path(package["object_path"]) / source["path"]
        path.write_bytes(path.read_bytes() + b"tampered")
        for kwargs in ({}, {"relation": "children", "record_id": self.parent}):
            with self.assertRaises(StandardsForgeError) as raised:
                self.browse(**kwargs)
            self.assertEqual("source_integrity_failure", raised.exception.code)

    def test_filters_are_literal_and_evidence_selector_replays(self):
        self.assertEqual([], self.browse(scope_prefix="%") ["records"])
        self.assertEqual([self.child], [r["record_id"] for r in self.browse(kind="clause")["records"]])
        packet = self.browse(scope_prefix="1")
        self.assertEqual(2, len(packet["records"]))
        selector = dict(packet["records"][1]["evidence_selector"])
        selector.pop("operation")
        evidence = self.service.get_clause(principal_id="local-user", **selector)
        self.assertEqual("get_clause", evidence["operation"])

    def test_cli_and_mcp_match_core(self):
        expected = self.browse()
        result = subprocess.run([sys.executable, "-m", "standardsforge", "--db", str(self.db),
            "--store", str(self.objects), "browse-records", self.digest, "--principal", "local-user"],
            capture_output=True, text=True, check=True, cwd=ROOT)
        self.assertEqual(expected, json.loads(result.stdout)["result"])
        from mcp import Client
        from standardsforge.mcp_server import create_mcp_server
        server = create_mcp_server(self.service, "local-user", result_mode="structured_only")
        async def run():
            async with Client(server) as client:
                result = await client.call_tool("browse_records", {"package_digest": self.digest})
            self.assertFalse(result.is_error)
            self.assertEqual([], result.content)
            self.assertEqual(expected, result.structured_content["result"])
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
