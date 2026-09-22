from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jsonschema import ValidationError
from jsonschema.validators import validator_for


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "prepared_distribution"))

import build_prepared_distribution as distribution_module  # noqa: E402
from build_prepared_distribution import (  # noqa: E402
    _build_distribution_scope,
    _load_acquisition_snapshot,
    _load_json,
    _load_wheel_provenance,
    _validate_built_distribution,
    _validate_mcp_wheelhouse,
    build_distribution,
)
from verify_mcp_environment import verify_environment  # noqa: E402


class DistributionScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.acquisition = {
            "schema_version": "0.1.0",
            "catalog_id": "dla-active-mil-std-current",
            "scope": "Active MIL-STD records; current public components are leading notices plus the first substantive revision or incorporated change.",
            "source": "https://quicksearch.dla.mil/qsSearch.aspx",
            "source_origin": "official_dla_assist_quick_search",
            "source_data_updated": "2026-09-20",
            "generated_at": "2026-09-21T12:00:00Z",
            "completed_at": "2026-09-21T12:30:00Z",
            "inventory_only": False,
            "records": [
                {
                    "document_id": "MIL-STD-TEST-A",
                    "status": "A",
                    "discovery_error": None,
                    "current_components": [
                        {
                            "distribution_statement": "A",
                            "acquisition_status": "downloaded",
                        },
                        {
                            "distribution_statement": "D",
                            "acquisition_status": "restricted_distribution",
                        },
                    ],
                },
                {
                    "document_id": "MIL-STD-TEST-B",
                    "status": "A",
                    "discovery_error": None,
                    "current_components": [
                        {
                            "distribution_statement": "A",
                            "acquisition_status": "not_publicly_exposed",
                        }
                    ],
                },
            ],
            "summary": {
                "record_count": 2,
                "current_component_count": 3,
                "downloaded_count": 1,
                "restricted_count": 1,
                "not_publicly_exposed_count": 1,
                "failed_count": 0,
            },
        }
        self.index = {
            "corpus_id": "dla-active-mil-std-current-page-text",
            "summary": {
                "manifest_record_count": 2,
                "compilable_record_count": 1,
                "compiled_record_count": 1,
                "failed_record_count": 0,
                "restricted_only_record_count": 1,
                "verified_pdf_count": 1,
                "compiled_component_count": 1,
                "physical_pages": 2,
                "page_records": 1,
                "pages_without_text_records": 1,
            },
        }
        self.outline = SimpleNamespace(
            manifest={
                "representation": "derived_structure",
                "coverage": {
                    "parsed_source_coverage": "partial_automated_outline_with_unsupported_regions"
                },
            },
            records=[
                {
                    "derivation": {
                        "review_status": "automated_unreviewed",
                        "statement_role": "unclassified",
                    }
                }
            ],
            package_digest="a" * 64,
        )

    def test_scope_is_schema_valid_and_keeps_exclusions_and_review_limits_explicit(self) -> None:
        scope = _build_distribution_scope(
            self.acquisition, "b" * 64, self.index, self.outline
        )
        schema = _load_json(ROOT / "contracts" / "distribution-scope.schema.json")
        validator_for(schema)(schema).validate(scope)

        self.assertEqual(["MIL-STD"], scope["selection"]["document_classes"]["included"])
        self.assertFalse(scope["selection"]["components"]["historical_editions_included"])
        self.assertEqual(1, scope["outcomes"]["pages_without_text_records"])
        self.assertFalse(scope["representations"]["semantic_review"]["human_verified"])
        self.assertFalse(scope["limitations"]["publisher_currentness_is_project_baseline"])

        missing_publisher = copy.deepcopy(scope)
        del missing_publisher["publisher"]
        with self.assertRaises(ValidationError):
            validator_for(schema)(schema).validate(missing_publisher)

    def test_rejects_mismatched_counts_and_upgraded_outline_review(self) -> None:
        inconsistent = copy.deepcopy(self.acquisition)
        inconsistent["summary"]["current_component_count"] = 4
        with self.assertRaisesRegex(ValueError, "outcome counts do not close"):
            _build_distribution_scope(
                inconsistent, "b" * 64, self.index, self.outline
            )

        upgraded_outline = copy.deepcopy(self.outline)
        upgraded_outline.records[0]["derivation"]["review_status"] = "human_verified"
        with self.assertRaisesRegex(ValueError, "cannot claim reviewed structure"):
            _build_distribution_scope(
                self.acquisition, "b" * 64, self.index, upgraded_outline
            )

    def test_rejects_records_outside_declared_selection(self) -> None:
        wrong_class = copy.deepcopy(self.acquisition)
        wrong_class["records"][0]["document_id"] = "MIL-HDBK-TEST-A"
        with self.assertRaisesRegex(ValueError, "outside the MIL-STD selection"):
            _build_distribution_scope(
                wrong_class, "b" * 64, self.index, self.outline
            )

        inactive = copy.deepcopy(self.acquisition)
        inactive["records"][0]["status"] = "C"
        with self.assertRaisesRegex(ValueError, "outside the active-status filter"):
            _build_distribution_scope(
                inactive, "b" * 64, self.index, self.outline
            )

        discovery_failure = copy.deepcopy(self.acquisition)
        discovery_failure["records"][0]["discovery_error"] = "detail_fetch_failed"
        with self.assertRaisesRegex(ValueError, "discovery failure"):
            _build_distribution_scope(
                discovery_failure, "b" * 64, self.index, self.outline
            )

    def test_rejects_acquisition_manifest_that_does_not_match_corpus_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-scope-test-") as temporary:
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(json.dumps(self.acquisition), encoding="utf-8")
            actual_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            acquisition, digest = _load_acquisition_snapshot(
                manifest, {"acquisition_manifest_sha256": actual_digest}
            )
            self.assertEqual(self.acquisition, acquisition)
            self.assertEqual(actual_digest, digest)

            with self.assertRaisesRegex(ValueError, "does not match"):
                _load_acquisition_snapshot(
                    manifest, {"acquisition_manifest_sha256": "0" * 64}
                )

    def test_mcp_wheelhouse_is_closed_and_pinned(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-mcp-wheelhouse-test-") as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            requirements = root / "requirements.txt"

            def write_wheel(path: Path, project: str, version: str) -> str:
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(
                        f"{project}-{version}.dist-info/METADATA",
                        f"Metadata-Version: 2.4\nName: {project}\nVersion: {version}\n",
                    )
                    archive.writestr(
                        f"{project}-{version}.dist-info/WHEEL",
                        "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                    )
                return hashlib.sha256(path.read_bytes()).hexdigest()

            mcp = wheelhouse / "mcp-2.2.0-py3-none-any.whl"
            mcp_digest = write_wheel(mcp, "mcp", "2.2.0")
            requirements.write_text(
                f"mcp==2.2.0 --hash=sha256:{mcp_digest}\n", encoding="utf-8"
            )
            payloads, digest, requirements_digest = _validate_mcp_wheelhouse(
                wheelhouse, requirements
            )
            self.assertEqual(["wheelhouse/mcp-2.2.0-py3-none-any.whl"], [item[1] for item in payloads])
            self.assertEqual(64, len(digest))
            self.assertEqual(hashlib.sha256(requirements.read_bytes()).hexdigest(), requirements_digest)

            extra = wheelhouse / "mcp_types-2.2.0-py3-none-any.whl"
            write_wheel(extra, "mcp_types", "2.2.0")
            with self.assertRaisesRegex(ValueError, "exact locked artifact"):
                _validate_mcp_wheelhouse(wheelhouse, requirements)
            extra.unlink()

            duplicate = wheelhouse / "duplicate-2.2.0-py3-none-any.whl"
            write_wheel(duplicate, "mcp", "2.2.0")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                _validate_mcp_wheelhouse(wheelhouse, requirements)
            duplicate.unlink()

            requirements.write_text(
                f"mcp==2.2.0 --hash=sha256:{'0' * 64}\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "exact locked artifact"):
                _validate_mcp_wheelhouse(wheelhouse, requirements)

            requirements.write_text(
                f"mcp==2.2.0 --hash=sha256:{mcp_digest}\n"
                f"mcp-types==2.2.0 --hash=sha256:{'1' * 64}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing locked packages"):
                _validate_mcp_wheelhouse(wheelhouse, requirements)

    def test_prepared_mcp_launcher_rejects_all_overrides(self) -> None:
        launcher = (
            ROOT / "scripts" / "prepared_distribution" / "standardsforge-mcp.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$args.Count -ne 0", launcher)
        self.assertNotIn("@args", launcher)
        self.assertIn("$Python -I -m standardsforge.mcp_server", launcher)
        self.assertIn("--principal local-user --result-mode structured_only", launcher)
        self.assertNotIn("setup.ps1')", launcher)
        cli_launcher = (
            ROOT / "scripts" / "prepared_distribution" / "standardsforge.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$Python -I -m standardsforge", cli_launcher)
        setup = (
            ROOT / "scripts" / "prepared_distribution" / "setup.ps1"
        ).read_text(encoding="utf-8")
        self.assertNotIn("$Python -m ", setup)
        self.assertIn("$McpRequirementsPath = Join-Path", setup.split("function", 1)[0])

    def test_prepared_environment_must_match_exact_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-mcp-environment-test-") as temporary:
            requirements = Path(temporary) / "requirements.txt"
            requirements.write_text(
                f"mcp==2.2.0 --hash=sha256:{'0' * 64}\n", encoding="utf-8"
            )
            expected = [
                ("standardsforge", "0.1.0a1"),
                ("mcp", "2.2.0"),
                ("pip", "25.0"),
            ]
            verify_environment(requirements, "0.1.0a1", expected)
            with self.assertRaisesRegex(RuntimeError, "differs from"):
                verify_environment(
                    requirements,
                    "0.1.0a1",
                    [*expected, ("injected-package", "1.0")],
                )
            with self.assertRaisesRegex(RuntimeError, "differs from"):
                verify_environment(
                    requirements,
                    "0.1.0a1",
                    [(name, "9.9" if name == "mcp" else version) for name, version in expected],
                )

    def test_distribution_bundles_exact_acquisition_and_reopens_inventory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-distribution-test-") as temporary:
            root = Path(temporary)
            repository = root / "repository"
            corpus = root / "corpus"
            corpus_packs = corpus / "packs"
            output = root / "standardsforge-ready-test.zip"
            corpus_packs.mkdir(parents=True)
            (repository / "contracts").mkdir(parents=True)
            for schema_name in (
                "distribution-scope.schema.json",
                "prepared-distribution.schema.json",
                "wheel-build-provenance.schema.json",
            ):
                shutil.copyfile(
                    ROOT / "contracts" / schema_name,
                    repository / "contracts" / schema_name,
                )
            static_root = repository / "scripts" / "prepared_distribution"
            static_root.mkdir(parents=True)
            for name in (
                "README.md",
                "prepared_runtime.py",
                "setup.py",
                "run.py",
                "setup.sh",
                "standardsforge.sh",
                "setup.ps1",
                "standardsforge.ps1",
                "standardsforge-mcp.ps1",
                "smoke_mcp.py",
                "verify_mcp_environment.py",
                "CONTENT-NOTICE.md",
            ):
                (static_root / name).write_text(name + "\n", encoding="utf-8")
            for name, value in (
                ("LICENSE", "test license\n"),
                ("README.md", "test source readme\n"),
                (
                    "build-toolchain.lock.json",
                    (ROOT / "build-toolchain.lock.json").read_text(encoding="utf-8"),
                ),
                ("pyproject.toml", "[project]\nname='standardsforge'\nversion='test'\n"),
                ("uv.lock", "version = 1\n"),
            ):
                (repository / name).write_text(value, encoding="utf-8")
            source_init = repository / "src" / "standardsforge" / "__init__.py"
            source_init.parent.mkdir(parents=True)
            source_init.write_text("__version__ = 'test'\n", encoding="utf-8")

            archive = corpus_packs / "test-pack.zip"
            archive.write_bytes(b"synthetic corpus archive")
            acquisition = copy.deepcopy(self.acquisition)
            acquisition["source_origin"] = "official_dla_assist_quick_search"
            acquisition["summary"] = {
                "record_count": 1,
                "current_component_count": 1,
                "downloaded_count": 1,
                "restricted_count": 0,
                "not_publicly_exposed_count": 0,
                "failed_count": 0,
            }
            acquisition["records"] = [
                {
                    "document_id": "MIL-STD-TEST-A",
                    "status": "A",
                    "discovery_error": None,
                    "current_components": [
                        {
                            "distribution_statement": "A",
                            "acquisition_status": "downloaded",
                        }
                    ],
                }
            ]
            acquisition_path = root / "acquisition.json"
            acquisition_path.write_text(
                json.dumps(acquisition, sort_keys=True) + "\n", encoding="utf-8"
            )
            acquisition_sha256 = hashlib.sha256(acquisition_path.read_bytes()).hexdigest()
            index = {
                "schema_version": "0.1.0",
                "corpus_id": "test-corpus",
                "compiler_version": "test-corpus-compiler-1",
                "acquisition_manifest_sha256": acquisition_sha256,
                "failures": [],
                "entries": [
                    {
                        "archive_path": "packs/test-pack.zip",
                        "archive_bytes": archive.stat().st_size,
                        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "package_digest": "c" * 64,
                        "pack_id": "test.corpus.pack",
                    }
                ],
                "summary": {
                    "status": "complete",
                    "manifest_record_count": 1,
                    "compilable_record_count": 1,
                    "compiled_record_count": 1,
                    "failed_record_count": 0,
                    "restricted_only_record_count": 0,
                    "verified_pdf_count": 1,
                    "compiled_component_count": 1,
                    "physical_pages": 1,
                    "page_records": 1,
                    "pages_without_text_records": 0,
                },
            }
            index_path = corpus / "corpus.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")

            policy_root = repository / ".standardsforge" / "policies"
            policy_root.mkdir(parents=True)
            for name, pack_ids in (
                ("mil-std-corpus-local.json", ["test.corpus.pack"]),
                ("mil-std-810h-derived-outline-local.json", ["test.outline.pack"]),
            ):
                (policy_root / name).write_text(
                    json.dumps(
                        {
                            "principal_id": "local-user",
                            "allowed_pack_ids": pack_ids,
                            "allowed_content_classes": ["public_government_standard"],
                        }
                    ),
                    encoding="utf-8",
                )
            wheel = root / "standardsforge-test-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as built_wheel:
                for name, value in (
                    (
                        "standardsforge-test.dist-info/WHEEL",
                        "Wheel-Version: 1.0\nGenerator: setuptools (84.0.0)\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                    ),
                    (
                        "standardsforge-test.dist-info/METADATA",
                        "Metadata-Version: 2.4\nName: standardsforge\nVersion: test\n",
                    ),
                ):
                    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                    built_wheel.writestr(info, value)
            mcp_wheelhouse = root / "mcp-wheelhouse"
            mcp_wheelhouse.mkdir()
            mcp_wheel = mcp_wheelhouse / "mcp-2.2.0-py3-none-any.whl"
            with zipfile.ZipFile(mcp_wheel, "w") as built_wheel:
                info = zipfile.ZipInfo(
                    "mcp-2.2.0.dist-info/METADATA", (2026, 1, 1, 0, 0, 0)
                )
                built_wheel.writestr(
                    info, "Metadata-Version: 2.4\nName: mcp\nVersion: 2.2.0\n"
                )
                built_wheel.writestr(
                    "mcp-2.2.0.dist-info/WHEEL",
                    "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                )
            mcp_requirements = root / "mcp-requirements.txt"
            mcp_requirements.write_text(
                "mcp==2.2.0 --hash=sha256:"
                + hashlib.sha256(mcp_wheel.read_bytes()).hexdigest()
                + "\n",
                encoding="utf-8",
            )
            provenance_path = root / f"{wheel.name}.provenance.json"
            source_paths = [
                repository / "build-toolchain.lock.json",
                repository / "pyproject.toml",
                repository / "uv.lock",
                repository / "README.md",
                repository / "LICENSE",
                source_init,
            ]
            source_records = [
                {
                    "path": path.relative_to(repository).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in source_paths
            ]
            build_tool_lock = repository / "build-toolchain.lock.json"
            build_tool = json.loads(build_tool_lock.read_text(encoding="utf-8"))["build_backend"]
            provenance_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "project": "standardsforge",
                        "version": "test",
                        "source_date_epoch": 1767225600,
                        "build_backend": "setuptools==84.0.0",
                        "wheel_generator": "setuptools (84.0.0)",
                        "builder": {"python": "3.12.test", "pip": "test"},
                        "source_files": source_records,
                        "wheel_source_paths": sorted(
                            item["path"]
                            for item in source_records
                            if item["path"] not in {"build-toolchain.lock.json", "uv.lock"}
                        ),
                        "release_metadata_paths": ["uv.lock"],
                        "build_tool": {
                            "lock_path": "build-toolchain.lock.json",
                            "lock_sha256": hashlib.sha256(build_tool_lock.read_bytes()).hexdigest(),
                            "artifact": {
                                "filename": build_tool["filename"],
                                "bytes": build_tool["bytes"],
                                "sha256": build_tool["sha256"],
                            },
                        },
                        "authentication": "none",
                        "wheel": {
                            "filename": wheel.name,
                            "bytes": wheel.stat().st_size,
                            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                            "clean_build_count": 2,
                        },
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            outline_directory = root / "outline"
            outline_directory.mkdir()
            outline = SimpleNamespace(
                manifest={
                    "pack_id": "test.outline.pack",
                    "representation": "derived_structure",
                    "coverage": {"parsed_source_coverage": "synthetic qualified scope"},
                },
                records=tuple(copy.deepcopy(self.outline.records)),
                package_digest="d" * 64,
            )

            def write_outline(_source: Path, destination: Path, *, compresslevel: int) -> None:
                self.assertEqual(9, compresslevel)
                destination.write_bytes(b"synthetic outline archive")

            with patch.object(distribution_module, "REPOSITORY_ROOT", repository), patch.object(
                distribution_module, "validate_pack_directory", return_value=outline
            ), patch.object(distribution_module, "write_pack_archive", side_effect=write_outline):
                result = build_distribution(
                    index_path,
                    acquisition_path,
                    outline_directory,
                    wheel,
                    provenance_path,
                    mcp_wheelhouse,
                    mcp_requirements,
                    output,
                    "test",
                    9,
                )

                self.assertEqual(output.resolve(), Path(result["output"]))
                prefix = "standardsforge-ready-test/"
                _validate_built_distribution(output, prefix)
                with zipfile.ZipFile(output) as built:
                    self.assertEqual(
                        acquisition_path.read_bytes(),
                        built.read(prefix + "provenance/acquisition-manifest.json"),
                    )
                    self.assertEqual(0o100755, built.getinfo(prefix + "setup.sh").external_attr >> 16)
                    self.assertEqual(0o100755, built.getinfo(prefix + "standardsforge.sh").external_attr >> 16)
                    manifest = json.loads(built.read(prefix + "bundle-manifest.json"))
                    paths = {item["path"] for item in manifest["files"]}
                    self.assertIn("provenance/source-baseline.json", paths)
                    self.assertIn("provenance/acquisition-manifest.json", paths)
                    self.assertIn("provenance/wheel-build.json", paths)
                    self.assertIn("wheelhouse/mcp-2.2.0-py3-none-any.whl", paths)
                    self.assertIn("standardsforge-mcp.ps1", paths)
                    self.assertIn("prepared_runtime.py", paths)
                    self.assertIn("setup.py", paths)
                    self.assertIn("run.py", paths)
                    self.assertIn("setup.sh", paths)
                    self.assertIn("standardsforge.sh", paths)
                    self.assertIn("policies/prepared-local.json", paths)
                    self.assertIn("smoke_mcp.py", paths)
                    self.assertIn("verify_mcp_environment.py", paths)
                    self.assertEqual("mcp==2.2.0", manifest["build"]["mcp_requirement"])
                    self.assertEqual(1, manifest["build"]["mcp_wheel_count"])
                    self.assertEqual("CPython >=3.11", manifest["build"]["core_runtime_python"])
                    self.assertEqual(
                        ["windows_x86_64", "linux_x86_64", "macos_arm64", "macos_x86_64"],
                        manifest["build"]["core_runtime_platforms"],
                    )
                    self.assertEqual("CPython 3.12", manifest["build"]["mcp_runtime_python"])
                    self.assertEqual("win_amd64", manifest["build"]["mcp_runtime_platform"])
                    self.assertEqual(
                        hashlib.sha256(mcp_requirements.read_bytes()).hexdigest(),
                        manifest["build"]["mcp_requirements_sha256"],
                    )

                second_output = root / "standardsforge-ready-test-second.zip"
                build_distribution(
                    index_path,
                    acquisition_path,
                    outline_directory,
                    wheel,
                    provenance_path,
                    mcp_wheelhouse,
                    mcp_requirements,
                    second_output,
                    "test",
                    9,
                )
                self.assertEqual(output.read_bytes(), second_output.read_bytes())

                tampered_output = root / "standardsforge-ready-test-tampered.zip"
                with zipfile.ZipFile(second_output, "r") as source_archive, zipfile.ZipFile(
                    tampered_output, "w"
                ) as target_archive:
                    for info in source_archive.infolist():
                        payload = source_archive.read(info.filename)
                        if info.filename == prefix + "bundle-manifest.json":
                            changed_manifest = json.loads(payload)
                            changed_manifest["build"]["mcp_wheelhouse_sha256"] = "0" * 64
                            payload = (
                                json.dumps(changed_manifest, indent=2, sort_keys=True) + "\n"
                            ).encode("utf-8")
                        target_archive.writestr(info, payload)
                with self.assertRaisesRegex(ValueError, "wheelhouse identity"):
                    _validate_built_distribution(tampered_output, prefix)

                with zipfile.ZipFile(output, "a") as built:
                    built.writestr(prefix + "unlisted.txt", "not inventoried")
                with self.assertRaisesRegex(ValueError, "unlisted or missing"):
                    _validate_built_distribution(output, prefix)

                (repository / "README.md").write_text(
                    "changed after the verified wheel build\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "source changed"):
                    _load_wheel_provenance(provenance_path, wheel, "test")


if __name__ == "__main__":
    unittest.main()
