from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_structure_compiler as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
import validate_contracts as contracts
from standardsforge.errors import StandardsForgeError
from standardsforge.service import StandardsForgeService, _RequestVerificationContext


class SourcePdfTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='standardsforge-source-pdfs-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        pack = self.root / 'pack'
        shutil.copytree(ROOT / 'examples/packs/fictional-adapter-v1', pack)
        inventory = json.loads((pack / 'inventory.json').read_text())
        for name in ('standard.pdf', 'notice.PDF'):
            path = pack / 'sources' / name
            fixtures.StructureCompilerTests._write_pdf(path)
            data = path.read_bytes()
            inventory['files'].append({'path': 'sources/' + name,
                'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        (pack / 'inventory.json').write_text(json.dumps(inventory), encoding='utf-8')
        self.db, self.objects = self.root / 'db.sqlite', self.root / 'objects'
        self.admin = StandardsForgeService(self.db, self.objects)
        policy = ROOT / 'examples/policies/local-synthetic.json'
        self.digest = self.admin.install_pack(pack, policy)['package_digest']
        self.text_digest = self.admin.install_pack(
            ROOT / 'examples/packs/fictional-adapter-v2', policy)['package_digest']
        self.service = StandardsForgeService.open_read_only(self.db, self.objects)

    def get(self):
        return self.service.get_source_pdfs(self.digest, 'local-user')

    def test_all_pdf_components_verified_offline_read_only_and_schema(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        with patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
            result = self.get()
        self.assertEqual('available', result['availability'])
        self.assertEqual(['sources/notice.PDF', 'sources/standard.pdf'], [f['source_path'] for f in result['files']])
        for file in result['files']:
            path = Path(file['local_path'])
            self.assertTrue(path.is_absolute())
            self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
            self.assertEqual(file['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(file['bytes'], path.stat().st_size)
        schemas = contracts.load_schemas()
        registry = contracts.check_schema_documents(schemas)
        contracts.validate_with_schema(schemas, registry, 'success-response.schema.json', {'ok': True, 'result': result})
        missing = self.service.get_source_pdfs(self.text_digest, 'local-user')
        self.assertEqual('no_pdf_sources', missing['availability'])
        self.assertEqual([], missing['files'])
        contracts.validate_with_schema(schemas, registry, 'source-pdfs.schema.json', missing)
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_missing_and_tampered_files_fail_on_each_request(self):
        path = Path(self.get()['files'][0]['local_path'])
        original = path.read_bytes()
        path.write_bytes(original + b'changed')
        with self.assertRaises(StandardsForgeError) as error:
            self.get()
        self.assertEqual('source_integrity_failure', error.exception.code)
        path.write_bytes(original)
        self.get()
        path.unlink()
        with self.assertRaises(StandardsForgeError) as error:
            self.get()
        self.assertEqual('source_integrity_failure', error.exception.code)

    def test_authorization_and_revocation_during_file_check(self):
        with self.assertRaises(StandardsForgeError):
            self.service.get_source_pdfs(self.digest, 'other-user')
        verify = _RequestVerificationContext.verified_file
        def revoke(context, *args):
            result = verify(context, *args)
            self.admin.revoke(self.digest, 'local-user')
            return result
        with patch.object(_RequestVerificationContext, 'verified_file', revoke):
            with self.assertRaises(StandardsForgeError):
                self.get()

    def test_cli_and_mcp_deliver_files_with_host_bound_paths(self):
        expected = self.get()
        response = subprocess.run([sys.executable, '-m', 'standardsforge', '--db', str(self.db),
            '--store', str(self.objects), 'source-pdfs', self.digest, '--principal', 'local-user'],
            capture_output=True, text=True, check=True, cwd=ROOT)
        self.assertEqual(expected, json.loads(response.stdout)['result'])
        from mcp import Client
        from standardsforge.mcp_server import create_mcp_server
        async def run():
            async with Client(create_mcp_server(self.service, 'local-user')) as client:
                response = await client.call_tool('get_source_pdfs', {'package_digest': self.digest})
                self.assertFalse(response.is_error)
                self.assertEqual(expected, response.structured_content['result'])
                response = await client.call_tool('get_source_pdfs', {
                    'package_digest': self.digest, 'path': str(self.root), 'principal_id': 'other-user'})
                self.assertEqual(expected, response.structured_content['result'])
                self.admin.revoke(self.digest, 'local-user')
                response = await client.call_tool('get_source_pdfs', {'package_digest': self.digest})
                self.assertTrue(response.is_error)
                self.assertIsNone(response.structured_content)
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
