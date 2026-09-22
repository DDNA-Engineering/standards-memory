from __future__ import annotations

import hashlib
import io
import json
import socket
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from jsonschema import ValidationError
from jsonschema.validators import validator_for


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.cli import main  # noqa: E402
from standardsforge.doctor import run_doctor  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402


PACKS = [
    ROOT / "examples" / "packs" / "fictional-adapter-v1",
    ROOT / "examples" / "packs" / "fictional-adapter-v2",
]
POLICY = ROOT / "examples" / "policies" / "local-synthetic.json"
DOCTOR_SCHEMA = json.loads((ROOT / "contracts" / "doctor-response.schema.json").read_text(encoding="utf-8"))
DOCTOR_VALIDATOR = validator_for(DOCTOR_SCHEMA)(DOCTOR_SCHEMA)


def _snapshot_tree(root: Path) -> dict[str, tuple[int, int, str] | tuple[int, int, None]]:
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[int, int, str] | tuple[int, int, None]] = {}
    for path in sorted([root, *root.rglob("*")]):
        relative = path.relative_to(root).as_posix() if path != root else "."
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        snapshot[relative] = (stat.st_size, stat.st_mtime_ns, digest)
    return snapshot


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-doctor-")
        self.base = Path(self.temp.name)
        self.db = self.base / "memory.db"
        self.objects = self.base / "objects"
        service = StandardsForgeService(self.db, self.objects)
        self.installed = [service.install_pack(pack, POLICY) for pack in PACKS]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *, full: bool = False, policy: Path = POLICY, principal: str = "local-user") -> dict:
        return run_doctor(
            self.db,
            self.objects,
            policy_path=policy,
            principal_id=principal,
            full_integrity=full,
        )

    def test_ready_quick_report_is_contract_valid_offline_and_non_mutating(self) -> None:
        before_db = _snapshot_tree(self.db.parent)
        with patch.object(socket, "socket", side_effect=AssertionError("network access attempted")):
            report = self._run()
        after_db = _snapshot_tree(self.db.parent)

        DOCTOR_VALIDATOR.validate(report)
        self.assertTrue(report["ready"])
        self.assertEqual("ready", report["status"])
        self.assertEqual("read_only", report["mutation_mode"])
        self.assertEqual("not_used", report["network_mode"])
        self.assertEqual(2, report["integrity"]["total_packages"])
        self.assertEqual(1, report["integrity"]["validated_packages"])
        self.assertFalse(report["integrity"]["complete"])
        self.assertEqual("pass", report["query_smoke"]["status"])
        self.assertEqual("performed", report["query_smoke"]["source_verification"])
        self.assertEqual(len(report["checks"]), sum(report["summary"][key] for key in ("passed", "failed", "not_checked")))
        self.assertEqual(0, report["summary"]["required_failed_or_not_checked"])
        self.assertEqual(before_db, after_db)

    def test_full_integrity_validates_every_package(self) -> None:
        report = self._run(full=True)
        DOCTOR_VALIDATOR.validate(report)
        self.assertTrue(report["ready"])
        self.assertEqual("full_integrity", report["mode"])
        self.assertEqual(2, report["integrity"]["validated_packages"])
        self.assertTrue(report["integrity"]["complete"])

    def test_uninitialized_paths_remain_absent_and_report_all_failures(self) -> None:
        missing = self.base / "missing"
        db = missing / "state.db"
        objects = missing / "objects"
        report = run_doctor(db, objects, policy_path=POLICY, principal_id="local-user")

        DOCTOR_VALIDATOR.validate(report)
        self.assertFalse(report["ready"])
        self.assertFalse(missing.exists())
        self.assertGreaterEqual(report["summary"]["required_failed_or_not_checked"], 4)
        self.assertEqual("not_checked", report["query_smoke"]["status"])

    def test_tampered_source_and_missing_object_are_reported(self) -> None:
        selected = min(item["package_digest"] for item in self.installed)
        source = next((self.objects / selected / "sources").iterdir())
        source.write_bytes(source.read_bytes() + b"tamper")
        tampered = self._run(full=True)
        self.assertFalse(tampered["ready"])
        self.assertIn(selected, tampered["integrity"]["failed_package_digests"])

        source.unlink()
        missing = self._run(full=True)
        self.assertFalse(missing["ready"])
        self.assertIn(selected, missing["integrity"]["failed_package_digests"])

    def test_unsupported_schema_is_not_migrated(self) -> None:
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE metadata SET value = '999' WHERE key = 'schema_version'")
        before = self.db.read_bytes()
        report = self._run()
        after = self.db.read_bytes()

        self.assertFalse(report["ready"])
        self.assertEqual(999, report["state"]["database_schema_version"])
        self.assertEqual(before, after)
        schema_check = next(item for item in report["checks"] if item["check_id"] == "state.database_schema")
        self.assertEqual("database_schema_invalid", schema_check["code"])

    def test_policy_drift_wrong_principal_and_path_escape_fail_closed(self) -> None:
        drifted = json.loads(POLICY.read_text(encoding="utf-8"))
        drifted["policy_id"] = "replacement-policy"
        drifted_path = self.base / "drifted-policy.json"
        drifted_path.write_text(json.dumps(drifted), encoding="utf-8")
        report = self._run(policy=drifted_path)
        self.assertFalse(report["ready"])
        grant = next(item for item in report["checks"] if item["check_id"] == "authorization.grants")
        self.assertEqual("principal_grants_not_ready", grant["code"])

        wrong_principal = self._run(principal="other-user")
        self.assertFalse(wrong_principal["ready"])
        policy_check = next(item for item in wrong_principal["checks"] if item["check_id"] == "authorization.policy")
        self.assertEqual("policy_principal_mismatch", policy_check["code"])

        selected = min(item["package_digest"] for item in self.installed)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute(
                "UPDATE packages SET object_path = ? WHERE package_digest = ?",
                (str(self.base), selected),
            )
        escaped = self._run(full=True)
        self.assertFalse(escaped["ready"])
        self.assertIn(selected, escaped["integrity"]["failed_package_digests"])

    def test_mcp_is_advisory_unless_required(self) -> None:
        with patch("standardsforge.doctor.importlib.util.find_spec", return_value=None):
            optional = self._run()
            required = run_doctor(
                self.db,
                self.objects,
                policy_path=POLICY,
                principal_id="local-user",
                require_mcp=True,
            )
        self.assertTrue(optional["ready"])
        self.assertFalse(required["ready"])
        optional_check = next(item for item in optional["checks"] if item["check_id"] == "optional.mcp")
        required_check = next(item for item in required["checks"] if item["check_id"] == "optional.mcp")
        self.assertEqual("advisory", optional_check["severity"])
        self.assertEqual("required", required_check["severity"])

    def test_revoked_policy_scope_grant_is_not_ready(self) -> None:
        selected = min(item["package_digest"] for item in self.installed)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute(
                "UPDATE grants SET can_serve = 0, revoked_at = '2026-09-22T00:00:00Z' WHERE principal_id = ? AND package_digest = ?",
                ("local-user", selected),
            )
        report = self._run()
        self.assertFalse(report["ready"])
        grant = next(item for item in report["checks"] if item["check_id"] == "authorization.grants")
        mismatches = next(detail["value"] for detail in grant["details"] if detail["name"] == "grant_mismatches")
        self.assertIn(f"{selected}:grant_revoked", mismatches)

    def test_cli_uses_completed_not_ready_exit_without_error_envelope(self) -> None:
        ready_stdout, ready_stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(ready_stdout), redirect_stderr(ready_stderr):
            ready_code = main(
                [
                    "--db", str(self.db),
                    "--store", str(self.objects),
                    "doctor",
                    "--policy", str(POLICY),
                    "--principal", "local-user",
                ]
            )
        self.assertEqual(0, ready_code)
        self.assertEqual("", ready_stderr.getvalue())
        self.assertTrue(json.loads(ready_stdout.getvalue())["result"]["ready"])

        missing_stdout, missing_stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(missing_stdout), redirect_stderr(missing_stderr):
            missing_code = main(
                [
                    "--db", str(self.base / "absent.db"),
                    "--store", str(self.base / "absent-objects"),
                    "doctor",
                    "--policy", str(POLICY),
                    "--principal", "local-user",
                ]
            )
        self.assertEqual(3, missing_code)
        self.assertEqual("", missing_stderr.getvalue())
        envelope = json.loads(missing_stdout.getvalue())
        self.assertTrue(envelope["ok"])
        self.assertFalse(envelope["result"]["ready"])

    def test_read_only_service_rejects_mutation_and_schema_rejects_unknown_fields(self) -> None:
        service = StandardsForgeService.open_read_only(self.db, self.objects)
        with self.assertRaises(StandardsForgeError) as caught:
            service.revoke(self.installed[0]["package_digest"], "local-user")
        self.assertEqual("read_only_store", caught.exception.code)

        invalid = self._run()
        invalid["unexpected"] = True
        with self.assertRaises(ValidationError):
            DOCTOR_VALIDATOR.validate(invalid)


if __name__ == "__main__":
    unittest.main()
