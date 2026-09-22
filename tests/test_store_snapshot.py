from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.service import StandardsForgeService  # noqa: E402


PACK_V1 = ROOT / "examples" / "packs" / "fictional-adapter-v1"
POLICY = ROOT / "examples" / "policies" / "local-synthetic.json"


class StoreSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-store-snapshot-")
        base = Path(self.temp.name)
        self.db_path = base / "memory.db"
        self.service = StandardsForgeService(self.db_path, base / "objects")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_evidence_graph_uses_one_snapshot_across_concurrent_commit(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            self.assertEqual("wal", connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])

        db_path = self.db_path

        class ConcurrentCommitConnection(sqlite3.Connection):
            mutation_committed = False
            snapshot_active_before_mutation = False

            def execute(self, sql, parameters=()):  # type: ignore[no-untyped-def]
                if "FROM dependencies" in sql and not type(self).mutation_committed:
                    type(self).snapshot_active_before_mutation = self.in_transaction
                    with closing(sqlite3.connect(db_path)) as writer, writer:
                        writer.execute(
                            """
                            UPDATE dependencies SET required = 0
                            WHERE package_digest = ? AND source_record_id = ?
                            """,
                            (digest, "clause-4.2.1"),
                        )
                    type(self).mutation_committed = True
                return super().execute(sql, parameters)

        def connect_with_probe() -> sqlite3.Connection:
            connection = sqlite3.connect(self.db_path, factory=ConcurrentCommitConnection)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            return connection

        with patch.object(self.service.store, "connect", side_effect=connect_with_probe):
            rows, relationships, missing = self.service.store.evidence_graph(digest, ["4.2.1"])

        self.assertTrue(ConcurrentCommitConnection.snapshot_active_before_mutation)
        self.assertTrue(ConcurrentCommitConnection.mutation_committed)
        self.assertEqual([], missing)
        self.assertEqual(["clause-4.2.1", "note-4.2.1-1"], [row["record_id"] for row in rows])
        self.assertEqual(
            [
                {
                    "source_record_id": "clause-4.2.1",
                    "relationship": "governed_by",
                    "target_record_id": "note-4.2.1-1",
                }
            ],
            relationships,
        )
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            required = connection.execute(
                """
                SELECT required FROM dependencies
                WHERE package_digest = ? AND source_record_id = ?
                """,
                (digest, "clause-4.2.1"),
            ).fetchone()[0]
        self.assertEqual(0, required)

    def test_external_content_fts_tracks_install_update_delete_and_reinstall(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]

        def matching_ids(query: str, index_name: str = "exact") -> list[str]:
            return [
                row["record_id"]
                for row in self.service.store.search(
                    "local-user", query, 20, digest, index_name=index_name
                )
            ]

        self.assertCountEqual(
            ["clause-4.2.1", "clause-4.2.2"],
            matching_ids("adapter"),
        )
        self.service.install_pack(PACK_V1, POLICY)
        self.assertCountEqual(
            ["clause-4.2.1", "clause-4.2.2"],
            matching_ids("adapter"),
        )

        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            fts_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'records_fts'"
            ).fetchone()[0]
            natural_fts_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'records_natural_fts'"
            ).fetchone()[0]
            self.assertIn("content='records'", fts_sql)
            self.assertIn("content='records'", natural_fts_sql)
            self.assertIn("porter unicode61", natural_fts_sql)
            self.assertEqual(
                3,
                connection.execute(
                    "SELECT count(*) FROM records_fts JOIN records ON records_fts.rowid = records.rowid"
                ).fetchone()[0],
            )
            connection.execute(
                "UPDATE records SET text = ? WHERE package_digest = ? AND record_id = ?",
                (
                    "The sensor shall retain the connector under a steady axial load of 80 N for 60 seconds.",
                    digest,
                    "clause-4.2.1",
                ),
            )

        self.assertNotIn("clause-4.2.1", matching_ids("adapter"))
        self.assertEqual(["clause-4.2.1"], matching_ids("sensor"))
        self.assertEqual(["clause-4.2.1"], matching_ids("sensors", "natural"))

        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("DELETE FROM dependencies WHERE package_digest = ?", (digest,))
            connection.execute(
                "DELETE FROM records WHERE package_digest = ? AND record_id = ?",
                (digest, "clause-4.2.1"),
            )
        self.assertEqual([], matching_ids("sensor"))
        self.assertEqual([], matching_ids("sensors", "natural"))

    def test_schema_four_migration_adds_natural_index_and_rebuilds_legacy_fts(self) -> None:
        digest = self.service.install_pack(PACK_V1, POLICY)["package_digest"]
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("DROP TABLE records_fts")
            connection.execute(
                """
                CREATE VIRTUAL TABLE records_fts USING fts5(
                    package_digest UNINDEXED, record_id UNINDEXED, clause_reference, heading, text,
                    tokenize='unicode61'
                )
                """
            )
            connection.execute(
                "INSERT INTO records_fts(package_digest, record_id, clause_reference, heading, text) VALUES (?, ?, ?, ?, ?)",
                (digest, "stale-record", "stale", "stale", "stale legacy index content"),
            )
            connection.execute("DROP TABLE records_natural_fts")
            connection.execute("UPDATE metadata SET value = '4' WHERE key = 'schema_version'")

        self.service = StandardsForgeService(self.db_path, self.service.store.object_root)
        self.assertCountEqual(
            ["clause-4.2.1", "clause-4.2.2"],
            [
                row["record_id"]
                for row in self.service.store.search("local-user", "adapter", 20, digest)
            ],
        )
        self.assertEqual([], self.service.store.search("local-user", "stale", 20, digest))
        self.assertEqual(
            ["clause-4.2.1"],
            [
                row["record_id"]
                for row in self.service.store.search(
                    "local-user", '"connectors" AND "retained"', 20, digest, index_name="natural"
                )
            ],
        )
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            version = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()[0]
            fts_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'records_fts'"
            ).fetchone()[0]
            natural_fts_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'records_natural_fts'"
            ).fetchone()[0]
        self.assertEqual("5", version)
        self.assertIn("content='records'", fts_sql)
        self.assertIn("porter unicode61", natural_fts_sql)


if __name__ == "__main__":
    unittest.main()
