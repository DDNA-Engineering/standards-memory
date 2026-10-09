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

    def test_missing_or_non_porter_natural_index_is_not_ready_or_repaired(self) -> None:
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("DROP TABLE records_natural_fts")
        missing_before = self.db.read_bytes()
        missing = self._run()
        self.assertFalse(missing["ready"])
        self.assertEqual(missing_before, self.db.read_bytes())

        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute(
                """
                CREATE VIRTUAL TABLE records_natural_fts USING fts5(
                    package_digest UNINDEXED, record_id UNINDEXED, heading, text,
                    content='records', content_rowid='rowid', tokenize='unicode61'
                )
                """
            )
            connection.execute("INSERT INTO records_natural_fts(records_natural_fts) VALUES('rebuild')")
        malformed_before = self.db.read_bytes()
        malformed = self._run()
        self.assertFalse(malformed["ready"])
        self.assertEqual(malformed_before, self.db.read_bytes())
        schema_check = next(
            item for item in malformed["checks"] if item["check_id"] == "state.database_schema"
        )
        natural_valid = next(
            detail["value"] for detail in schema_check["details"] if detail["name"] == "natural_fts_valid"
        )
        self.assertFalse(natural_valid)

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

    def test_active_grant_outside_narrowed_policy_fails_readiness(self) -> None:
        narrowed = json.loads(POLICY.read_text(encoding="utf-8"))
        narrowed["policy_id"] = "narrowed"
        narrowed["allowed_pack_ids"] = ["example.vehicle-adapter.2.0"]
        narrowed_path = self.base / "narrowed-policy.json"
        narrowed_path.write_text(json.dumps(narrowed), encoding="utf-8")
        temp = tempfile.TemporaryDirectory(prefix="standardsforge-doctor-narrowed-")
        self.addCleanup(temp.cleanup)
        db, objects = Path(temp.name) / "memory.db", Path(temp.name) / "objects"
        service = StandardsForgeService(db, objects)
        outside = service.install_pack(PACKS[0], POLICY)["package_digest"]
        service.install_pack(PACKS[1], narrowed_path)

        report = run_doctor(db, objects, policy_path=narrowed_path, principal_id="local-user")
        DOCTOR_VALIDATOR.validate(report)
        self.assertFalse(report["ready"])
        grant = next(item for item in report["checks"] if item["check_id"] == "authorization.grants")
        details = {detail["name"]: detail["value"] for detail in grant["details"]}
        self.assertEqual(("fail", "grants_outside_policy"), (grant["status"], grant["code"]))
        self.assertEqual([outside], details["grants_outside_policy"])
        self.assertEqual(1, details["unrelated_active_grant_count"])
        self.assertEqual(1, details["matching_grant_count"])
        self.assertEqual([], details["grant_mismatches"])
        self.assertNotIn("matches the current trusted policy", grant["message"])
        # The still-active grant is genuinely served, which is why readiness must fail.
        served = StandardsForgeService.open_read_only(db, objects).get_clause(outside, "4.2.1", "local-user")
        self.assertEqual("example.vehicle-adapter.1.0", served["package"]["pack_id"])

        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "--db", str(db),
                    "--store", str(objects),
                    "doctor",
                    "--policy", str(narrowed_path),
                    "--principal", "local-user",
                ]
            )
        self.assertEqual(3, code)
        self.assertEqual("", stderr.getvalue())

        service.revoke(outside, "local-user")
        revoked = run_doctor(db, objects, policy_path=narrowed_path, principal_id="local-user")
        self.assertTrue(revoked["ready"])
        grant = next(item for item in revoked["checks"] if item["check_id"] == "authorization.grants")
        self.assertEqual("principal_grants_ready", grant["code"])
        details = {detail["name"]: detail["value"] for detail in grant["details"]}
        self.assertEqual([], details["grants_outside_policy"])

    def test_grants_from_several_one_pack_policies_are_ready_only_with_every_policy(self) -> None:
        base = json.loads(POLICY.read_text(encoding="utf-8"))
        paths = []
        for index, pack_id in enumerate(("example.vehicle-adapter.1.0", "example.vehicle-adapter.2.0"), start=1):
            path = self.base / f"one-pack-{index}.json"
            path.write_text(json.dumps({**base, "policy_id": f"one-pack-{index}", "allowed_pack_ids": [pack_id]}), encoding="utf-8")
            paths.append(path)
        temp = tempfile.TemporaryDirectory(prefix="standardsforge-doctor-multi-")
        self.addCleanup(temp.cleanup)
        db, objects = Path(temp.name) / "memory.db", Path(temp.name) / "objects"
        service = StandardsForgeService(db, objects)
        first = service.install_pack(PACKS[0], paths[0])["package_digest"]
        service.install_pack(PACKS[1], paths[1])

        single = run_doctor(db, objects, policy_path=paths[0], principal_id="local-user")
        DOCTOR_VALIDATOR.validate(single)
        self.assertFalse(single["ready"])
        checks = {item["check_id"]: item for item in single["checks"]}
        self.assertEqual("grants_outside_policy", checks["authorization.grants"]["code"])

        both = run_doctor(db, objects, policy_path=paths, principal_id="local-user")
        DOCTOR_VALIDATOR.validate(both)
        self.assertTrue(both["ready"])
        checks = {item["check_id"]: item for item in both["checks"]}
        policy_details = {detail["name"]: detail["value"] for detail in checks["authorization.policy"]["details"]}
        self.assertEqual(["one-pack-1", "one-pack-2"], policy_details["policy_ids"])
        grant_details = {detail["name"]: detail["value"] for detail in checks["authorization.grants"]["details"]}
        self.assertEqual(2, grant_details["matching_grant_count"])

        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "--db", str(db), "--store", str(objects), "doctor",
                    "--policy", str(paths[0]), "--policy", str(paths[1]),
                    "--principal", "local-user",
                ]
            )
        self.assertEqual(0, code, stdout.getvalue())

        # A grant must match the policy that issued it, not merely any policy naming the pack.
        swapped = self.base / "swapped.json"
        swapped.write_text(json.dumps({**base, "policy_id": "one-pack-3", "allowed_pack_ids": ["example.vehicle-adapter.1.0"]}), encoding="utf-8")
        mismatch = run_doctor(db, objects, policy_path=[swapped, paths[1]], principal_id="local-user")
        self.assertFalse(mismatch["ready"])
        grant_details = {
            detail["name"]: detail["value"]
            for detail in next(item for item in mismatch["checks"] if item["check_id"] == "authorization.grants")["details"]
        }
        self.assertEqual([f"{first}:policy_id"], grant_details["grant_mismatches"])

        conflict = self.base / "conflict.json"
        conflict.write_text(json.dumps({**base, "policy_id": "one-pack-1", "allowed_pack_ids": ["example.vehicle-adapter.2.0"]}), encoding="utf-8")
        conflicted = run_doctor(db, objects, policy_path=[paths[0], conflict], principal_id="local-user")
        DOCTOR_VALIDATOR.validate(conflicted)
        self.assertFalse(conflicted["ready"])
        checks = {item["check_id"]: item for item in conflicted["checks"]}
        self.assertEqual("policy_conflict", checks["authorization.policy"]["code"])

    def test_padded_principal_is_reported_not_stripped(self) -> None:
        for principal in (" local-user", "local-user ", "local-user\n", "local\ud800user"):
            with self.subTest(principal=principal):
                report = self._run(principal=principal)
                DOCTOR_VALIDATOR.validate(report)
                self.assertFalse(report["ready"])
                self.assertIsNone(report["request"]["principal_id"])
                checks = {item["check_id"]: item for item in report["checks"]}
                self.assertEqual("principal_invalid", checks["authorization.policy"]["code"])
                self.assertEqual("principal_invalid", checks["authorization.grants"]["code"])
                self.assertEqual("not_checked", report["query_smoke"]["status"])
        unselected = run_doctor(self.db, self.objects, policy_path=POLICY)
        checks = {item["check_id"]: item for item in unselected["checks"]}
        self.assertEqual("principal_not_selected", checks["authorization.policy"]["code"])

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
