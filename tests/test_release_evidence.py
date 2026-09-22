from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from jsonschema.validators import validator_for


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_evidence as release_module  # noqa: E402
from build_starter_distribution import build_starter_distribution  # noqa: E402
from release_evidence import generate_release_evidence, validate_release_evidence  # noqa: E402
from validate_installed_wheel import _source_inventory, _wheel_source_paths  # noqa: E402


def _wheel_member(archive: zipfile.ZipFile, name: str, value: str) -> None:
    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_STORED
    archive.writestr(info, value)


class ReleaseEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.shared = tempfile.TemporaryDirectory(prefix="standardsforge-release-evidence-")
        cls.base = Path(cls.shared.name)
        cls.wheel = cls.base / "standardsforge-0.1.0a1-py3-none-any.whl"
        with zipfile.ZipFile(cls.wheel, "w", compression=zipfile.ZIP_STORED) as archive:
            _wheel_member(
                archive,
                "standardsforge-0.1.0a1.dist-info/WHEEL",
                "Wheel-Version: 1.0\nGenerator: setuptools (84.0.0)\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            )
            _wheel_member(
                archive,
                "standardsforge-0.1.0a1.dist-info/METADATA",
                "Metadata-Version: 2.4\nName: standardsforge\nVersion: 0.1.0a1\n",
            )
        source_files = _source_inventory()
        lock_path = ROOT / "build-toolchain.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))["build_backend"]
        cls.provenance = cls.base / f"{cls.wheel.name}.provenance.json"
        cls.provenance.write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "project": "standardsforge",
                    "version": "0.1.0a1",
                    "source_date_epoch": 1767225600,
                    "build_backend": "setuptools==84.0.0",
                    "wheel_generator": "setuptools (84.0.0)",
                    "builder": {"python": "3.12.test", "pip": "test"},
                    "source_files": source_files,
                    "wheel_source_paths": _wheel_source_paths(source_files),
                    "release_metadata_paths": ["uv.lock"],
                    "build_tool": {
                        "lock_path": lock_path.name,
                        "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
                        "artifact": {
                            "filename": lock["filename"],
                            "bytes": lock["bytes"],
                            "sha256": lock["sha256"],
                        },
                    },
                    "authentication": "none",
                    "wheel": {
                        "filename": cls.wheel.name,
                        "bytes": cls.wheel.stat().st_size,
                        "sha256": hashlib.sha256(cls.wheel.read_bytes()).hexdigest(),
                        "clean_build_count": 2,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        cls.starter = cls.base / "standardsforge-starter.zip"
        build_starter_distribution(cls.wheel, cls.provenance, cls.starter)
        cls.evidence = cls.base / "evidence"
        cls.result = generate_release_evidence(
            cls.wheel,
            cls.provenance,
            cls.starter,
            cls.evidence,
            repository="example/standardsforge",
            repository_uri="https://github.com/example/standardsforge.git",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.shared.cleanup()

    def _copy_evidence(self, name: str) -> Path:
        target = self.base / name
        shutil.copytree(self.evidence, target)
        self.addCleanup(shutil.rmtree, target, ignore_errors=True)
        return target

    @staticmethod
    def _refresh_inventory(directory: Path, filename: str) -> None:
        index_path = directory / "release-evidence.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        record = next(item for item in index["evidence_files"] if item["path"] == filename)
        changed = directory / filename
        record["bytes"] = changed.stat().st_size
        record["sha256"] = hashlib.sha256(changed.read_bytes()).hexdigest()
        index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_evidence_is_deterministic_schema_valid_and_explicitly_unsigned(self) -> None:
        second = self.base / "evidence-second"
        self.addCleanup(shutil.rmtree, second, ignore_errors=True)
        result = generate_release_evidence(
            self.wheel,
            self.provenance,
            self.starter,
            second,
            repository="example/standardsforge",
            repository_uri="https://github.com/example/standardsforge.git",
        )
        for name in release_module.FINAL_FILENAMES:
            self.assertEqual((self.evidence / name).read_bytes(), (second / name).read_bytes())
        self.assertTrue(result["integrity_verified"])
        self.assertFalse(result["authenticity_verified"])
        self.assertEqual("not_present", result["signature_status"])

        index = json.loads((self.evidence / "release-evidence.json").read_text(encoding="utf-8"))
        self.assertEqual("unsigned", index["authentication"]["local_evidence"])
        for filename, schema_name in (
            ("wheel.cdx.json", "cyclonedx-release-sbom.schema.json"),
            ("starter.cdx.json", "cyclonedx-release-sbom.schema.json"),
            ("wheel.intoto.json", "release-build-statement.schema.json"),
            ("starter.intoto.json", "release-build-statement.schema.json"),
        ):
            value = json.loads((self.evidence / filename).read_text(encoding="utf-8"))
            schema = json.loads((ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
            validator_for(schema)(schema).validate(value)
        wheel_sbom = json.loads((self.evidence / "wheel.cdx.json").read_text(encoding="utf-8"))
        self.assertEqual([], wheel_sbom["components"])
        self.assertEqual([], wheel_sbom["dependencies"][0]["dependsOn"])

    def test_tamper_extra_false_signature_wrong_subject_and_authenticity_fail(self) -> None:
        tampered = self._copy_evidence("tampered-evidence")
        with (tampered / "wheel.cdx.json").open("ab") as target:
            target.write(b" ")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            validate_release_evidence(tampered, self.wheel, self.provenance, self.starter)

        extra = self._copy_evidence("extra-evidence")
        (extra / "extra.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact closed"):
            validate_release_evidence(extra, self.wheel, self.provenance, self.starter)

        signed = self._copy_evidence("false-signed-evidence")
        statement_path = signed / "wheel.intoto.json"
        statement = json.loads(statement_path.read_text(encoding="utf-8"))
        statement["predicate"]["standardsforgeAuthentication"]["signed"] = True
        statement_path.write_text(json.dumps(statement, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._refresh_inventory(signed, statement_path.name)
        with self.assertRaises(Exception):
            validate_release_evidence(signed, self.wheel, self.provenance, self.starter)

        wrong = self._copy_evidence("wrong-subject-evidence")
        statement_path = wrong / "starter.intoto.json"
        statement = json.loads(statement_path.read_text(encoding="utf-8"))
        statement["subject"][0]["digest"]["sha256"] = "0" * 64
        statement_path.write_text(json.dumps(statement, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._refresh_inventory(wrong, statement_path.name)
        with self.assertRaisesRegex(ValueError, "subject"):
            validate_release_evidence(wrong, self.wheel, self.provenance, self.starter)

        with self.assertRaisesRegex(ValueError, "unsigned"):
            validate_release_evidence(
                self.evidence,
                self.wheel,
                self.provenance,
                self.starter,
                require_authenticity=True,
            )

    def test_dirty_source_cannot_satisfy_clean_release_policy(self) -> None:
        responses = iter(
            [
                subprocess.CompletedProcess([], 0, stdout="a" * 40 + "\n", stderr=""),
                subprocess.CompletedProcess([], 0, stdout=" M README.md\n", stderr=""),
            ]
        )
        with patch.object(release_module, "_git", side_effect=lambda *args, **kwargs: next(responses)):
            with self.assertRaisesRegex(ValueError, "clean Git worktree"):
                release_module._source_control(None, True)


if __name__ == "__main__":
    unittest.main()
