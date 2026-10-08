import hashlib
import json
import socket
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from standardsforge.bundle import build_bundle, install_bundle, verify_bundle
from standardsforge.errors import StandardsForgeError
from standardsforge.service import StandardsForgeService
import validate_contracts as contracts


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = [ROOT / 'examples/packs' / f'fictional-adapter-v{i}' for i in (1, 2)]
        self.policy = ROOT / 'examples/policies/local-synthetic.json'
        self.bundle = self.root / 'bundle.zip'

    def test_deterministic_deduplication_reconstruction_and_authorized_install(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
            report = build_bundle(self.sources, self.bundle)
            build_bundle(list(reversed(self.sources)), self.root / 'reverse.zip')
            # Source order is irrelevant to logical package identity; repeated
            # identical ordered input must also be byte reproducible.
            build_bundle(self.sources, self.root / 'repeat.zip')
            self.assertEqual(self.bundle.read_bytes(), (self.root / 'repeat.zip').read_bytes())
            self.assertGreater(report['deduplicated_file_bytes'], 0)
            self.assertEqual(verify_bundle(self.bundle)['package_digests'], verify_bundle(self.root/'reverse.zip')['package_digests'])
            with zipfile.ZipFile(self.bundle) as archive:
                manifest = json.loads(archive.read('bundle.json'))
            schemas = contracts.load_schemas()
            contracts.validate_with_schema(schemas, contracts.check_schema_documents(schemas), 'content-bundle.schema.json', manifest)
            service = StandardsForgeService(self.root / 'memory.db', self.root / 'objects')
            result = install_bundle(self.bundle, service, self.policy)
            self.assertEqual(2, result['packages'])
            for item in result['installed']:
                packet = service.get_clause(item['package_digest'], '4.2.1', 'local-user')
                self.assertTrue(packet['evidence'][0]['source_checks']['source_digest_verified'])
            self.assertEqual(2, install_bundle(self.bundle, service, self.policy)['packages'])

    def test_malformed_paths_extra_blobs_and_corruption_are_rejected(self):
        build_bundle(self.sources, self.bundle)
        with zipfile.ZipFile(self.bundle) as archive:
            entries = {name:archive.read(name) for name in archive.namelist()}
        variants = []
        extra = dict(entries); extra['blobs/' + '0'*64] = b'extra'; variants.append(extra)
        altered = dict(entries); key = next(k for k in entries if k.startswith('blobs/')); altered[key] = b'x'*len(entries[key]); variants.append(altered)
        unsafe = dict(entries); manifest = json.loads(entries['bundle.json']); manifest['packs'][0]['files'][0]['path'] = '../escape.txt'; unsafe['bundle.json'] = json.dumps(manifest).encode(); variants.append(unsafe)
        for i, variant in enumerate(variants):
            target = self.root / f'bad-{i}.zip'
            with zipfile.ZipFile(target, 'w') as archive:
                for name, data in variant.items(): archive.writestr(name,data)
            with self.subTest(i=i), self.assertRaises(StandardsForgeError): verify_bundle(target)

    def test_policy_preflight_and_existing_destination(self):
        build_bundle(self.sources, self.bundle)
        service = StandardsForgeService(self.root / 'memory.db', self.root / 'objects')
        policy = json.loads(self.policy.read_text()); policy['allowed_pack_ids'] = ['not-authorized']
        denied = self.root / 'denied.json'; denied.write_text(json.dumps(policy))
        with self.assertRaises(StandardsForgeError): install_bundle(self.bundle, service, denied)
        self.assertEqual([], service.list_documents('local-user')['documents'])
        before = hashlib.sha256(self.bundle.read_bytes()).hexdigest()
        with self.assertRaises(StandardsForgeError): build_bundle(self.sources, self.bundle)
        self.assertEqual(before, hashlib.sha256(self.bundle.read_bytes()).hexdigest())
