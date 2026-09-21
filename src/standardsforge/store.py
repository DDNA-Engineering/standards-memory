from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from .errors import StandardsForgeError, require
from .identity import normalize_identifier
from .models import LocalPolicy, ValidatedPack
from .pack import validate_pack_directory


SCHEMA_VERSION = 2


class LocalStore:
    """SQLite metadata plus an immutable content-addressed object directory."""

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
                    CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
                        package_digest UNINDEXED,
                        record_id UNINDEXED,
                        clause_reference,
                        heading,
                        text,
                        tokenize='unicode61'
                    );
                    """
                )
                row = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
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
                    connection.execute("UPDATE metadata SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))
                elif int(row["value"]) != SCHEMA_VERSION:
                    raise StandardsForgeError("unsupported_database_version", "The local database schema is unsupported.")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS records_role_scope_idx ON records(package_digest, statement_role, clause_reference, ordinal)"
                )
                cursor_secret = connection.execute("SELECT value FROM metadata WHERE key = 'cursor_secret'").fetchone()
                if cursor_secret is None:
                    connection.execute("INSERT INTO metadata(key, value) VALUES('cursor_secret', ?)", (secrets.token_hex(32),))
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
            try:
                os.replace(staging, destination)
            except FileExistsError:
                existing = validate_pack_directory(destination)
                require(existing.package_digest == pack.package_digest, "object_store_conflict", "Concurrent object install conflicted.")
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
                                heading, text, source_json, statement_role, derivation_json, ordinal
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                                ordinal,
                            ),
                        )
                        connection.execute(
                            "INSERT INTO records_fts(package_digest, record_id, clause_reference, heading, text) VALUES (?, ?, ?, ?, ?)",
                            (pack.package_digest, record["record_id"], record["clause_reference"], record["heading"], record["text"]),
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
                WHERE package_digest = ? AND clause_reference = ? AND kind = 'clause'
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

    def search(self, principal_id: str, fts_query: str, limit: int) -> list[sqlite3.Row]:
        try:
            with self._connection() as connection:
                return list(
                    connection.execute(
                        """
                        SELECT p.package_digest, p.edition_id, p.identifier, p.title,
                               r.record_id, r.kind, r.clause_reference, r.heading,
                               bm25(records_fts, 0.0, 0.0, 3.0, 1.0, 1.0) AS score
                        FROM records_fts
                        JOIN records r
                          ON r.package_digest = records_fts.package_digest
                         AND r.record_id = records_fts.record_id
                        JOIN packages p ON p.package_digest = r.package_digest
                        JOIN grants g ON g.package_digest = p.package_digest
                        WHERE records_fts MATCH ? AND g.principal_id = ?
                          AND g.can_serve = 1 AND g.revoked_at IS NULL
                        ORDER BY score, p.package_digest, r.ordinal
                        LIMIT ?
                        """,
                        (fts_query, principal_id, limit),
                    )
                )
        except sqlite3.Error as exc:
            raise StandardsForgeError("search_error", "The lexical query could not be evaluated.") from exc

    def revoke(self, principal_id: str, package_digest: str) -> bool:
        revoked_at = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE grants SET can_serve = 0, revoked_at = ? WHERE principal_id = ? AND package_digest = ?",
                (revoked_at, principal_id, package_digest),
            )
        return cursor.rowcount == 1
