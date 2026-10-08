import asyncio
import base64
import hashlib
import importlib.util
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from standardsforge.service import StandardsForgeService
from standardsforge.errors import StandardsForgeError
from standardsforge.tokenization import canonical_json
import validate_contracts as contracts


class ProfileSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = StandardsForgeService(self.root/'memory.db', self.root/'objects')
        self.digest = self.service.install_pack(ROOT/'examples/packs/fictional-adapter-v1', ROOT/'examples/policies/local-synthetic.json')['package_digest']

    def select(self, **kwargs):
        return self.service.select_evidence(self.digest, 'clause-4.2.1', 'local-user', **kwargs)

    def test_exact_byte_selection_schema_and_no_silent_token_estimate(self):
        packet = self.select()
        self.assertEqual('utf8_bytes', packet['selection_basis'])
        selected = next(c for c in packet['candidates'] if c['profile'] == packet['selected_profile'])
        self.assertEqual(min(c['utf8_bytes'] for c in packet['candidates']), selected['utf8_bytes'])
        self.assertEqual(len(canonical_json(packet['evidence'])), selected['utf8_bytes'])
        schemas = contracts.load_schemas()
        contracts.validate_with_schema(schemas, contracts.check_schema_documents(schemas), 'query-response.schema.json', packet)
        for kwargs in ({'max_tokens':100000}, {'max_bytes':1}, {'max_tokens':True}):
            with self.assertRaises(StandardsForgeError): self.select(**kwargs)

    @unittest.skipUnless(importlib.util.find_spec('tiktoken'), 'optional tokens extra required')
    def test_pinned_offline_tokenizer_and_exact_budget_boundary(self):
        fixture = {'schema_version':'0.1.0','name':'test-byte-bpe','pat_str':r'[\s\S]',
                   'special_tokens':{},'mergeable_ranks':[[base64.b64encode(bytes([i])).decode(),i] for i in range(256)]}
        path = self.root/'tokenizer.json'; data = canonical_json(fixture); path.write_bytes(data)
        schemas = contracts.load_schemas()
        contracts.validate_with_schema(schemas, contracts.check_schema_documents(schemas), 'local-tokenizer.schema.json', fixture)
        with patch.object(socket,'socket',side_effect=AssertionError('network forbidden')):
            self.service.configure_tokenizer(path,hashlib.sha256(data).hexdigest())
            packet = self.select()
            selected = next(c for c in packet['candidates'] if c['profile'] == packet['selected_profile'])
            count = self.service.token_counter.count(packet['evidence'])
            self.assertEqual(count,selected['tokens'])
            self.assertEqual(packet['selected_profile'],self.select(max_tokens=count)['selected_profile'])
            with self.assertRaises(StandardsForgeError): self.select(max_tokens=count-1)
            with self.assertRaises(StandardsForgeError): self.service.configure_tokenizer(path,'0'*64)
        contracts.validate_with_schema(schemas, contracts.check_schema_documents(schemas), 'query-response.schema.json', packet)

    def test_mcp_selection_and_revocation(self):
        from mcp import Client
        from standardsforge.mcp_server import create_mcp_server
        expected = self.select()
        server = create_mcp_server(self.service,'local-user',result_mode='structured_only')
        async def run():
            async with Client(server) as client:
                result = await client.call_tool('select_evidence',{'package_digest':self.digest,'record_id':'clause-4.2.1'})
            self.assertFalse(result.is_error)
            self.assertEqual(expected,result.structured_content['result'])
            self.assertEqual([],result.content)
        asyncio.run(run())
        self.service.revoke(self.digest,'local-user')
        with self.assertRaises(StandardsForgeError): self.select()
