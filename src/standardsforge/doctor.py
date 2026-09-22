from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import platform
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .errors import StandardsForgeError
from .pack import validate_pack_directory
from .policy import load_policy
from .service import StandardsForgeService
from .store import SCHEMA_VERSION


_REQUIRED_TABLES = {"metadata", "packages", "grants", "records", "dependencies", "records_fts"}
_REQUIRED_INDEXES = {"packages_identity_idx", "records_clause_idx", "records_role_scope_idx"}
_REQUIRED_TRIGGERS = {"records_fts_ai", "records_fts_ad", "records_fts_au"}
_REQUIRED_METADATA = {"schema_version", "cursor_secret", "corpus_generation", "authorization_generation"}
_EXPECTED_MCP_VERSION = "2.2.0"


def _detail(**values: Any) -> list[dict[str, Any]]:
    return [{"name": key, "value": value} for key, value in values.items()]


def _check(
    check_id: str,
    severity: str,
    status: str,
    code: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "severity": severity,
        "status": status,
        "code": code,
        "message": message,
        "details": _detail(**details),
    }


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _fts5_available() -> bool:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE doctor_fts USING fts5(value)")
        return True
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def _safe_object_path(root: Path, stored: str, digest: str) -> bool:
    candidate = Path(stored)
    expected = root / digest
    try:
        return (
            candidate.is_dir()
            and not candidate.is_symlink()
            and candidate.resolve(strict=True) == expected.resolve(strict=True)
            and candidate.resolve(strict=True).is_relative_to(root)
        )
    except OSError:
        return False


