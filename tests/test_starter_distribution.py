from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jsonschema.validators import validator_for


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_starter_distribution as starter_builder  # noqa: E402
from build_starter_distribution import (  # noqa: E402
    build_starter_distribution,
    discover_wheel_inputs,
    validate_starter_archive,
)
from validate_installed_wheel import _source_inventory, _wheel_source_paths  # noqa: E402


def _wheel_member(archive: zipfile.ZipFile, name: str, value: str) -> None:
    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_STORED
    archive.writestr(info, value)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


class StarterDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.shared = tempfile.TemporaryDirectory(prefix="standardsforge-starter-tests-")
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
        cls.provenance = cls.base / f"{cls.wheel.name}.provenance.json"
        source_files = _source_inventory()
        build_tool_lock = ROOT / "build-toolchain.lock.json"
        build_tool = json.loads(build_tool_lock.read_text(encoding="utf-8"))["build_backend"]
        cls.provenance.write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "project": "standardsforge",
                    "version": "0.1.0a1",
                    "source_date_epoch": 1767225600,
                    "build_backend": "setuptools==84.0.0",
                    "wheel_generator": "setuptools (84.0.0)",
                    "builder": {"python": "test", "pip": "test"},
                    "source_files": source_files,
                    "wheel_source_paths": _wheel_source_paths(source_files),
                    "release_metadata_paths": ["uv.lock"],
                    "build_tool": {
                        "lock_path": build_tool_lock.name,
                        "lock_sha256": hashlib.sha256(build_tool_lock.read_bytes()).hexdigest(),
                        "artifact": {
                            "filename": build_tool["filename"],
                            "bytes": build_tool["bytes"],
                            "sha256": build_tool["sha256"],
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
        cls.archive = cls.base / "starter.zip"
        cls.result = build_starter_distribution(cls.wheel, cls.provenance, cls.archive)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.shared.cleanup()

    def _extract(self, name: str) -> Path:
        root = self.base / name
        root.mkdir()
        with zipfile.ZipFile(self.archive, "r") as archive:
            prefix = f"standardsforge-starter-{self.result['version']}/"
            distribution = root / prefix.removesuffix("/")
            distribution.mkdir()
            for info in archive.infolist():
                relative = info.filename.removeprefix(prefix)
                target = distribution.joinpath(*Path(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info.filename))
        return distribution

    def test_builder_is_byte_reproducible_and_manifest_is_closed(self) -> None:
        second = self.base / "starter-second.zip"
        result = build_starter_distribution(self.wheel, self.provenance, second)
        self.addCleanup(second.unlink, missing_ok=True)
        self.addCleanup(second.with_suffix(".zip.sha256").unlink, missing_ok=True)
        self.assertEqual(self.archive.read_bytes(), second.read_bytes())
        self.assertEqual(self.result["archive_sha256"], result["archive_sha256"])

        manifest = validate_starter_archive(self.archive)
        schema = json.loads((ROOT / "contracts" / "starter-bundle.schema.json").read_text(encoding="utf-8"))
        validator_for(schema)(schema).validate(manifest)
        self.assertEqual(2, len(manifest["packages"]))
        self.assertTrue(all(value is False for value in manifest["claims"].values()))
        with zipfile.ZipFile(self.archive, "r") as archive:
            self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()))
            self.assertTrue(all(info.date_time == (2026, 1, 1, 0, 0, 0) for info in archive.infolist()))

    def test_consumer_prevalidation_is_stdlib_only_and_non_mutating_on_tamper(self) -> None:
        distribution = self._extract("prevalidation")
        setup = _load_module(distribution / "setup.py", "starter_setup_prevalidation")
        manifest, manifest_sha256 = setup.validate_bundle(distribution)
        self.assertEqual("synthetic_contract_starter", manifest["profile"])
        self.assertEqual(64, len(manifest_sha256))
        self.assertFalse((distribution / ".venv").exists())
        self.assertFalse((distribution / ".standardsforge").exists())

        readme = distribution / "README.md"
        readme.write_bytes(readme.read_bytes() + b"tamper")
        with self.assertRaisesRegex(setup.StarterSetupError, "inventory validation"):
            setup.setup_starter(distribution, quiet=True)
        self.assertFalse((distribution / ".venv").exists())
        self.assertFalse((distribution / ".standardsforge").exists())

    def test_consumer_rejects_extra_file_stale_receipt_and_unowned_state(self) -> None:
        distribution = self._extract("consumer-negatives")
        setup = _load_module(distribution / "setup.py", "starter_setup_negatives")
        manifest, manifest_sha256 = setup.validate_bundle(distribution)
        (distribution / "extra.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(setup.StarterSetupError, "unlisted or missing"):
            setup.validate_bundle(distribution)
        (distribution / "extra.txt").unlink()

        state = distribution / ".standardsforge"
        state.mkdir()
        receipt = setup._receipt_value(manifest, manifest_sha256)
        receipt["wheel_sha256"] = "0" * 64
        (state / "starter-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(setup.StarterSetupError, "does not match"):
            setup.validate_receipt(distribution, manifest, manifest_sha256)
        (state / "starter-receipt.json").unlink()
        with self.assertRaisesRegex(setup.StarterSetupError, "not owned"):
            setup.setup_starter(distribution, quiet=True)

    def test_consumer_pip_install_is_local_and_dependency_free(self) -> None:
        distribution = self._extract("pip-command")
        setup = _load_module(distribution / "setup.py", "starter_setup_pip")
        manifest, manifest_sha256 = setup.validate_bundle(distribution)
        venv_root = distribution / ".venv"
        venv_root.mkdir()
        setup._write_json_atomic(venv_root / setup.VENV_MARKER, {"bundle_manifest_sha256": manifest_sha256})
        python = setup._venv_python(venv_root)
        python.parent.mkdir(parents=True)
        python.write_bytes(b"placeholder")
        calls: list[list[str]] = []

        def record(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(setup, "_run", side_effect=record):
            returned = setup._prepare_venv(distribution, manifest, manifest_sha256)
        self.assertEqual(python, returned)
        command = calls[0]
        self.assertIn("--no-index", command)
        self.assertIn("--no-deps", command)
        self.assertIn("--force-reinstall", command)
        self.assertEqual(str(distribution / manifest["build"]["wheel_path"]), command[-1])

    def test_existing_venv_inner_link_is_rejected_before_pip(self) -> None:
        distribution = self._extract("venv-inner-link")
        setup = _load_module(distribution / "setup.py", "starter_setup_venv_link")
        manifest, manifest_sha256 = setup.validate_bundle(distribution)
        venv_root = distribution / manifest["install"]["venv_directory"]
        venv_root.mkdir()
        setup._write_json_atomic(
            venv_root / setup.VENV_MARKER,
            {"bundle_manifest_sha256": manifest_sha256},
        )
        python = setup._venv_python(venv_root)
        python.parent.mkdir(parents=True)
        python.write_bytes(b"placeholder")
        link_parent = venv_root / ("Lib" if os.name == "nt" else "lib")
        link_parent.mkdir()
        target = self.base / "venv-junction-target"
        target.mkdir(exist_ok=True)
        link = link_parent / "site-packages"
        if os.name == "nt":
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                text=True,
                capture_output=True,
                shell=False,
            )
            if created.returncode != 0:
                self.skipTest("Windows junction creation is unavailable.")
        else:
            link.symlink_to(target, target_is_directory=True)
        try:
            with patch.object(setup, "_run") as run:
                with self.assertRaisesRegex(setup.StarterSetupError, "symbolic link or junction"):
                    setup._prepare_venv(distribution, manifest, manifest_sha256)
                run.assert_not_called()
        finally:
            if link.is_symlink():
                link.unlink()
            elif link.exists():
                os.rmdir(link)

    def test_launcher_preserves_cli_arguments_and_exit_code(self) -> None:
        distribution = self._extract("launcher")
        setup = _load_module(distribution / "setup.py", "starter_setup_launcher")
        manifest, manifest_sha256 = setup.validate_bundle(distribution)
        state = distribution / ".standardsforge"
        state.mkdir()
        setup._write_json_atomic(state / "starter-receipt.json", setup._receipt_value(manifest, manifest_sha256))
        run = _load_module(distribution / "run.py", "starter_run_test")
        observed: list[str] = []

        def launch(command, **kwargs):
            observed.extend(command)
            return SimpleNamespace(returncode=7)

        arguments = ["run.py", "search", "axial load", "--principal", "local-user"]
        with patch.object(run.subprocess, "run", side_effect=launch) as mocked_run, patch.object(sys, "argv", arguments):
            code = run.main()
        self.assertEqual(7, code)
        self.assertEqual(arguments[1:], observed[-len(arguments[1:]):])
        self.assertFalse(mocked_run.call_args.kwargs["shell"])

    def test_archive_rejects_duplicate_unlisted_and_noncanonical_members(self) -> None:
        scenarios = ("duplicate", "unlisted", "unsafe")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                target = self.base / f"bad-{scenario}.zip"
                shutil.copyfile(self.archive, target)
                self.addCleanup(target.unlink, missing_ok=True)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_STORED) as archive:
                        if scenario == "duplicate":
                            name = archive.namelist()[0]
                        elif scenario == "unlisted":
                            name = f"standardsforge-starter-{self.result['version']}/extra.txt"
                        else:
                            name = f"standardsforge-starter-{self.result['version']}/../escape.txt"
                        archive.writestr(name, b"bad")
                with self.assertRaises(ValueError):
                    validate_starter_archive(target)

    def test_archive_rejects_symbolic_link_member_metadata(self) -> None:
        target = self.base / "bad-symlink.zip"
        self.addCleanup(target.unlink, missing_ok=True)
        with zipfile.ZipFile(self.archive, "r") as source, zipfile.ZipFile(
            target, "w", compression=zipfile.ZIP_STORED
        ) as destination:
            for original in source.infolist():
                info = zipfile.ZipInfo(original.filename, original.date_time)
                info.create_system = original.create_system
                info.external_attr = original.external_attr
                info.compress_type = original.compress_type
                info.extra = original.extra
                info.comment = original.comment
                if original.filename.endswith("/CONTENT-NOTICE.md"):
                    info.external_attr = 0o120777 << 16
                destination.writestr(info, source.read(original.filename))
        with self.assertRaises(ValueError):
            validate_starter_archive(target)

    def test_consumer_rejects_wrong_policy_identity_even_when_reinventoried(self) -> None:
        distribution = self._extract("wrong-policy")
        setup = _load_module(distribution / "setup.py", "starter_setup_wrong_policy")
        manifest_path = distribution / "bundle-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        policy_path = distribution / manifest["install"]["policy_path"]
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["policy_id"] = "wrong-policy"
        policy_bytes = (json.dumps(policy, indent=2) + "\n").encode("utf-8")
        policy_path.write_bytes(policy_bytes)
        policy_digest = hashlib.sha256(policy_bytes).hexdigest()
        manifest["install"]["policy_sha256"] = policy_digest
        inventory_entry = next(
            item for item in manifest["files"] if item["path"] == manifest["install"]["policy_path"]
        )
        inventory_entry.update({"bytes": len(policy_bytes), "sha256": policy_digest})
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(setup.StarterSetupError, "policy identity"):
            setup.validate_bundle(distribution)

    def test_setup_recovers_only_matching_marked_partial_state(self) -> None:
        distribution = self._extract("partial-recovery")
        setup = _load_module(distribution / "setup.py", "starter_setup_partial")
        manifest, manifest_sha256 = setup.validate_bundle(distribution)
        state = distribution / manifest["install"]["state_directory"]
        state.mkdir()
        (state / "interrupted.tmp").write_text("partial", encoding="utf-8")
        setup._write_json_atomic(
            state / "starter-setup-incomplete.json",
            {"bundle_manifest_sha256": manifest_sha256},
        )
        package_digests = iter(item["package_digest"] for item in manifest["packages"])

        def successful_command(command, **kwargs):
            if "install" in command:
                payload = {
                    "ok": True,
                    "result": {"package_digest": next(package_digests)},
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        placeholder_python = distribution / ".venv" / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        with patch.object(setup, "_prepare_venv", return_value=placeholder_python), patch.object(
            setup, "_run", side_effect=successful_command
        ), patch.object(setup, "_run_smokes"):
            result = setup.setup_starter(distribution, quiet=True)

        self.assertEqual("ready", result["status"])
        self.assertFalse((state / "interrupted.tmp").exists())
        self.assertFalse((state / "starter-setup-incomplete.json").exists())
        self.assertTrue((state / "starter-receipt.json").is_file())

    def test_existing_output_and_incomplete_wheel_provenance_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "already exists"):
            build_starter_distribution(self.wheel, self.provenance, self.archive)

        incomplete = self.base / "incomplete.provenance.json"
        value = json.loads(self.provenance.read_text(encoding="utf-8"))
        value["source_files"] = value["source_files"][:-1]
        incomplete.write_text(json.dumps(value), encoding="utf-8")
        output = self.base / "incomplete.zip"
        with self.assertRaises(ValueError):
            build_starter_distribution(self.wheel, incomplete, output)
        self.assertFalse(output.exists())
        self.assertFalse(output.with_suffix(".zip.sha256").exists())

    def test_wheel_directory_discovery_requires_one_exact_pair(self) -> None:
        self.assertEqual(
            (self.wheel, self.provenance),
            discover_wheel_inputs(self.base),
        )
        extra = self.base / "standardsforge-extra.whl"
        shutil.copyfile(self.wheel, extra)
        try:
            with self.assertRaisesRegex(ValueError, "exactly one"):
                discover_wheel_inputs(self.base)
        finally:
            extra.unlink()


if __name__ == "__main__":
    unittest.main()
