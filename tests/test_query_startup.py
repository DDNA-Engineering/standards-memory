from __future__ import annotations

import contextlib
import hashlib
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from standardsforge.cli import main
from standardsforge.service import StandardsForgeService
from standardsforge.errors import StandardsForgeError


class QueryStartupTests(unittest.TestCase):
    def test_queries_do_not_create_or_migrate_state(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            db, objects = base / "memory.db", base / "objects"
            args = ["--db", str(db), "--store", str(objects), "list-documents", "--principal", "local-user"]
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, main(args))
            self.assertEqual([], list(base.iterdir()))
            service = StandardsForgeService(db, objects)
            service.install_pack(ROOT / "examples/packs/fictional-adapter-v1", ROOT / "examples/policies/local-synthetic.json")
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(args))
            self.assertEqual(before, hashlib.sha256(db.read_bytes()).hexdigest())
            reader = StandardsForgeService.open_read_only(db, objects)
            with contextlib.closing(reader.store.connect()) as connection:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM records")
            with contextlib.closing(service.store.connect()) as connection, connection:
                connection.execute("UPDATE metadata SET value = '4' WHERE key = 'schema_version'")
            before = db.read_bytes()
            with self.assertRaises(StandardsForgeError) as caught:
                StandardsForgeService.open_read_only(db, objects)
            self.assertEqual("schema_migration_required", caught.exception.code)
            self.assertEqual(before, db.read_bytes())

    def test_mcp_missing_store_fails_without_creating_state(self):
        from standardsforge.mcp_server import main as mcp_main
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, mcp_main(["--db", str(base / "db"), "--store", str(base / "objects"), "--principal", "local-user"]))
            self.assertEqual([], list(base.iterdir()))