def run_doctor(
    db_path: str | Path,
    object_root: str | Path,
    *,
    policy_path: str | Path | None = None,
    principal_id: str | None = None,
    full_integrity: bool = False,
    require_mcp: bool = False,
) -> dict[str, Any]:
    database = Path(db_path).resolve(strict=False)
    object_store = Path(object_root).resolve(strict=False)
    mode = "full_integrity" if full_integrity else "quick"
    checks: list[dict[str, Any]] = []

    python_supported = sys.version_info >= (3, 11)
    checks.append(
        _check(
            "runtime.python",
            "required",
            "pass" if python_supported else "fail",
            "python_supported" if python_supported else "python_version_unsupported",
            "Python meets the supported minimum." if python_supported else "Python 3.11 or newer is required.",
            actual=platform.python_version(),
            minimum="3.11",
        )
    )
    fts5 = _fts5_available()
    checks.append(
        _check(
            "runtime.sqlite_fts5",
            "required",
            "pass" if fts5 else "fail",
            "sqlite_fts5_available" if fts5 else "sqlite_fts5_unavailable",
            "SQLite FTS5 is available." if fts5 else "SQLite FTS5 is unavailable.",
            sqlite_version=sqlite3.sqlite_version,
        )
    )

    database_exists = database.is_file() and not database.is_symlink()
    checks.append(
        _check(
            "state.database",
            "required",
            "pass" if database_exists else "fail",
            "database_present" if database_exists else "database_not_found",
            "The database is an existing regular file." if database_exists else "The database is missing, not a regular file, or a symbolic link.",
            path=str(database),
        )
    )
    store_exists = object_store.is_dir() and not object_store.is_symlink()
    checks.append(
        _check(
            "state.object_store",
            "required",
            "pass" if store_exists else "fail",
            "object_store_present" if store_exists else "object_store_not_found",
            "The object store is an existing directory." if store_exists else "The object store is missing, not a directory, or a symbolic link.",
            path=str(object_store),
        )
    )

    schema_version: int | None = None
    package_rows: list[sqlite3.Row] = []
    grant_rows: list[sqlite3.Row] = []
    record_rows: list[sqlite3.Row] = []
    database_usable = False
    if database_exists:
        try:
            connection = _readonly_connection(database)
            try:
                quick_rows = connection.execute("PRAGMA quick_check").fetchall()
                foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
                objects = connection.execute(
                    "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'view', 'index', 'trigger')"
                ).fetchall()
                names_by_type = {
                    kind: {str(row["name"]) for row in objects if row["type"] == kind}
                    for kind in ("table", "view", "index", "trigger")
                }
                missing_tables = sorted(_REQUIRED_TABLES - (names_by_type["table"] | names_by_type["view"]))
                missing_indexes = sorted(_REQUIRED_INDEXES - names_by_type["index"])
                missing_triggers = sorted(_REQUIRED_TRIGGERS - names_by_type["trigger"])
                metadata_rows = (
                    connection.execute("SELECT key, value FROM metadata ORDER BY key").fetchall()
                    if "metadata" in names_by_type["table"]
                    else []
                )
                metadata = {str(row["key"]): str(row["value"]) for row in metadata_rows}
                missing_metadata = sorted(_REQUIRED_METADATA - set(metadata))
                try:
                    schema_version = int(metadata["schema_version"])
                except (KeyError, TypeError, ValueError):
                    schema_version = None
                cursor_secret_valid = re.fullmatch(r"[0-9a-f]{64}", metadata.get("cursor_secret", "")) is not None
                quick_ok = bool(quick_rows) and all(str(row[0]) == "ok" for row in quick_rows)
                database_usable = (
                    quick_ok
                    and not foreign_key_rows
                    and not missing_tables
                    and not missing_indexes
                    and not missing_triggers
                    and not missing_metadata
                    and cursor_secret_valid
                    and schema_version == SCHEMA_VERSION
                )
                if database_usable:
                    connection.execute("SELECT rowid FROM records_fts WHERE records_fts MATCH ? LIMIT 1", ("doctor",)).fetchall()
                    package_rows = connection.execute(
                        "SELECT package_digest, pack_id, object_path, rights_json FROM packages ORDER BY package_digest"
                    ).fetchall()
                    grant_rows = connection.execute(
                        "SELECT principal_id, package_digest, can_serve, policy_id, policy_fingerprint, revoked_at FROM grants ORDER BY principal_id, package_digest"
                    ).fetchall()
                    record_rows = connection.execute(
                        "SELECT package_digest, record_id, clause_reference, ordinal FROM records ORDER BY package_digest, ordinal, record_id"
                    ).fetchall()
                checks.append(
                    _check(
                        "state.database_schema",
                        "required",
                        "pass" if database_usable else "fail",
                        "database_schema_current" if database_usable else "database_schema_invalid",
                        "The database passed read-only integrity and schema checks." if database_usable else "The database failed an integrity, schema-object, metadata, or version check.",
                        schema_version=schema_version,
                        supported_schema_version=SCHEMA_VERSION,
                        missing_tables=missing_tables,
                        missing_indexes=missing_indexes,
                        missing_triggers=missing_triggers,
                        missing_metadata=missing_metadata,
                        quick_check="ok" if quick_ok else "failed",
                        foreign_key_violation_count=len(foreign_key_rows),
                        cursor_secret_valid=cursor_secret_valid,
                    )
                )
            finally:
                connection.close()
        except sqlite3.Error as exc:
            database_usable = False
            checks.append(
                _check(
                    "state.database_schema",
                    "required",
                    "fail",
                    "database_read_failed",
                    "The database could not be inspected read-only.",
                    error_type=type(exc).__name__,
                )
            )
    else:
        checks.append(
            _check(
                "state.database_schema",
                "required",
                "not_checked",
                "database_unavailable",
                "Database schema was not checked because no safe database file is available.",
            )
        )

    package_count = len(package_rows) if database_usable else None
    packages_present = database_usable and bool(package_rows)
    checks.append(
        _check(
            "state.installed_packages",
            "required",
            "pass" if packages_present else ("fail" if database_usable else "not_checked"),
            "packages_installed" if packages_present else ("no_installed_packages" if database_usable else "database_unavailable"),
            "At least one package is installed." if packages_present else "No installed package could be confirmed.",
            installed_package_count=package_count,
        )
    )

    effective_principal = principal_id.strip() if isinstance(principal_id, str) and principal_id.strip() else None
    policy = None
    if policy_path is None:
        checks.append(
            _check(
                "authorization.policy",
                "required",
                "fail",
                "policy_not_supplied",
                "A trusted local policy is required to establish serving readiness.",
            )
        )
    else:
        try:
            policy = load_policy(policy_path)
        except StandardsForgeError as exc:
            checks.append(_check("authorization.policy", "required", "fail", exc.code, "The supplied trusted policy is invalid."))
        else:
            policy_ok = effective_principal is not None and effective_principal == policy.principal_id and policy.allow_serve
            code = "policy_valid"
            if effective_principal is None:
                code = "principal_not_selected"
            elif effective_principal != policy.principal_id:
                code = "policy_principal_mismatch"
            elif not policy.allow_serve:
                code = "policy_serve_denied"
            checks.append(
                _check(
                    "authorization.policy",
                    "required",
                    "pass" if policy_ok else "fail",
                    code,
                    "The supplied policy is valid, principal-bound, and permits serving." if policy_ok else "The supplied policy does not establish serving authority for the selected principal.",
                    selected_principal=effective_principal,
                    policy_principal=policy.principal_id,
                    policy_id=policy.policy_id,
                    policy_fingerprint=policy.fingerprint,
                    allow_serve=policy.allow_serve,
                )
            )

    active_grants = [row for row in grant_rows if int(row["can_serve"]) == 1 and row["revoked_at"] is None] if database_usable else []
    principal_grants = [row for row in active_grants if row["principal_id"] == effective_principal]
    revoked_principal_grants = [
        row for row in grant_rows if row["principal_id"] == effective_principal and row["revoked_at"] is not None
    ] if effective_principal is not None else []
    package_by_digest = {str(row["package_digest"]): row for row in package_rows}
    matching_grants: list[sqlite3.Row] = []
    grant_mismatches: list[str] = []
    if database_usable and effective_principal is not None and policy is not None:
        principal_grants_by_digest = {
            str(row["package_digest"]): row
            for row in grant_rows
            if row["principal_id"] == effective_principal
        }
        policy_scope_packages = [
            row for row in package_rows if row["pack_id"] in policy.allowed_pack_ids
        ]
        for package in policy_scope_packages:
            digest = str(package["package_digest"])
            grant = principal_grants_by_digest.get(digest)
            mismatch_codes: list[str] = []
            if grant is None:
                mismatch_codes.append("grant_missing")
            else:
                if int(grant["can_serve"]) != 1 or grant["revoked_at"] is not None:
                    mismatch_codes.append("grant_revoked")
                if grant["policy_id"] != policy.policy_id:
                    mismatch_codes.append("policy_id")
                if grant["policy_fingerprint"] != policy.fingerprint:
                    mismatch_codes.append("policy_fingerprint")
            try:
                content_class = json.loads(package["rights_json"])["content_class"]
            except (KeyError, TypeError, json.JSONDecodeError):
                mismatch_codes.append("rights_invalid")
            else:
                if content_class not in policy.allowed_content_classes:
                    mismatch_codes.append("content_class_not_allowed")
            if mismatch_codes:
                grant_mismatches.extend(f"{digest}:{code}" for code in mismatch_codes)
            elif grant is not None:
                matching_grants.append(grant)

    if not database_usable:
        grant_status, grant_code = "not_checked", "database_unavailable"
    elif effective_principal is None:
        grant_status, grant_code = "fail", "principal_not_selected"
    elif policy is None:
        grant_status, grant_code = "not_checked", "policy_unavailable"
    elif matching_grants and not grant_mismatches:
        grant_status, grant_code = "pass", "principal_grants_ready"
    else:
        grant_status, grant_code = "fail", "principal_grants_not_ready"
    checks.append(
        _check(
            "authorization.grants",
            "required",
            grant_status,
            grant_code,
            "Every active grant for the selected principal matches the current trusted policy." if grant_status == "pass" else "Active grants could not be proven ready under the current trusted policy.",
            selected_principal=effective_principal,
            active_grant_count=len(principal_grants),
            revoked_grant_count=len(revoked_principal_grants),
            matching_grant_count=len(matching_grants),
            unrelated_active_grant_count=len(principal_grants) - len(matching_grants),
            grant_mismatches=sorted(grant_mismatches),
        )
    )

    selected_digest = min((str(row["package_digest"]) for row in matching_grants), default=None)
    failed_digests: list[str] = []
    validated_packages = 0
    validated_digests: set[str] = set()
    if database_usable and store_exists and package_rows:
        root = object_store.resolve(strict=True)
        structural_failures = {
            str(row["package_digest"])
            for row in package_rows
            if not _safe_object_path(root, str(row["object_path"]), str(row["package_digest"]))
        }
        if full_integrity:
            rows_to_validate = package_rows
        elif selected_digest is not None:
            rows_to_validate = [package_by_digest[selected_digest]]
        else:
            rows_to_validate = []
        for row in rows_to_validate:
            digest = str(row["package_digest"])
            if digest in structural_failures:
                continue
            try:
                pack = validate_pack_directory(root / digest)
                if pack.package_digest != digest or pack.manifest["pack_id"] != row["pack_id"]:
                    structural_failures.add(digest)
                else:
                    validated_packages += 1
                    validated_digests.add(digest)
            except (StandardsForgeError, OSError):
                structural_failures.add(digest)
        failed_digests = sorted(structural_failures)
        integrity_complete = full_integrity and validated_packages == len(package_rows) and not failed_digests
        integrity_passed = bool(rows_to_validate) and not failed_digests and validated_packages == len(rows_to_validate)
        checks.append(
            _check(
                "integrity.packages",
                "required",
                "pass" if integrity_passed else "fail",
                "package_integrity_valid" if integrity_passed else "package_object_invalid",
                "Installed object paths are safe and the requested package-integrity coverage passed." if integrity_passed else "An installed object path or requested package failed validation.",
                total_packages=len(package_rows),
                validated_packages=validated_packages,
                integrity_complete=integrity_complete,
                failed_package_digests=failed_digests,
            )
        )
    else:
        integrity_complete = False
        checks.append(
            _check(
                "integrity.packages",
                "required",
                "not_checked",
                "package_integrity_unavailable",
                "Package integrity was not checked because usable installed state is unavailable.",
                total_packages=package_count,
                validated_packages=0,
            )
        )

    selected_record = next((row for row in record_rows if row["package_digest"] == selected_digest), None)
    query_smoke: dict[str, Any] = {
        "status": "not_checked",
        "package_digest": selected_digest,
        "record_id": str(selected_record["record_id"]) if selected_record is not None else None,
        "clause_reference": str(selected_record["clause_reference"]) if selected_record is not None else None,
        "evidence_count": None,
        "required_relationship_count": None,
        "source_verification": "not_performed",
        "final_authorization": "not_performed",
        "error_code": None,
    }
    if (
        effective_principal is not None
        and selected_digest is not None
        and selected_digest in validated_digests
        and selected_record is not None
        and grant_status == "pass"
    ):
        try:
            service = StandardsForgeService.open_read_only(database, object_store)
            packet = service.get_clause(
                selected_digest,
                str(selected_record["clause_reference"]),
                effective_principal,
                record_id=str(selected_record["record_id"]),
            )
        except StandardsForgeError as exc:
            query_smoke["status"] = "fail"
            query_smoke["error_code"] = exc.code
        else:
            query_smoke.update(
                {
                    "status": "pass",
                    "evidence_count": len(packet["evidence"]),
                    "required_relationship_count": len(packet["required_relationships"]),
                    "source_verification": "performed",
                    "final_authorization": "performed",
                }
            )
    query_ok = query_smoke["status"] == "pass"
    checks.append(
        _check(
            "query.exact_clause",
            "required",
            query_smoke["status"],
            "query_smoke_passed" if query_ok else (query_smoke["error_code"] or "query_smoke_unavailable"),
            "The real read-only query path returned source-verified evidence and reauthorized the package." if query_ok else "The real read-only query path did not establish readiness.",
            package_digest=query_smoke["package_digest"],
            record_id=query_smoke["record_id"],
            error_code=query_smoke["error_code"],
        )
    )

    mcp_installed = importlib.util.find_spec("mcp") is not None
    mcp_version: str | None = None
    mcp_importable = False
    mcp_code = "mcp_not_installed"
    if mcp_installed:
        try:
            mcp_version = importlib.metadata.version("mcp")
            importlib.import_module("standardsforge.mcp_server")
            mcp_importable = True
            mcp_code = "mcp_available" if mcp_version == _EXPECTED_MCP_VERSION else "mcp_version_mismatch"
        except Exception:
            mcp_code = "mcp_import_failed"
    mcp_ok = mcp_installed and mcp_importable and mcp_version == _EXPECTED_MCP_VERSION
    checks.append(
        _check(
            "optional.mcp",
            "required" if require_mcp else "advisory",
            "pass" if mcp_ok else "fail",
            mcp_code,
            "The pinned MCP adapter dependency is importable." if mcp_ok else ("The MCP adapter is required but unavailable or incompatible." if require_mcp else "The optional MCP adapter is unavailable or incompatible; core CLI reads remain supported."),
            installed=mcp_installed,
            importable=mcp_importable,
            installed_version=mcp_version,
            expected_version=_EXPECTED_MCP_VERSION,
        )
    )

    ready = all(check["status"] == "pass" for check in checks if check["severity"] == "required")
    summary = {
        "passed": sum(check["status"] == "pass" for check in checks),
        "failed": sum(check["status"] == "fail" for check in checks),
        "not_checked": sum(check["status"] == "not_checked" for check in checks),
        "required_failed_or_not_checked": sum(
            check["status"] != "pass" and check["severity"] == "required" for check in checks
        ),
    }
    return {
        "schema_version": "0.1.0",
        "operation": "doctor",
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "mode": mode,
        "mutation_mode": "read_only",
        "network_mode": "not_used",
        "request": {
            "principal_id": effective_principal,
            "policy_supplied": policy_path is not None,
            "require_mcp": require_mcp,
        },
        "runtime": {
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
            "standardsforge_version": __version__,
        },
        "state": {
            "database_path": str(database),
            "object_store_path": str(object_store),
            "database_exists": database_exists,
            "object_store_exists": store_exists,
            "database_schema_version": schema_version,
            "installed_package_count": package_count,
            "active_grant_count": len(active_grants) if database_usable else None,
            "selected_principal_active_grant_count": len(principal_grants) if database_usable and effective_principal is not None else None,
        },
        "integrity": {
            "requested_mode": mode,
            "complete": integrity_complete,
            "total_packages": package_count,
            "validated_packages": validated_packages,
            "failed_package_digests": failed_digests,
        },
        "query_smoke": query_smoke,
        "checks": checks,
        "summary": summary,
        "limitations": [
            "Doctor is read-only and does not repair, migrate, install, revoke, fetch, or invoke a model.",
            "Quick mode fully validates the deterministic package used by the query smoke and checks every stored object path; use full_integrity to validate every installed package.",
            "A ready report establishes local runtime, store, policy, and exact-query readiness only, not source applicability, compliance, approval, semantic completeness, or MCP client-host configuration.",
        ],
    }
