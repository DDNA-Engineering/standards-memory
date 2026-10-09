from __future__ import annotations

import hashlib
import copy
import json
import os
import shutil
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
    mcp_server_options,
    required_install_bytes,
    _write_host_configuration,
    _venv_python,
    VENV_MARKER,
    _run,
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

    def test_os_metadata_files_are_tolerated_but_other_extras_are_named(self) -> None:
        validate_bundle(self.root)
        names = [".DS_Store", "wheel/._standardsforge.whl", "Thumbs.db", "provenance/desktop.ini"]
        if os.name != "nt":
            names.append("Icon\r")  # macOS folder icon; Windows cannot create this name
        for relative in names:
            (self.root / relative).write_bytes(b"shell metadata")
        validate_bundle(self.root)
        (self.root / "notes.txt").write_text("mine", encoding="utf-8")
        with self.assertRaisesRegex(PreparedSetupError, r"missing or unlisted files \(not part of this release: notes\.txt\)"):
            validate_bundle(self.root)

    @unittest.skipIf(os.name == "nt", "symbolic links need privileges on Windows")
    def test_os_metadata_name_does_not_excuse_a_link(self) -> None:
        (self.root / ".DS_Store").symlink_to(self.root / "setup.py")
        with self.assertRaisesRegex(PreparedSetupError, "symbolic link"):
            validate_bundle(self.root)

    def test_per_python_locks_and_tokenizer_are_bound_to_the_manifest(self) -> None:
        validate_bundle(self.root)
        for change, message in (
            (lambda m: m["build"]["mcp_requirements_sha256"].pop("3.13"), "mcp_requirements_sha256"),
            (lambda m: m["build"]["mcp_requirements_sha256"].update({"3.11": "0" * 64}), "digest is inconsistent for Python 3.11"),
            (lambda m: m["build"]["tokenizer"].update(sha256="0" * 64), "tokenizer artifact is inconsistent"),
            (lambda m: m["build"]["tokenizer"].update(implementation="tiktoken==0.13.0"), "tokenizer identity is invalid"),
            (lambda m: m["build"].update(mcp_runtime_pythons=["3.12"]), "mcp_runtime_pythons"),
        ):
            baseline = copy.deepcopy(self.manifest)
            change(self.manifest)
            self._write_manifest()
            with self.assertRaisesRegex(PreparedSetupError, message):
                validate_bundle(self.root)
            self.manifest = baseline
            self._write_manifest()

    def test_lock_entries_must_close_over_the_wheelhouse(self) -> None:
        lock = self.root / "provenance/mcp-wheelhouse-win-amd64-cp313.txt"
        changed = f"mcp==2.2.0 --hash=sha256:{'1' * 64}\n".encode()
        lock.write_bytes(changed)
        for item in self.manifest["files"]:
            if item["path"] == "provenance/mcp-wheelhouse-win-amd64-cp313.txt":
                item.update(bytes=len(changed), sha256=_sha256(changed))
        self.manifest["build"]["mcp_requirements_sha256"]["3.13"] = _sha256(changed)
        self._write_manifest()
        with self.assertRaisesRegex(PreparedSetupError, "does not exactly match its per-Python locks"):
            validate_bundle(self.root)

    def test_launch_options_pin_tokenizer_and_optional_reference_bindings(self) -> None:
        manifest, _ = validate_bundle(self.root)
        options = mcp_server_options(self.root, manifest)
        self.assertEqual(["--tokenizer-artifact", str(self.root / "tokenizer" / "o200k_base.json"),
                          "--tokenizer-sha256", manifest["build"]["tokenizer"]["sha256"]], options)
        manifest["state"]["reference_bindings"] = {"path": "references/reference-bindings.json", "sha256": "b" * 64}
        self.assertEqual(["--reference-bindings", str(self.root / "references" / "reference-bindings.json"),
                          "--reference-bindings-sha256", "b" * 64], mcp_server_options(self.root, manifest)[4:])

    def test_offline_mcp_accepts_each_locked_windows_python(self) -> None:
        for version, accepted in (((3, 10), False), ((3, 11), True), ((3, 12), True), ((3, 13), True), ((3, 14), False)):
            with (patch("prepared_runtime.sys.platform", "win32"), patch("prepared_runtime.platform.machine", return_value="AMD64"),
                  patch("prepared_runtime.sys.version_info", (*version, 0, "final", 0))):
                if accepted:
                    _check_mcp_profile("offline")
                else:
                    with self.assertRaisesRegex(PreparedSetupError, "3.11, 3.12 or 3.13"):
                        _check_mcp_profile("offline")

    def test_first_setup_stops_before_indexing_when_disk_space_is_short(self) -> None:
        manifest, _ = validate_bundle(self.root)
        self.assertEqual(250 * 1000 * 1000, required_install_bytes(manifest))
        manifest["files"].append({"path": "corpus/a.zip", "bytes": 10**9, "sha256": "0" * 64})
        self.assertEqual(2 * 10**9 + 250 * 1000 * 1000, required_install_bytes(manifest))
        with patch("prepared_runtime.shutil.disk_usage", return_value=shutil._ntuple_diskusage(10**12, 10**12 - 10**8, 10**8)):
            with self.assertRaisesRegex(PreparedSetupError, r"needs about 0\.2 GB of free disk space .* only 0\.1 GB"):
                setup_prepared(self.root, quiet=True)
        self.assertFalse((self.root / ".venv").exists())
        self.assertFalse((self.root / ".standardsforge").exists())

    def test_only_explicit_dependency_install_enables_package_index(self) -> None:
        with patch("prepared_runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            _run(["python", "-m", "pip"], self.root)
            self.assertEqual("1", run.call_args.kwargs["env"]["PIP_NO_INDEX"])
            _run(["python", "-m", "pip"], self.root, dependency_network=True)
            self.assertEqual("0", run.call_args.kwargs["env"]["PIP_NO_INDEX"])

    def test_changed_bundle_cannot_retain_ready_receipt(self) -> None:
        _, digest = validate_bundle(self.root)
        state = self.root / ".standardsforge"
        state.mkdir()
        receipt = state / "prepared-distribution.json"
        receipt.write_text(json.dumps({"bundle_manifest_sha256": digest}), encoding="utf-8")
        (self.root / "setup.py").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(PreparedSetupError, "inventory validation failed"):
            setup_prepared(self.root, quiet=True)
        self.assertFalse(receipt.exists())
        self.assertEqual({"bundle_manifest_sha256": digest}, json.loads((state / "prepared-setup-incomplete.json").read_text()))

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
        tokenizer_bytes = b'{"name":"o200k_base","schema_version":"0.1.0"}'
        payloads = {
            f"wheel/{wheel_name}": wheel_bytes,
            f"wheelhouse/{mcp_name}": mcp_bytes,
            "provenance/acquisition-manifest.json": acquisition_bytes,
            "provenance/source-baseline.json": (json.dumps(source_baseline) + "\n").encode(),
            "provenance/wheel-build.json": (json.dumps(wheel_provenance) + "\n").encode(),
            "provenance/mcp-wheelhouse-win-amd64-cp311.txt": requirements,
            "provenance/mcp-wheelhouse-win-amd64-cp312.txt": requirements,
            "provenance/mcp-wheelhouse-win-amd64-cp313.txt": requirements,
            "tokenizer/o200k_base.json": tokenizer_bytes,
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
            "schema_version": "1.4",
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
                "mcp_requirements_sha256": {version: _sha256(requirements) for version in ("3.11", "3.12", "3.13")},
                "core_runtime_python": "CPython >=3.11",
                "core_runtime_platforms": ["windows_x86_64", "linux_x86_64", "macos_arm64", "macos_x86_64"],
                "mcp_runtime_platform": "win_amd64",
                "mcp_runtime_pythons": ["3.11", "3.12", "3.13"],
                "tokenizer": {"encoding": "o200k_base", "path": "tokenizer/o200k_base.json", "sha256": _sha256(tokenizer_bytes),
                              "bytes": len(tokenizer_bytes), "implementation": "tiktoken==0.14.0"},
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

    def test_reviewed_packs_and_reference_bindings_are_closed_and_pinned(self) -> None:
        entry = {"path": "packs/reviewed/mil-std-882e.zip", "suite_path": "qualification/reviewed/mil-std-882e-suite.json",
                 "run_path": "qualification/reviewed/mil-std-882e-run.json", "pack_id": "reviewed", "package_digest": "c" * 64}
        bindings = b'{"binding_set": {}}'
        for relative, value in ((entry["path"], b"fixture"), (entry["suite_path"], b"fixture"), (entry["run_path"], b"fixture"),
                                ("references/reference-bindings.json", bindings)):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
            self.manifest["files"].append({"path": relative, "bytes": len(value), "sha256": _sha256(value)})
        self.manifest["state"].update(qualified_packs=[entry], included_package_count=440,
                                      reference_bindings={"path": "references/reference-bindings.json", "sha256": _sha256(bindings)})
        self._write_manifest()
        validate_bundle(self.root)
        baseline = copy.deepcopy(self.manifest)
        for change in (lambda m: m["state"]["qualified_packs"][0].update(suite_path="qualification/recovery/mil-std-882e-suite.json"),
                       lambda m: m["state"]["reference_bindings"].update(sha256="0" * 64),
                       lambda m: m["state"]["reference_bindings"].update(path="references/other.json")):
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
        for unsupported in ("1.2", "1.3"):
            self.manifest["schema_version"] = unsupported
            self._write_manifest()
            with self.assertRaisesRegex(PreparedSetupError, "Unsupported"):
                validate_bundle(self.root)
        self.manifest["schema_version"] = "1.4"
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
        # -I is what standardsforge.sh and the PowerShell launchers use; run.py must
        # still find its adjacent helper without the script directory on sys.path.
        for flag in ("-B", "-I"):
            result = subprocess.run(
                [sys.executable, flag, str(self.root / "run.py"), "--help"],
                cwd=self.root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn("prepared_bundle_invalid", result.stderr)
            self.assertFalse(sentinel.exists())



class _FakeEnvBuilder:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def create(self, root) -> None:
        python = _venv_python(Path(root))
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_bytes(b"fresh interpreter")


class PreparedRecoveryTests(unittest.TestCase):
    """Interrupted or failed setup must stay recoverable and never strand .venv."""

    tearDown = PreparedRuntimeTests.tearDown
    _write_manifest = PreparedRuntimeTests._write_manifest

    def setUp(self) -> None:
        PreparedRuntimeTests.setUp(self)
        # Setup resolves its root; compare against the same path (macOS /var -> /private/var).
        self.root = self.root.resolve()

    def _partial_install(self) -> tuple[str, Path, Path]:
        _, digest = validate_bundle(self.root)
        state = self.root / ".standardsforge"
        state.mkdir()
        (state / "prepared-setup-incomplete.json").write_text(json.dumps({"bundle_manifest_sha256": digest}), encoding="utf-8")
        (state / "memory.db").write_bytes(b"half-built")
        venv_root = self.root / ".venv"
        python = _venv_python(venv_root)
        python.parent.mkdir(parents=True)
        python.write_bytes(b"old interpreter")
        (venv_root / VENV_MARKER).write_text(json.dumps({"bundle_manifest_sha256": digest}), encoding="utf-8")
        return digest, state, venv_root

    def _setup_until_install(self) -> None:
        with (
            patch("prepared_runtime.venv.EnvBuilder", _FakeEnvBuilder),
            patch("prepared_runtime._run", side_effect=PreparedSetupError("stopped at wheel install")),
        ):
            with self.assertRaisesRegex(PreparedSetupError, "stopped at wheel install"):
                setup_prepared(self.root, quiet=True)

    def _assert_recovered(self, digest: str) -> None:
        state = self.root / ".standardsforge"
        venv_root = self.root / ".venv"
        self.assertEqual({"bundle_manifest_sha256": digest}, json.loads((state / "prepared-setup-incomplete.json").read_text()))
        self.assertEqual({"bundle_manifest_sha256": digest}, json.loads((venv_root / VENV_MARKER).read_text()))
        self.assertEqual(b"fresh interpreter", _venv_python(venv_root).read_bytes())
        self.assertFalse((state / "memory.db").exists())
        self.assertFalse((state / ".discarded-venv").exists())

    def test_locked_venv_keeps_both_ownership_markers_and_retry_recovers(self) -> None:
        digest, state, venv_root = self._partial_install()
        real_rename = os.rename

        def locked(source, target, *args, **kwargs):
            if Path(source) == venv_root:
                raise PermissionError(13, "Access is denied", str(_venv_python(venv_root)))
            return real_rename(source, target, *args, **kwargs)

        with patch("prepared_runtime.os.rename", side_effect=locked):
            with self.assertRaisesRegex(PreparedSetupError, "delete the directory .*\\.venv") as failed:
                setup_prepared(self.root, quiet=True)
        self.assertIn(str(venv_root), str(failed.exception))
        self.assertTrue((venv_root / VENV_MARKER).is_file())
        self.assertTrue((state / "prepared-setup-incomplete.json").is_file())
        self.assertTrue((state / "memory.db").is_file())

        self._setup_until_install()
        self._assert_recovered(digest)

    def test_failed_delete_after_move_is_finished_by_the_next_run(self) -> None:
        digest, state, venv_root = self._partial_install()
        real_rmtree = shutil.rmtree

        def stuck(path, *args, **kwargs):
            if Path(path).name == ".discarded-venv":
                (Path(path) / VENV_MARKER).unlink()
                raise PermissionError(13, "Access is denied", str(path))
            return real_rmtree(path, *args, **kwargs)

        with patch("prepared_runtime.shutil.rmtree", side_effect=stuck):
            with self.assertRaisesRegex(PreparedSetupError, "run setup again"):
                setup_prepared(self.root, quiet=True)
        self.assertFalse(venv_root.exists())
        self.assertTrue((state / "prepared-setup-incomplete.json").is_file())

        self._setup_until_install()
        self._assert_recovered(digest)

    def test_interruption_at_any_recovery_step_remains_recoverable(self) -> None:
        import prepared_runtime as runtime_module

        injections = [
            (runtime_module.os, "rename", 1),
            (runtime_module.shutil, "rmtree", 1),
            (runtime_module.shutil, "rmtree", 2),
            (runtime_module, "_write_json_atomic", 1),
            (runtime_module, "_write_json_atomic", 2),
            (Path, "unlink", 1),
            (Path, "mkdir", 1),
            (Path, "mkdir", 2),
        ]
        for owner, attribute, interrupted_call in injections:
            with self.subTest(target=f"{getattr(owner, '__name__', owner)}.{attribute}", call=interrupted_call):
                shutil.rmtree(self.root / ".standardsforge", ignore_errors=True)
                shutil.rmtree(self.root / ".venv", ignore_errors=True)
                digest, _, _ = self._partial_install()
                real = getattr(owner, attribute)
                calls = {"count": 0}

                def interrupt(*args, **kwargs):
                    calls["count"] += 1
                    if calls["count"] == interrupted_call:
                        raise KeyboardInterrupt
                    return real(*args, **kwargs)

                with (
                    patch.object(owner, attribute, side_effect=interrupt, autospec=owner is Path),
                    patch("prepared_runtime.venv.EnvBuilder", _FakeEnvBuilder),
                    patch("prepared_runtime._run", side_effect=PreparedSetupError("stopped at wheel install")),
                ):
                    try:
                        setup_prepared(self.root, quiet=True)
                    except (KeyboardInterrupt, PreparedSetupError):
                        pass
                self.assertGreaterEqual(calls["count"], 1)
                self._setup_until_install()
                self._assert_recovered(digest)

    def test_unmarked_venv_without_partial_state_gets_actionable_message_and_is_kept(self) -> None:
        venv_root = self.root / ".venv"
        python = _venv_python(venv_root)
        python.parent.mkdir(parents=True)
        python.write_bytes(b"someone else's interpreter")
        with self.assertRaisesRegex(PreparedSetupError, "no StandardsForge ownership marker") as failed:
            setup_prepared(self.root, quiet=True)
        self.assertIn(f"delete the directory {venv_root}", str(failed.exception))
        self.assertEqual(b"someone else's interpreter", python.read_bytes())
        self.assertFalse((self.root / ".standardsforge").exists())

    def test_unowned_state_is_not_deleted_and_names_the_directory(self) -> None:
        state = self.root / ".standardsforge"
        state.mkdir()
        (state / "memory.db").write_bytes(b"unknown")
        with self.assertRaisesRegex(PreparedSetupError, "not owned by a recoverable setup") as failed:
            setup_prepared(self.root, quiet=True)
        self.assertIn(str(state), str(failed.exception))
        self.assertTrue((state / "memory.db").is_file())

    def test_empty_state_from_interrupted_first_setup_is_recoverable(self) -> None:
        _, digest = validate_bundle(self.root)
        (self.root / ".standardsforge").mkdir()
        self._setup_until_install()
        self.assertEqual(
            {"bundle_manifest_sha256": digest},
            json.loads((self.root / ".standardsforge/prepared-setup-incomplete.json").read_text()),
        )
        self.assertTrue((self.root / ".venv" / VENV_MARKER).is_file())

    def test_recovery_refuses_to_delete_the_running_interpreter_environment(self) -> None:
        _, state, venv_root = self._partial_install()
        with patch("prepared_runtime.sys.prefix", str(venv_root)):
            with self.assertRaisesRegex(PreparedSetupError, "Run setup with the system Python"):
                setup_prepared(self.root, quiet=True)
        self.assertEqual(b"old interpreter", _venv_python(venv_root).read_bytes())
        self.assertTrue((venv_root / VENV_MARKER).is_file())
        self.assertTrue((state / "memory.db").is_file())

    def test_differently_owned_venv_is_never_deleted_during_recovery(self) -> None:
        _, state, venv_root = self._partial_install()
        (venv_root / VENV_MARKER).write_text(json.dumps({"bundle_manifest_sha256": "f" * 64}), encoding="utf-8")
        with self.assertRaisesRegex(PreparedSetupError, "not owned by this prepared bundle"):
            setup_prepared(self.root, quiet=True)
        self.assertTrue(_venv_python(venv_root).is_file())
        self.assertTrue((state / "memory.db").is_file())


class PreparedOutputEncodingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="standardsforge-prepared-encoding-")
        self.root = Path(self.temporary.name) / "Łč prepared"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _child(self, payload: bytes) -> list[str]:
        return [sys.executable, "-I", "-c", f"import sys; sys.stdout.buffer.write({payload!r})"]

    def test_utf8_cli_output_is_decoded_under_a_legacy_locale(self) -> None:
        database = str(self.root / ".standardsforge" / "memory.db")
        payload = (json.dumps({"ok": True, "result": {"path": database}}, ensure_ascii=False) + "\n").encode("utf-8")
        with (
            patch("subprocess._text_encoding", return_value="cp1252"),
            patch("locale.getpreferredencoding", return_value="cp1252"),
        ):
            result = _run(self._child(payload), self.root, capture=True)
        self.assertEqual({"path": database}, _parse_cli_success(result, "doctor"))

    def test_invalid_utf8_output_is_a_typed_setup_error(self) -> None:
        with self.assertRaisesRegex(PreparedSetupError, "not valid UTF-8"):
            _run(self._child(b'{"ok": true, "result": {"path": "\xa3\xe8"}}\n'), self.root, capture=True)

    def test_failed_command_with_undecodable_stderr_still_reports_failure(self) -> None:
        command = [sys.executable, "-I", "-c", "import sys; sys.stderr.buffer.write(b'\\xa3 failed'); raise SystemExit(3)"]
        with self.assertRaisesRegex(PreparedSetupError, r"failed \(3\).*failed"):
            _run(command, self.root, capture=True)


if __name__ == "__main__":
    unittest.main()
