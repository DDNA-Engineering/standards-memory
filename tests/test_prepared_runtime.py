from __future__ import annotations

import hashlib
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv
import tomllib
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "prepared_distribution"))

from prepared_runtime import (  # noqa: E402
    PreparedSetupError,
    _parse_cli_success,
    _remove_posix_venv_lib64_alias,
    _require_no_links_tree,
    setup_prepared,
    validate_bundle,
    validate_receipt,
    _check_mcp_profile,
    _write_host_configuration,
    _venv_python,
    VENV_MARKER,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class PreparedRuntimeTests(unittest.TestCase):
    def test_offline_mcp_rejects_other_platforms_before_setup(self) -> None:
        with patch("prepared_runtime.sys.platform", "darwin"):
            with self.assertRaisesRegex(PreparedSetupError, "Offline MCP requires"):
                setup_prepared(self.root, mcp_mode="offline", quiet=True)
        self.assertFalse((self.root / ".venv").exists())
        self.assertFalse((self.root / ".standardsforge").exists())
        _check_mcp_profile("online")

    def test_generated_host_configs_round_trip_paths_with_spaces_and_unicode(self) -> None:
        root = self.root / "Prepared library ü"
        (root / ".standardsforge").mkdir(parents=True)
        paths = _write_host_configuration(root)
        json_entry = json.loads(Path(paths["claude_desktop_or_cursor"]).read_text(encoding="utf-8"))["mcpServers"]["standardsforge"]
        toml_entry = tomllib.loads(Path(paths["codex"]).read_text(encoding="utf-8"))["mcp_servers"]["standardsforge"]
        self.assertEqual(json_entry, toml_entry)
        self.assertEqual(["-I", str(root / "run_mcp.py")], json_entry["args"])
        self.assertTrue(Path(json_entry["command"]).is_absolute())

    def test_mcp_launcher_rejects_overrides_and_missing_readiness_without_setup(self) -> None:
        launcher = ROOT / "scripts/prepared_distribution/run_mcp.py"
        for arguments, code, message in ((["--principal", "other"], 2, "does not accept"), ([], 1, "prepared_mcp_not_ready")):
            result = subprocess.run([sys.executable, "-I", str(launcher), *arguments], capture_output=True, text=True)
            self.assertEqual(code, result.returncode)
            self.assertIn(message, result.stderr)
            self.assertEqual("", result.stdout)

    def test_failed_revalidation_removes_stale_readiness(self) -> None:
        manifest, digest = validate_bundle(self.root)
        state = self.root / ".standardsforge"
        state.mkdir()
        receipt = state / "prepared-distribution.json"
        receipt.write_text(json.dumps({
            "bundle_manifest_sha256": digest, "mcp_status": "ready", "principal_id": "local-user",
            "status": "ready", "version": manifest["version"], "wheel_sha256": manifest["build"]["wheel_sha256"],
        }), encoding="utf-8")
        python = _venv_python(self.root / ".venv")
        python.parent.mkdir(parents=True)
        python.touch()
        (self.root / ".venv" / VENV_MARKER).write_text(json.dumps({"bundle_manifest_sha256": digest}), encoding="utf-8")
        with patch("prepared_runtime._run", side_effect=PreparedSetupError("installation failed")):
            with self.assertRaisesRegex(PreparedSetupError, "installation failed"):
                setup_prepared(self.root, quiet=True)
        self.assertFalse(receipt.exists())
        self.assertTrue((state / "prepared-setup-incomplete.json").is_file())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux venv alias behavior")
    def test_standard_linux_venv_alias_is_removed_but_external_link_is_rejected(self) -> None:
        venv_root = self.root / ".venv"
        venv.EnvBuilder(with_pip=False, symlinks=False).create(venv_root)
        alias = venv_root / "lib64"
        self.assertTrue(alias.is_symlink())
        self.assertEqual("lib", os.readlink(alias))

        _remove_posix_venv_lib64_alias(venv_root)
        self.assertFalse(alias.exists())
        _require_no_links_tree(venv_root, "Prepared .venv")

        outside = self.root / "outside"
        outside.mkdir()
        alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(PreparedSetupError, "unexpected symbolic link"):
            _remove_posix_venv_lib64_alias(venv_root)
        with self.assertRaisesRegex(PreparedSetupError, "symbolic link or junction"):
            _require_no_links_tree(venv_root, "Prepared .venv")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux venv alias behavior")
    def test_unowned_venv_alias_is_not_modified(self) -> None:
        venv_root = self.root / ".venv"
        venv.EnvBuilder(with_pip=False, symlinks=False).create(venv_root)
        alias = venv_root / "lib64"
        self.assertTrue(alias.is_symlink())
        with self.assertRaises(PreparedSetupError):
            setup_prepared(self.root)
        self.assertTrue(alias.is_symlink())

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
        wheel_name = "standardsforge-0.1.0a5-py3-none-any.whl"
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
            "version": "0.1.0a5",
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
            "version": "0.1.0a5",
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

    def test_qualified_pack_manifest_requires_closed_paths_and_inventory(self) -> None:
        entry = {"path": "packs/recovery/semantics.zip", "suite_path": "qualification/recovery/semantics-suite.json",
                 "run_path": "qualification/recovery/semantics-run.json", "pack_id": "reviewed", "package_digest": "a" * 64}
        for key in ("path", "suite_path", "run_path"):
            target = self.root / entry[key]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fixture")
            self.manifest["files"].append({"path": entry[key], "bytes": 7, "sha256": _sha256(b"fixture")})
        self.manifest["state"].update(qualified_packs=[entry], included_package_count=440)
        self._write_manifest()
        validate_bundle(self.root)
        baseline = copy.deepcopy(self.manifest)
        for change in (lambda m: m["state"]["qualified_packs"][0].update(path="../outside.zip"),
                       lambda m: m["state"].update(included_package_count=439),
                       lambda m: m["state"]["qualified_packs"].append(copy.deepcopy(entry)),
                       lambda m: m["files"].pop()):
            self.manifest = copy.deepcopy(baseline)
            change(self.manifest)
            self._write_manifest()
            with self.assertRaises(PreparedSetupError):
                validate_bundle(self.root)

    def test_validates_closed_bundle_and_bound_receipts(self) -> None:
        manifest, digest = validate_bundle(self.root)
        receipt = {
            "bundle_manifest_sha256": digest,
            "mcp_status": "not_installed",
            "principal_id": "local-user",
            "status": "ready",
            "version": "0.1.0a5",
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
            "version": "0.1.0a5",
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
