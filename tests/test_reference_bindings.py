from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from standardsforge.coverage_ledger import digest
from standardsforge.errors import StandardsForgeError
from standardsforge.reference_bindings import validate_bindings
from standardsforge.service import StandardsForgeService
import validate_contracts as contracts


class ReferenceBindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db, self.objects = self.root / "memory.db", self.root / "objects"
        self.admin = StandardsForgeService(self.db, self.objects)
        self.pins = [self.admin.install_pack(ROOT / "examples/packs" / name,
                      ROOT / "examples/policies/local-synthetic.json")["package_digest"]
                     for name in ("fictional-adapter-v1", "fictional-adapter-v2")]
        self.service = StandardsForgeService.open_read_only(self.db, self.objects)
        selectors = []
        for pin in self.pins:
            packet = self.service.get_clause(pin, principal_id="local-user", record_id="clause-4.2.1")
            record = packet["evidence"][0]
            selectors.append({"package_digest": pin, "edition_id": packet["package"]["edition_id"],
                              "record_id": record["record_id"], "quote_sha256": record["citation"]["quote_sha256"]})
        text = self.service.get_clause(self.pins[0], principal_id="local-user", record_id="clause-4.2.1")["evidence"][0]["text"]
        self.binding = {"binding_id": "synthetic-reference", "source": selectors[0],
                        "reference": {"start_byte": 0, "end_byte": len(text.encode("utf-8")), "exact_text": text},
                        "target": selectors[1], "status": "resolved",
                        "edition_basis": "reviewer_selected_navigation_edition", "rationale": "Synthetic cross-package navigation fixture only."}
        self.path = self.root / "bindings.json"
        self.configure(self.binding)

    def configure(self, binding):
        binding = copy.deepcopy(binding)
        binding["review"] = {"kind": "agent", "identity": "fixture-review", "reviewed_at": "2026-10-08",
                             "binding_sha256": digest({k: v for k, v in binding.items() if k != "review"})}
        body = {"binding_set_id": "fixture", "bindings": [binding], "scope": "reviewed_navigation_only",
                "project_applicability": "not_decided"}
        self.document = {"schema_version": "0.1.0", "binding_set": body, "binding_set_sha256": digest(body)}
        self.path.write_text(json.dumps(self.document), encoding="utf-8")
        self.pin = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.service.configure_reference_bindings(self.path, self.pin)

    def follow(self, **kwargs):
        return self.service.follow_references(self.pins[0], "clause-4.2.1", "local-user", **kwargs)

    def test_complete_offline_evidence_contract_and_cli(self):
        before = self.db.read_bytes()
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            packet = self.follow()
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(self.pins[1], packet["references"][0]["target_evidence"]["package"]["package_digest"])
        self.assertEqual(2, len(packet["source_evidence"]["evidence"]))
        self.assertFalse(packet["coverage"]["transitive_closure_complete"])
        schemas = contracts.load_schemas(); registry = contracts.check_schema_documents(schemas)
        contracts.validate_with_schema(schemas, registry, "reference-bindings.schema.json", self.document)
        contracts.validate_with_schema(schemas, registry, "query-response.schema.json", packet)
        result = subprocess.run([sys.executable, "-m", "standardsforge", "--db", str(self.db), "--store", str(self.objects),
            "--reference-bindings", str(self.path), "--reference-bindings-sha256", self.pin,
            "follow-references", self.pins[0], "clause-4.2.1", "--principal", "local-user"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual(packet, json.loads(result.stdout)["result"])

    def test_unresolved_zero_and_budget_do_not_claim_completeness(self):
        binding = dict(self.binding, target=None, status="unresolved", edition_basis="unresolved")
        self.configure(binding)
        self.assertIsNone(self.follow()["references"][0]["target_evidence"])
        self.assertEqual(1, self.follow()["coverage"]["unresolved"])
        packet = self.service.follow_references(self.pins[0], "clause-4.2.2", "local-user")
        self.assertEqual([], packet["references"])
        self.assertFalse(packet["coverage"]["all_source_references_reviewed"])
        with self.assertRaises(StandardsForgeError): self.follow(max_bytes=1)

    def test_stale_endpoint_span_and_missing_target(self):
        for selector_key, field, value in (("source", "quote_sha256", "0" * 64), ("target", "edition_id", "wrong"),
                ("target", "record_id", "absent"), ("target", "package_digest", "0" * 64),
                ("reference", "exact_text", "x" * len(self.binding["reference"]["exact_text"]))):
            binding = copy.deepcopy(self.binding); binding[selector_key][field] = value
            self.configure(binding)
            with self.subTest(field=field), self.assertRaises(StandardsForgeError): self.follow()

    def test_review_digest_and_trusted_startup_pin(self):
        with self.assertRaises(StandardsForgeError): self.service.configure_reference_bindings(self.path, "0" * 64)
        document = copy.deepcopy(self.document)
        document["binding_set"]["bindings"][0]["rationale"] = "changed"
        document["binding_set_sha256"] = digest(document["binding_set"])
        with self.assertRaises(StandardsForgeError): validate_bindings(document)
        document = copy.deepcopy(self.document)
        document["binding_set"]["bindings"].append(document["binding_set"]["bindings"][0])
        document["binding_set_sha256"] = digest(document["binding_set"])
        with self.assertRaises(StandardsForgeError): validate_bindings(document)

    def test_revoked_endpoint_and_midflight_revocation(self):
        self.admin.revoke(self.pins[1], "local-user")
        with self.assertRaises(StandardsForgeError): self.follow()
        self.admin.install_pack(ROOT / "examples/packs/fictional-adapter-v2", ROOT / "examples/policies/local-synthetic.json")
        original = self.service._finalize_budget
        def revoked(*args):
            original(*args)
            self.admin.revoke(self.pins[0], "local-user")
        with patch.object(self.service, "_finalize_budget", side_effect=revoked), self.assertRaises(StandardsForgeError): self.follow()

    def test_target_source_tampering_is_reverified(self):
        self.follow()
        package = self.service.store.authorized_package("local-user", self.pins[1])
        row = self.service.store.record_by_id(self.pins[1], "clause-4.2.1")
        source = json.loads(row["source_json"])
        path = Path(package["object_path"]) / source["path"]
        path.write_bytes(path.read_bytes() + b"tampered")
        with self.assertRaises(StandardsForgeError): self.follow()

    def test_mcp_keeps_paths_and_principal_at_startup(self):
        from mcp import Client
        from standardsforge.mcp_server import create_mcp_server
        async def run():
            async with Client(create_mcp_server(self.service, "local-user")) as client:
                tools = await client.list_tools()
                tool = next(t for t in tools.tools if t.name == "follow_references")
                self.assertEqual({"package_digest", "record_id", "max_bytes"}, set(tool.input_schema["properties"]))
                result = await client.call_tool("follow_references", {"package_digest": self.pins[0], "record_id": "clause-4.2.1"})
                self.assertFalse(result.is_error)
                self.assertEqual("follow_references", result.structured_content["result"]["operation"])
        asyncio.run(run())
