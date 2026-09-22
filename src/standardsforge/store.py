from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from .errors import StandardsForgeError, require
from .identity import normalize_identifier
from .models import LocalPolicy, ValidatedPack
from .pack import validate_pack_directory


SCHEMA_VERSION = 4


class LocalStore:
    def __init__(self, db_path: str | Path, object_root: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.object_root = Path(object_root).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.object_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        try:
            with self._connection() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS packages (
                        package_digest TEXT PRIMARY KEY,
                        pack_id TEXT NOT NULL,
                        document_family_id TEXT NOT NULL,
                        edition_id TEXT NOT NULL,
                        publisher TEXT NOT NULL,
                        identifier TEXT NOT NULL,
                        normalized_identifier TEXT NOT NULL,
                        title TEXT NOT NULL,
                        revision TEXT NOT NULL,
                        publication_date TEXT NOT NULL,
                        category TEXT NOT NULL,
                        object_path TEXT NOT NULL,
                        manifest_json TEXT NOT NULL,
                        rights_json TEXT NOT NULL,
                        inventory_json TEXT NOT NULL,
                        installed_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS packages_identity_idx
                        ON packages(normalized_identifier, edition_id);
                    CREATE TABLE IF NOT EXISTS grants (
                        principal_id TEXT NOT NULL,
                        package_digest TEXT NOT NULL,
                        can_serve INTEGER NOT NULL CHECK(can_serve IN (0, 1)),
                        policy_id TEXT NOT NULL,
                        policy_fingerprint TEXT NOT NULL,
                        revoked_at TEXT,
                        PRIMARY KEY(principal_id, package_digest),
                        FOREIGN KEY(package_digest) REFERENCES packages(package_digest)
                    );
                    CREATE TABLE IF NOT EXISTS records (
                        package_digest TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        edition_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        clause_reference TEXT NOT NULL,
                        heading TEXT NOT NULL,
                        text TEXT NOT NULL,
                        source_json TEXT NOT NULL,
                        statement_role TEXT NOT NULL,
                        derivation_json TEXT NOT NULL,
                        structure_json TEXT NOT NULL DEFAULT '{}',
                        ordinal INTEGER NOT NULL,
                        PRIMARY KEY(package_digest, record_id),
                        FOREIGN KEY(package_digest) REFERENCES packages(package_digest)
                    );
                    CREATE INDEX IF NOT EXISTS records_clause_idx
                        ON records(package_digest, clause_reference, kind);
                    CREATE TABLE IF NOT EXISTS dependencies (
                        package_digest TEXT NOT NULL,
                        source_record_id TEXT NOT NULL,
                        relationship TEXT NOT NULL,
                        target_record_id TEXT NOT NULL,
                        required INTEGER NOT NULL CHECK(required IN (0, 1)),
                        PRIMARY KEY(package_digest, source_record_id, relationship, target_record_id),
                        FOREIGN KEY(package_digest, source_record_id)
                            REFERENCES records(package_digest, record_id),
                        FOREIGN KEY(package_digest, target_record_id)
                            REFERENCES records(package_digest, record_id)
                    );
                    """
                )
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
                previous_version = int(row["value"]) if row is not None else None
                if row is None:
                    connection.execute("INSERT INTO metadata(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
                elif int(row["value"]) == 1:
                    legacy_derivation = json.dumps(
                        {"statement_role": "unknown", "method": "legacy_unknown", "review_status": "unreviewed"},
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    connection.execute("ALTER TABLE records ADD COLUMN statement_role TEXT NOT NULL DEFAULT 'unknown'")
                    connection.execute(
                        "ALTER TABLE records ADD COLUMN derivation_json TEXT NOT NULL DEFAULT " + "'" + legacy_derivation + "'"
                    )
                    connection.execute("ALTER TABLE records ADD COLUMN structure_json TEXT NOT NULL DEFAULT '{}'")
                elif int(row["value"]) == 2:
                    connection.execute("ALTER TABLE records ADD COLUMN structure_json TEXT NOT NULL DEFAULT '{}'")
                elif int(row["value"]) not in {3, SCHEMA_VERSION}:
                    raise StandardsForgeError("unsupported_database_version", "The local database schema is unsupported.")

                fts_row = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'records_fts'"
                ).fetchone()
                fts_sql = str(fts_row["sql"] or "").lower() if fts_row is not None else ""
                needs_fts_rebuild = (
                    previous_version is None
                    or previous_version < SCHEMA_VERSION
                    or "content='records'" not in fts_sql
                )
                if needs_fts_rebuild:
                    connection.execute("DROP TRIGGER IF EXISTS records_fts_ai")
                    connection.execute("DROP TRIGGER IF EXISTS records_fts_ad")
                    connection.execute("DROP TRIGGER IF EXISTS records_fts_au")
                    connection.execute("DROP TABLE IF EXISTS records_fts")
                    connection.execute(
                        """
                        CREATE VIRTUAL TABLE records_fts USING fts5(
                            package_digest UNINDEXED,
                            record_id UNINDEXED,
                            clause_reference,
                            heading,
                            text,
                            content='records',
                            content_rowid='rowid',
                            tokenize='unicode61'
                        )
                        """
                    )

                connection.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS records_fts_ai AFTER INSERT ON records BEGIN
                        INSERT INTO records_fts(rowid, package_digest, record_id, clause_reference, heading, text)
                        VALUES (new.rowid, new.package_digest, new.record_id, new.clause_reference, new.heading, new.text);
                    END
                    """
                )
                connection.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS records_fts_ad AFTER DELETE ON records BEGIN
                        INSERT INTO records_fts(records_fts, rowid, package_digest, record_id, clause_reference, heading, text)
                        VALUES ('delete', old.rowid, old.package_digest, old.record_id, old.clause_reference, old.heading, old.text);
                    END
                    """
                )
                connection.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS records_fts_au AFTER UPDATE ON records BEGIN
                        INSERT INTO records_fts(records_fts, rowid, package_digest, record_id, clause_reference, heading, text)
                        VALUES ('delete', old.rowid, old.package_digest, old.record_id, old.clause_reference, old.heading, old.text);
                        INSERT INTO records_fts(rowid, package_digest, record_id, clause_reference, heading, text)
                        VALUES (new.rowid, new.package_digest, new.record_id, new.clause_reference, new.heading, new.text);
                    END
                    """
                )
                if needs_fts_rebuild:
                    connection.execute("INSERT INTO records_fts(records_fts) VALUES('rebuild')")
                if previous_version is not None and previous_version < SCHEMA_VERSION:
                    connection.execute(
                        "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
                        (str(SCHEMA_VERSION),),
                    )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS records_role_scope_idx ON records(package_digest, statement_role, clause_reference, ordinal)"
                )
                cursor_secret = connection.execute("SELECT value FROM metadata WHERE key = 'cursor_secret'").fetchone()
                if cursor_secret is None:
                    connection.execute("INSERT INTO metadata(key, value) VALUES('cursor_secret', ?)", (secrets.token_hex(32),))
                connection.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('corpus_generation', '0')")
                connection.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('authorization_generation', '0')")
        except sqlite3.Error as exc:
            raise StandardsForgeError("storage_error", "The local store could not be initialized.") from exc

    def _copy_pack(self, pack: ValidatedPack) -> Path:
        destination = self.object_root / pack.package_digest
        if destination.exists():
            require(not destination.is_symlink(), "object_store_conflict", "The object directory cannot be a symbolic link.")
            existing = validate_pack_directory(destination)
            require(existing.package_digest == pack.package_digest, "object_store_conflict", "The existing object directory has unexpected content.")
            return destination

        staging = Path(tempfile.mkdtemp(prefix=".candidate-", dir=self.object_root))
        try:
            paths = ["inventory.json", *(entry.path for entry in pack.inventory)]
            for relative in paths:
                rel = PurePosixPath(relative)
                target = staging.joinpath(*rel.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(pack.root.joinpath(*rel.parts), target)
            copied = validate_pack_directory(staging)
            require(copied.package_digest == pack.package_digest, "object_store_conflict", "Copied pack digest changed before activation.")
            for attempt in range(6):
                try:
                    os.replace(staging, destination)
                    break
                except FileExistsError:
                    existing = validate_pack_directory(destination)
                    require(existing.package_digest == pack.package_digest, "object_store_conflict", "Concurrent object install conflicted.")
                    break
                except PermissionError as exc:
                    if destination.exists():
                        existing = validate_pack_directory(destination)
                        require(existing.package_digest == pack.package_digest, "object_store_conflict", "Concurrent object install conflicted.")
                        break
                    if attempt == 5:
                        raise StandardsForgeError(
                            "object_store_activation_failed",
                            "A validated object directory could not be activated after bounded retries.",
                            {"path": str(destination)},
                        ) from exc
                    time.sleep(0.05 * (2**attempt))
            return destination
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def install(self, pack: ValidatedPack, policy: LocalPolicy) -> dict[str, Any]:
        object_path = self._copy_pack(pack)
        installed_at = datetime.now(UTC).isoformat()
        inventory_json = json.dumps(
            [{"path": entry.path, "sha256": entry.sha256, "bytes": entry.bytes} for entry in pack.inventory],
            sort_keys=True,
            separators=(",", ":"),
        )
        manifest_json = json.dumps(pack.manifest, sort_keys=True, separators=(",", ":"))
        rights_json = json.dumps(pack.rights, sort_keys=True, separators=(",", ":"))

        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT package_digest FROM packages WHERE package_digest = ?", (pack.package_digest,)
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO packages(
                            package_digest, pack_id, document_family_id, edition_id, publisher,
                            identifier, normalized_identifier, title, revision, publication_date,
                            category, object_path, manifest_json, rights_json, inventory_json, installed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pack.package_digest,
                            pack.manifest["pack_id"],
                            pack.manifest["document_family_id"],
                            pack.manifest["edition_id"],
                            pack.manifest["publisher"],
                            pack.manifest["identifier"],
                            normalize_identifier(pack.manifest["identifier"]),
                            pack.manifest["title"],
                            pack.manifest["revision"],
                            pack.manifest["publication_date"],
                            pack.manifest["category"],
                            str(object_path),
                            manifest_json,
                            rights_json,
                            inventory_json,
                            installed_at,
                        ),
                    )
                    for ordinal, record in enumerate(pack.records):
                        connection.execute(
                            """
                            INSERT INTO records(
                                package_digest, record_id, edition_id, kind, clause_reference,
                                heading, text, source_json, statement_role, derivation_json, structure_json, ordinal
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                pack.package_digest,
                                record["record_id"],
                                record["edition_id"],
                                record["kind"],
                                record["clause_reference"],
                                record["heading"],
                                record["text"],
                                json.dumps(record["source"], sort_keys=True, separators=(",", ":")),
                                record["derivation"]["statement_role"],
                                json.dumps(record["derivation"], sort_keys=True, separators=(",", ":")),
                                json.dumps(record.get("structure", {}), sort_keys=True, separators=(",", ":")),
                                ordinal,
                            ),
                        )
                    for record in pack.records:
                        for dependency in record["dependencies"]:
                            connection.execute(
                                """
                                INSERT INTO dependencies(
                                    package_digest, source_record_id, relationship, target_record_id, required
                                ) VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    pack.package_digest,
                                    record["record_id"],
                                    dependency["relationship"],
                                    dependency["target_record_id"],
                                    int(dependency["required"]),
                                ),
                            )
                    connection.execute(
                        "UPDATE metadata SET value = CAST(value AS INTEGER) + 1 WHERE key = 'corpus_generation'"
                    )
                connection.execute(
                    """
                    INSERT INTO grants(principal_id, package_digest, can_serve, policy_id, policy_fingerprint, revoked_at)
                    VALUES (?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(principal_id, package_digest) DO UPDATE SET
                        can_serve = excluded.can_serve,
                        policy_id = excluded.policy_id,
                        policy_fingerprint = excluded.policy_fingerprint,
                        revoked_at = NULL
                    """,
                    (policy.principal_id, pack.package_digest, int(policy.allow_serve), policy.policy_id, policy.fingerprint),
                )
                connection.execute(
                    "UPDATE metadata SET value = CAST(value AS INTEGER) + 1 WHERE key = 'authorization_generation'"
                )
        except sqlite3.Error as exc:
            raise StandardsForgeError("storage_error", "The pack could not be installed into the local store.") from exc

        return {
            "package_digest": pack.package_digest,
            "pack_id": pack.manifest["pack_id"],
            "document_family_id": pack.manifest["document_family_id"],
            "edition_id": pack.manifest["edition_id"],
            "principal_id": policy.principal_id,
            "serve_authorized": policy.allow_serve,
            "object_path": str(object_path),
        }

    def authorized_packages(self, principal_id: str, normalized_identifier: str, edition_id: str | None) -> list[sqlite3.Row]:
        sql = """
            SELECT p.*, g.policy_fingerprint AS grant_policy_fingerprint FROM packages p
            JOIN grants g ON g.package_digest = p.package_digest
            WHERE g.principal_id = ? AND g.can_serve = 1 AND g.revoked_at IS NULL
              AND p.normalized_identifier = ?
        """
        params: list[Any] = [principal_id, normalized_identifier]
        if edition_id is not None:
            sql += " AND p.edition_id = ?"
            params.append(edition_id)
        sql += " ORDER BY p.publication_date, p.edition_id, p.package_digest"
        with self._connection() as connection:
            return list(connection.execute(sql, params))

    def authorized_document_packages(self, principal_id: str) -> list[sqlite3.Row]:
        """Return package metadata only for grants currently visible to one principal."""

        with self._connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT p.*, g.policy_fingerprint AS grant_policy_fingerprint,
                           (
                               SELECT COUNT(*) FROM records r
                               WHERE r.package_digest = p.package_digest
                           ) AS record_count
                    FROM packages p
                    JOIN grants g ON g.package_digest = p.package_digest
                    WHERE g.principal_id = ? AND g.can_serve = 1 AND g.revoked_at IS NULL
                    ORDER BY p.normalized_identifier, p.edition_id, p.package_digest
                    """,
                    (principal_id,),
                )
            )

    def authorized_package(self, principal_id: str, package_digest: str) -> sqlite3.Row:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT p.*, g.policy_fingerprint AS grant_policy_fingerprint FROM packages p
                JOIN grants g ON g.package_digest = p.package_digest
                WHERE p.package_digest = ? AND g.principal_id = ?
                  AND g.can_serve = 1 AND g.revoked_at IS NULL
                """,
                (package_digest, principal_id),
            ).fetchone()
        if row is None:
            raise StandardsForgeError("not_found", "No authorized resource matches the request.")
        return row

    def record_by_clause(self, package_digest: str, clause_reference: str) -> sqlite3.Row | None:
        with self._connection() as connection:
            return connection.execute(
                """
                SELECT * FROM records
                WHERE package_digest = ? AND clause_reference = ?
                ORDER BY ordinal LIMIT 1
                """,
                (package_digest, clause_reference),
            ).fetchone()

    def record_by_id(self, package_digest: str, record_id: str) -> sqlite3.Row | None:
        with self._connection() as connection:
            return connection.execute(
                "SELECT * FROM records WHERE package_digest = ? AND record_id = ?",
                (package_digest, record_id),
            ).fetchone()

    def required_dependencies(self, package_digest: str, record_id: str) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT relationship, target_record_id FROM dependencies
                    WHERE package_digest = ? AND source_record_id = ? AND required = 1
                    ORDER BY relationship, target_record_id
                    """,
                    (package_digest, record_id),
                )
            )

    def evidence_graph(
        self,
        package_digest: str,
        clause_references: list[str],
    ) -> tuple[list[sqlite3.Row], list[dict[str, str]], list[str]]:
        """Read roots and their required closure in one connection with batched breadth-first queries."""

        unique_references = list(dict.fromkeys(clause_references))
        placeholders = ",".join("?" for _ in unique_references)
        try:
            with self._connection() as connection:
                # A connection context does not start a transaction for SELECTs.
                # Pin the roots, dependency edges, and dependency records to one
                # read snapshot so a concurrent install cannot produce a mixed
                # evidence graph between the batched statements below.
                connection.execute("BEGIN")
                root_rows = list(
                    connection.execute(
                        f"SELECT * FROM records WHERE package_digest = ? AND clause_reference IN ({placeholders}) ORDER BY ordinal, record_id",
                        [package_digest, *unique_references],
                    )
                )
                roots_by_reference = {row["clause_reference"]: row for row in root_rows}
                missing = [reference for reference in unique_references if reference not in roots_by_reference]
                row_by_id: dict[str, sqlite3.Row] = {}
                loaded: set[str] = set()
                frontier: list[str] = []
                for reference in unique_references:
                    row = roots_by_reference.get(reference)
                    if row is not None and row["record_id"] not in loaded:
                        loaded.add(row["record_id"])
                        row_by_id[row["record_id"]] = row
                        frontier.append(row["record_id"])

                edges_by_source: dict[str, list[dict[str, str]]] = {}
                while frontier:
                    edge_placeholders = ",".join("?" for _ in frontier)
                    edge_rows = list(
                        connection.execute(
                            f"""
                            SELECT source_record_id, relationship, target_record_id
                            FROM dependencies
                            WHERE package_digest = ? AND required = 1
                              AND source_record_id IN ({edge_placeholders})
                            ORDER BY relationship, target_record_id
                            """,
                            [package_digest, *frontier],
                        )
                    )
                    for edge in edge_rows:
                        edges_by_source.setdefault(edge["source_record_id"], []).append(
                            {
                                "source_record_id": edge["source_record_id"],
                                "relationship": edge["relationship"],
                                "target_record_id": edge["target_record_id"],
                            }
                        )
                    next_ids: list[str] = []
                    for source_record_id in frontier:
                        for edge in edges_by_source.get(source_record_id, []):
                            target_id = edge["target_record_id"]
                            if target_id not in loaded:
                                loaded.add(target_id)
                                next_ids.append(target_id)
                    if not next_ids:
                        break
                    target_placeholders = ",".join("?" for _ in next_ids)
                    target_rows = list(
                        connection.execute(
                            f"SELECT * FROM records WHERE package_digest = ? AND record_id IN ({target_placeholders})",
                            [package_digest, *next_ids],
                        )
                    )
                    targets_by_id = {row["record_id"]: row for row in target_rows}
                    unresolved = [record_id for record_id in next_ids if record_id not in targets_by_id]
                    if unresolved:
                        raise StandardsForgeError(
                            "incomplete_dependency",
                            "Required evidence dependency is unavailable.",
                            {"record_ids": unresolved},
                        )
                    row_by_id.update(targets_by_id)
                    frontier = next_ids

                ordered_rows: list[sqlite3.Row] = []
                relationships: list[dict[str, str]] = []
                emitted_records: set[str] = set()
                emitted_edges: set[tuple[str, str, str]] = set()
                for reference in unique_references:
                    root = roots_by_reference.get(reference)
                    if root is None:
                        continue
                    queue = [root["record_id"]]
                    traversed: set[str] = set()
                    while queue:
                        record_id = queue.pop(0)
                        if record_id in traversed:
                            continue
                        traversed.add(record_id)
                        if record_id not in emitted_records:
                            emitted_records.add(record_id)
                            ordered_rows.append(row_by_id[record_id])
                        for edge in edges_by_source.get(record_id, []):
                            edge_key = (edge["source_record_id"], edge["relationship"], edge["target_record_id"])
                            if edge_key not in emitted_edges:
                                emitted_edges.add(edge_key)
                                relationships.append(edge)
                            if edge["target_record_id"] not in traversed:
                                queue.append(edge["target_record_id"])
                return ordered_rows, relationships, missing
        except sqlite3.Error as exc:
            raise StandardsForgeError("storage_error", "The evidence graph could not be read.") from exc

    def records_by_ids(self, package_digest: str, record_ids: list[str]) -> list[sqlite3.Row]:
        if not record_ids:
            return []
        placeholders = ",".join("?" for _ in record_ids)
        with self._connection() as connection:
            rows = list(
                connection.execute(
                    f"SELECT * FROM records WHERE package_digest = ? AND record_id IN ({placeholders})",
                    [package_digest, *record_ids],
                )
            )
        by_id = {row["record_id"]: row for row in rows}
        return [by_id[record_id] for record_id in record_ids if record_id in by_id]

    def cache_state(self, principal_id: str) -> dict[str, str]:
        """Return current cache generations plus the caller's active visibility fingerprint."""

        with self._connection() as connection:
            generation_rows = connection.execute(
                "SELECT key, value FROM metadata WHERE key IN ('corpus_generation', 'authorization_generation')"
            ).fetchall()
            grants = connection.execute(
                """
                SELECT package_digest, policy_fingerprint
                FROM grants
                WHERE principal_id = ? AND can_serve = 1 AND revoked_at IS NULL
                ORDER BY package_digest
                """,
                (principal_id,),
            ).fetchall()
        generations = {row["key"]: row["value"] for row in generation_rows}
        visibility = json.dumps(
            [[row["package_digest"], row["policy_fingerprint"]] for row in grants],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            "corpus_generation": generations.get("corpus_generation", "0"),
            "authorization_generation": generations.get("authorization_generation", "0"),
            "visibility_fingerprint": hashlib.sha256(visibility).hexdigest(),
        }

    def all_records(self, package_digest: str) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM records WHERE package_digest = ? ORDER BY ordinal, record_id",
                    (package_digest,),
                )
            )

    def all_dependencies(self, package_digest: str) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT source_record_id, relationship, target_record_id, required
                    FROM dependencies WHERE package_digest = ?
                    ORDER BY source_record_id, relationship, target_record_id
                    """,
                    (package_digest,),
                )
            )

    @staticmethod
    def _scope_clause(scope_prefix: str) -> tuple[str, str]:
        escaped = scope_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return scope_prefix, escaped + ".%"

    def obligation_records(
        self,
        package_digest: str,
        scope_prefix: str | None,
        after_ordinal: int,
        limit: int,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT * FROM records
            WHERE package_digest = ? AND statement_role = 'obligation' AND ordinal > ?
        """
        params: list[Any] = [package_digest, after_ordinal]
        if scope_prefix is not None:
            exact, descendant = self._scope_clause(scope_prefix)
            sql += " AND (clause_reference = ? OR clause_reference LIKE ? ESCAPE '\\')"
            params.extend([exact, descendant])
        sql += " ORDER BY ordinal, record_id LIMIT ?"
        params.append(limit)
        with self._connection() as connection:
            return list(connection.execute(sql, params))

    def obligation_count(self, package_digest: str, scope_prefix: str | None) -> int:
        sql = "SELECT COUNT(*) AS count FROM records WHERE package_digest = ? AND statement_role = 'obligation'"
        params: list[Any] = [package_digest]
        if scope_prefix is not None:
            exact, descendant = self._scope_clause(scope_prefix)
            sql += " AND (clause_reference = ? OR clause_reference LIKE ? ESCAPE '\\')"
            params.extend([exact, descendant])
        with self._connection() as connection:
            row = connection.execute(sql, params).fetchone()
        return int(row["count"])

    def cursor_secret(self) -> bytes:
        with self._connection() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key = 'cursor_secret'").fetchone()
        if row is None:
            raise StandardsForgeError("storage_error", "The cursor signing key is unavailable.")
        try:
            return bytes.fromhex(row["value"])
        except ValueError as exc:
            raise StandardsForgeError("storage_error", "The cursor signing key is invalid.") from exc

    def search(
        self,
        principal_id: str,
        fts_query: str,
        limit: int,
        package_digest: str | None = None,
        scope_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = ""
        params: list[Any] = [fts_query, principal_id]
        if package_digest is not None:
            filters += " AND p.package_digest = ?"
            params.append(package_digest)
        if scope_prefix is not None:
            exact, descendant = self._scope_clause(scope_prefix)
            filters += " AND (r.clause_reference = ? OR r.clause_reference LIKE ? ESCAPE '\\')"
            params.extend([exact, descendant])
        params.append(limit)
        try:
            with self._connection() as connection:
                rows = [
                    dict(row)
                    for row in connection.execute(
                        f"""
                        SELECT p.package_digest, p.edition_id, p.identifier, p.title, p.manifest_json,
                               r.record_id, r.kind, r.clause_reference, r.heading, r.ordinal,
                               r.source_json, r.structure_json,
                               snippet(records_fts, 4, '⟦', '⟧', ' … ', 20) AS matched_snippet,
                               bm25(records_fts, 0.0, 0.0, 3.0, 1.0, 1.0) AS score
                        FROM records_fts
                        JOIN records r
                          ON r.package_digest = records_fts.package_digest
                         AND r.record_id = records_fts.record_id
                        JOIN packages p ON p.package_digest = r.package_digest
                        JOIN grants g ON g.package_digest = p.package_digest
                        WHERE records_fts MATCH ? AND g.principal_id = ?
                          AND g.can_serve = 1 AND g.revoked_at IS NULL
                          {filters}
                        ORDER BY score, p.package_digest, r.ordinal
                        LIMIT ?
                        """,
                        params,
                    )
                ]

                structural_matches: list[tuple[int, dict[str, Any], str]] = []
                package_digests: set[str] = set()
                for index, row in enumerate(rows):
                    try:
                        structure = json.loads(row["structure_json"])
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise StandardsForgeError("storage_error", "A stored structural record is invalid.") from exc
                    parent_logical_id = structure.get("parent_logical_id")
                    if isinstance(parent_logical_id, str) and parent_logical_id:
                        structural_matches.append((index, row, parent_logical_id))
                        package_digests.add(row["package_digest"])

                if not structural_matches:
                    for row in rows:
                        row["heading_ancestry"] = []
                    return rows

                package_placeholders = ",".join("?" for _ in package_digests)
                structural_rows = connection.execute(
                    f"""
                    SELECT package_digest, record_id, clause_reference, heading, structure_json
                    FROM records
                    WHERE package_digest IN ({package_placeholders}) AND structure_json <> '{{}}'
                    """,
                    sorted(package_digests),
                ).fetchall()
                structural_by_logical_id: dict[tuple[str, str], dict[str, Any]] = {}
                for parent_row in structural_rows:
                    try:
                        structure = json.loads(parent_row["structure_json"])
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise StandardsForgeError("storage_error", "A stored structural record is invalid.") from exc
                    logical_id = structure.get("logical_id")
                    if isinstance(logical_id, str) and logical_id:
                        structural_by_logical_id[(parent_row["package_digest"], logical_id)] = {
                            "record_id": parent_row["record_id"],
                            "clause_reference": parent_row["clause_reference"],
                            "heading": parent_row["heading"],
                            "parent_logical_id": structure.get("parent_logical_id"),
                        }

                for index, row, parent_logical_id in structural_matches:
                    lineage: list[dict[str, str]] = []
                    visited = {row["record_id"]}
                    next_logical_id: str | None = parent_logical_id
                    while next_logical_id is not None:
                        parent = structural_by_logical_id.get((row["package_digest"], next_logical_id))
                        if parent is None:
                            raise StandardsForgeError(
                                "storage_error",
                                "A stored structural parent is unavailable.",
                                {"record_id": row["record_id"], "parent_logical_id": next_logical_id},
                            )
                        if parent["record_id"] in visited:
                            raise StandardsForgeError(
                                "storage_error",
                                "The stored structural ancestry contains a cycle.",
                                {"record_id": row["record_id"]},
                            )
                        visited.add(parent["record_id"])
                        lineage.append(
                            {
                                "record_id": parent["record_id"],
                                "clause_reference": parent["clause_reference"],
                                "heading": parent["heading"],
                            }
                        )
                        parent_logical_id = parent["parent_logical_id"]
                        if parent_logical_id is not None and not isinstance(parent_logical_id, str):
                            raise StandardsForgeError(
                                "storage_error",
                                "A stored structural parent identity is invalid.",
                                {"record_id": parent["record_id"]},
                            )
                        next_logical_id = parent_logical_id
                    row["heading_ancestry"] = list(reversed(lineage))
                for row in rows:
                    row.setdefault("heading_ancestry", [])
                return rows
        except sqlite3.Error as exc:
            raise StandardsForgeError("search_error", "The lexical query could not be evaluated.") from exc

    def revoke(self, principal_id: str, package_digest: str) -> bool:
        revoked_at = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE grants SET can_serve = 0, revoked_at = ? WHERE principal_id = ? AND package_digest = ?",
                (revoked_at, principal_id, package_digest),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    "UPDATE metadata SET value = CAST(value AS INTEGER) + 1 WHERE key = 'authorization_generation'"
                )
        return cursor.rowcount == 1

    def active_grants_for_pack_ids(self, principal_id: str, pack_ids: list[str]) -> list[dict[str, str]]:
        if not pack_ids:
            return []
        placeholders = ",".join("?" for _ in pack_ids)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT p.pack_id, p.package_digest
                FROM packages p
                JOIN grants g ON g.package_digest = p.package_digest
                WHERE g.principal_id = ?
                  AND g.can_serve = 1
                  AND g.revoked_at IS NULL
                  AND p.pack_id IN ({placeholders})
                ORDER BY p.pack_id, p.package_digest
                """,
                (principal_id, *pack_ids),
            ).fetchall()
        return [
            {"pack_id": row["pack_id"], "package_digest": row["package_digest"]}
            for row in rows
        ]
