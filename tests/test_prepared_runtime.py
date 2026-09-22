from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "prepared_distribution"))

from prepared_runtime import (  # noqa: E402
    PreparedSetupError,
    _parse_cli_success,
    validate_bundle,
    validate_receipt,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class PreparedRuntimeTests(unittest.TestCase):
    def test_cli_success_envelope_is_unwrapped(self) -> None:
        result = subprocess.CompletedProcess([], 0, stdout='{"ok": true, "result": {"ready": true}}')

        self.assertEqual(_parse_cli_success(result, "doctor"), {"ready": True})

    def test_cli_error_envelope_is_rejected(self) -> None:
        result = subprocess.CompletedProcess(
            [],
            0,
            stdout='{"ok": false, "error": {"code": "not_ready"}}',
        )

        with self.assertRaisesRegex(PreparedSetupError, "successful result envelope"):
            _parse_cli_success(result, "doctor")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="standardsforge-prepared-runtime-")
        self.root = Path(self.temporary.name)
        wheel_name = "standardsforge-0.1.0a4-py3-none-any.whl"
        wheel_bytes = b"qualified universal wheel"
        wheel_digest = _sha256(wheel_bytes)
        acquisition_bytes = b'{"qualified":true}\n'
        source_baseline = {
            "acquisition": {
                "manifest_path": "provenance/acquisition-manifest.json",
                "manifest_sha256": _sha256(acquisition_bytes),
            }
        }
        wheel_provenance = {
            "version": "0.1.0a4",
            "wheel": {"filename": wheel_name, "sha256": wheel_digest},
        }
        mcp_name = "mcp-2.2.0-py3-none-any.whl"
        mcp_bytes = b"qualified mcp wheel"
        requirements = f"mcp==2.2.0 --hash=sha256:{_sha256(mcp_bytes)}\n".encode()
        payloads = {
            f"wheel/{wheel_name}": wheel_bytes,
            f"wheelhouse/{mcp_name}": mcp_bytes,
            "provenance/acquisition-manifest.json": acquisition_bytes,
            "provenance/source-baseline.json": (json.dumps(source_baseline) + "\n").encode(),
            "provenance/wheel-build.json": (json.dumps(wheel_provenance) + "\n").encode(),
            "provenance/mcp-wheelhouse-win-amd64-cp312.txt": requirements,
            "prepared_runtime.py": (ROOT / "scripts/prepared_distribution/prepared_runtime.py").read_bytes(),
            "run.py": (ROOT / "scripts/prepared_distribution/run.py").read_bytes(),
            "setup.py": b"print('verified setup placeholder')\n",
        }
        for relative, value in payloads.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        wheelhouse_row = f"{_sha256(mcp_bytes)} {len(mcp_bytes)} {mcp_name}\n".encode()
        self.manifest = {
            "schema_version": "1.3",
            "product": "StandardsForge prepared distribution",
            "version": "0.1.0a4",
            "build": {
                "archive_source_date_epoch": 1767225600,
                "archive_timestamp": "2026-01-01T00:00:00Z",
                "wheel_build_backend": "setuptools==84.0.0",
                "wheel_generator": "setuptools (84.0.0)",
                "wheel_sha256": wheel_digest,
                "wheel_provenance_sha256": _sha256(payloads["provenance/wheel-build.json"]),
                "mcp_requirement": "mcp==2.2.0",
                "mcp_wheel_count": 1,
                "mcp_wheelhouse_sha256": _sha256(wheelhouse_row),
                "mcp_requirements_sha256": _sha256(requirements),
                "core_runtime_python": "CPython >=3.11",
                "core_runtime_platforms": ["windows_x86_64", "linux_x86_64", "macos_arm64", "macos_x86_64"],
                "mcp_runtime_python": "CPython 3.12",
                "mcp_runtime_platform": "win_amd64",
                "corpus_compiler_version": "0.3.0",
            },
            "state": {"principal_id": "local-user", "corpus_package_count": 438},
            "files": [
                {"path": relative, "bytes": len(value), "sha256": _sha256(value)}
                for relative, value in sorted(payloads.items())
            ],
        }
        self._write_manifest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_manifest(self) -> str:
        value = (json.dumps(self.manifest, indent=2, sort_keys=True) + "\n").encode()
        (self.root / "bundle-manifest.json").write_bytes(value)
        return _sha256(value)

    def test_validates_closed_bundle_and_bound_receipts(self) -> None:
        manifest, digest = validate_bundle(self.root)
        receipt = {
            "bundle_manifest_sha256": digest,
            "mcp_status": "not_installed",
            "principal_id": "local-user",
            "status": "ready",
            "version": "0.1.0a4",
            "wheel_sha256": manifest["build"]["wheel_sha256"],
        }
        state = self.root / ".standardsforge"
        state.mkdir()
        (state / "prepared-distribution.json").write_text(json.dumps(receipt), encoding="utf-8")
        self.assertEqual(receipt, validate_receipt(self.root, manifest, digest))

    def test_rejects_tampered_missing_extra_and_duplicate_files(self) -> None:
        target = self.root / self.manifest["files"][0]["path"]
        original = target.read_bytes()
        target.write_bytes(original + b"tamper")
        with self.assertRaisesRegex(PreparedSetupError, "inventory validation failed"):
            validate_bundle(self.root)
        target.write_bytes(original)

        extra = self.root / "unlisted.txt"
        extra.write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(PreparedSetupError, "missing or unlisted"):
            validate_bundle(self.root)
        extra.unlink()

        self.manifest["files"].append(dict(self.manifest["files"][0]))
        self._write_manifest()
        with self.assertRaisesRegex(PreparedSetupError, "duplicate"):
            validate_bundle(self.root)

    def test_rejects_unsupported_manifest_and_unsafe_link(self) -> None:
        self.manifest["schema_version"] = "1.2"
        self._write_manifest()
        with self.assertRaisesRegex(PreparedSetupError, "Unsupported"):
            validate_bundle(self.root)
        self.manifest["schema_version"] = "1.3"
        self._write_manifest()

        link = self.root / "linked"
        try:
            link.symlink_to(self.root / "wheel", target_is_directory=True)
        except OSError:
            self.skipTest("symbolic links are unavailable")
        with self.assertRaisesRegex(PreparedSetupError, "symbolic link or junction"):
            validate_bundle(self.root)

    def test_rejects_external_runtime_state_even_with_matching_receipt(self) -> None:
        manifest, digest = validate_bundle(self.root)
        external = self.root.parent / f"{self.root.name}-external-state"
        external.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(external, ignore_errors=True))
        receipt = {
            "bundle_manifest_sha256": digest,
            "mcp_status": "not_installed",
            "principal_id": "local-user",
            "status": "ready",
            "version": "0.1.0a4",
            "wheel_sha256": manifest["build"]["wheel_sha256"],
        }
        (external / "prepared-distribution.json").write_text(json.dumps(receipt), encoding="utf-8")
        link = self.root / ".standardsforge"
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest("symbolic links are unavailable")
        with self.assertRaisesRegex(PreparedSetupError, "symbolic link or junction"):
            validate_receipt(self.root, manifest, digest)

    def test_launcher_never_executes_tampered_setup_fallback(self) -> None:
        sentinel = self.root / "unverified-setup-executed"
        (self.root / "setup.py").write_text(
            "from pathlib import Path\nPath('unverified-setup-executed').write_text('bad')\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-B", str(self.root / "run.py"), "--help"],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("prepared_bundle_invalid", result.stderr)
        self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
