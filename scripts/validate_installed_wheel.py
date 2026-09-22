from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

from jsonschema.validators import validator_for


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATE_EPOCH = "1767225600"
BUILD_TOOL_LOCK = ROOT / "build-toolchain.lock.json"


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_build_tool(directory: Path) -> tuple[dict[str, object], Path]:
    lock = json.loads(BUILD_TOOL_LOCK.read_text(encoding="utf-8"))
    if set(lock) != {"schema_version", "build_backend"} or lock["schema_version"] != "0.1.0":
        raise RuntimeError("The build-toolchain lock is malformed.")
    backend = lock["build_backend"]
    if not isinstance(backend, dict) or set(backend) != {
        "name", "version", "filename", "bytes", "sha256", "index"
    }:
        raise RuntimeError("The build backend lock is malformed.")
    if backend["name"] != "setuptools" or backend["version"] != "84.0.0":
        raise RuntimeError("The build backend lock does not select setuptools 84.0.0.")
    artifact = directory.resolve() / str(backend["filename"])
    if not artifact.is_file() or artifact.is_symlink():
        raise RuntimeError(f"The locked build backend artifact is missing: {artifact}")
    if artifact.stat().st_size != backend["bytes"] or _sha256(artifact) != backend["sha256"]:
        raise RuntimeError("The build backend artifact does not match the lock.")
    return lock, artifact


def _source_inventory() -> list[dict[str, object]]:
    inputs = [
        ROOT / name
        for name in (
            "build-toolchain.lock.json",
            "pyproject.toml",
            "uv.lock",
            "README.md",
            "LICENSE",
        )
    ]
    inputs.extend(
        path
        for path in sorted((ROOT / "src").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    return [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(inputs, key=lambda value: value.relative_to(ROOT).as_posix())
    ]


def _wheel_source_paths(source_files: list[dict[str, object]]) -> list[str]:
    excluded = {"build-toolchain.lock.json", "uv.lock"}
    return [str(item["path"]) for item in source_files if item["path"] not in excluded]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build twice, verify, install, and optionally retain a reproducible core wheel."
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--build-tool-dir",
        type=Path,
        default=ROOT / "build" / "toolchain-cache",
        help="Directory containing the exact backend wheel named by build-toolchain.lock.json.",
    )
    args = parser.parse_args()
    build_tool_lock, build_tool_artifact = _load_build_tool(args.build_tool_dir)
    with tempfile.TemporaryDirectory(prefix="standardsforge-wheel-") as temporary:
        base = Path(temporary)
        clean_env = dict(os.environ)
        clean_env.pop("PYTHONPATH", None)
        clean_env["PYTHONNOUSERSITE"] = "1"
        clean_env["PYTHONHASHSEED"] = "0"
        clean_env["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
        clean_env["PIP_NO_INDEX"] = "1"
        clean_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        source = base / "source"
        source.mkdir()
        shutil.copytree(ROOT / "src", source / "src")
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy2(ROOT / name, source / name)

        builder_environment = base / "builder"
        venv.EnvBuilder(with_pip=True, clear=True).create(builder_environment)
        builder_python = (
            builder_environment / "Scripts" / "python.exe"
            if os.name == "nt"
            else builder_environment / "bin" / "python"
        )
        _run(
            [
                str(builder_python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--force-reinstall",
                str(build_tool_artifact),
            ],
            cwd=base,
            env=clean_env,
        )
        builder_versions = json.loads(
            subprocess.run(
                [
                    str(builder_python),
                    "-I",
                    "-c",
                    (
                        "import importlib.metadata,json,sys;"
                        "print(json.dumps({'python':sys.version.split()[0],"
                        "'pip':importlib.metadata.version('pip'),"
                        "'setuptools':importlib.metadata.version('setuptools')}))"
                    ),
                ],
                cwd=base,
                env=clean_env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        if builder_versions["setuptools"] != "84.0.0":
            raise RuntimeError("The isolated builder did not load the locked setuptools version.")

        wheels: list[Path] = []
        for build_number in (1, 2):
            wheelhouse = base / f"wheelhouse-{build_number}"
            wheelhouse.mkdir()
            _run(
                [
                    str(builder_python),
                    "-m",
                    "pip",
                    "wheel",
                    str(source),
                    "--no-deps",
                    "--no-index",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(wheelhouse),
                ],
                cwd=base,
                env=clean_env,
            )
            built = list(wheelhouse.glob("standardsforge-*.whl"))
            if len(built) != 1:
                raise RuntimeError(
                    f"Expected one StandardsForge wheel in build {build_number}, found {len(built)}."
                )
            wheels.append(built[0])
        first_wheel_digest = hashlib.sha256(wheels[0].read_bytes()).hexdigest()
        second_wheel_digest = hashlib.sha256(wheels[1].read_bytes()).hexdigest()
        if first_wheel_digest != second_wheel_digest:
            raise RuntimeError("Two clean wheel builds produced different bytes.")
        with zipfile.ZipFile(wheels[0]) as archive:
            if any(info.date_time != (2026, 1, 1, 0, 0, 0) for info in archive.infolist()):
                raise RuntimeError("The wheel did not honor the fixed SOURCE_DATE_EPOCH.")
            wheel_metadata_name = next(
                info.filename
                for info in archive.infolist()
                if info.filename.endswith(".dist-info/WHEEL")
            )
            wheel_metadata = archive.read(wheel_metadata_name).decode("utf-8")
            package_metadata_name = next(
                info.filename
                for info in archive.infolist()
                if info.filename.endswith(".dist-info/METADATA")
            )
            package_metadata = archive.read(package_metadata_name).decode("utf-8")
        wheel_generator = next(
            line.removeprefix("Generator: ")
            for line in wheel_metadata.splitlines()
            if line.startswith("Generator: ")
        )
        if wheel_generator != "setuptools (84.0.0)":
            raise RuntimeError("The wheel does not identify the pinned build backend.")
        version = next(
            line.removeprefix("Version: ")
            for line in package_metadata.splitlines()
            if line.startswith("Version: ")
        )

        environment = base / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = (
            environment / "Scripts" / "python.exe"
            if os.name == "nt"
            else environment / "bin" / "python"
        )
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--force-reinstall",
                str(wheels[0]),
            ],
            cwd=base,
            env=clean_env,
        )
        _run([str(python), "-m", "pip", "check"], cwd=base, env=clean_env)

        run_directory = base / "outside-checkout"
        run_directory.mkdir()
        smoke = (
            "from pathlib import Path; "
            "from standardsforge.service import StandardsForgeService; "
            "service=StandardsForgeService(Path('memory.db'), Path('objects')); "
            "result=service.search('core smoke', 'wheel-user'); "
            "assert result['operation']=='search' and result['results']==[]"
        )
        _run([str(python), "-I", "-c", smoke], cwd=run_directory, env=clean_env)
        doctor_smoke = (
            "from pathlib import Path; "
            "from standardsforge.doctor import run_doctor; "
            "from standardsforge.service import StandardsForgeService; "
            "service=StandardsForgeService(Path('doctor.db'), Path('doctor-objects')); "
            "[service.install_pack(Path(value), Path(__import__('sys').argv[3])) for value in __import__('sys').argv[1:3]]; "
            "result=run_doctor(Path('doctor.db'), Path('doctor-objects'), policy_path=Path(__import__('sys').argv[3]), principal_id='local-user', full_integrity=True); "
            "assert result['ready'] and result['integrity']['complete'] and result['query_smoke']['status']=='pass'"
        )
        _run(
            [
                str(python),
                "-I",
                "-c",
                doctor_smoke,
                str(ROOT / "examples" / "packs" / "fictional-adapter-v1"),
                str(ROOT / "examples" / "packs" / "fictional-adapter-v2"),
                str(ROOT / "examples" / "policies" / "local-synthetic.json"),
            ],
            cwd=run_directory,
            env=clean_env,
        )

        source_files = _source_inventory()
        provenance = {
            "schema_version": "0.1.0",
            "project": "standardsforge",
            "version": version,
            "source_date_epoch": int(SOURCE_DATE_EPOCH),
            "build_backend": "setuptools==84.0.0",
            "wheel_generator": wheel_generator,
            "builder": {
                "python": builder_versions["python"],
                "pip": builder_versions["pip"],
            },
            "source_files": source_files,
            "wheel_source_paths": _wheel_source_paths(source_files),
            "release_metadata_paths": ["uv.lock"],
            "build_tool": {
                "lock_path": BUILD_TOOL_LOCK.name,
                "lock_sha256": _sha256(BUILD_TOOL_LOCK),
                "artifact": {
                    "filename": build_tool_artifact.name,
                    "bytes": build_tool_artifact.stat().st_size,
                    "sha256": _sha256(build_tool_artifact),
                },
            },
            "authentication": "none",
            "wheel": {
                "filename": wheels[0].name,
                "bytes": wheels[0].stat().st_size,
                "sha256": first_wheel_digest,
                "clean_build_count": 2,
            },
        }
        schema = json.loads(
            (ROOT / "contracts" / "wheel-build-provenance.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        validator_class(schema).validate(provenance)

        retained_wheel: str | None = None
        retained_provenance: str | None = None
        if args.output_dir is not None:
            output_directory = args.output_dir.resolve()
            output_directory.mkdir(parents=True, exist_ok=True)
            wheel_target = output_directory / wheels[0].name
            provenance_target = output_directory / f"{wheels[0].name}.provenance.json"
            if wheel_target.exists() or provenance_target.exists():
                raise RuntimeError("The reproducible wheel or its provenance output already exists.")
            wheel_partial = output_directory / f".{wheels[0].name}.partial"
            provenance_partial = output_directory / f".{wheels[0].name}.provenance.json.partial"
            try:
                shutil.copyfile(wheels[0], wheel_partial)
                provenance_partial.write_text(
                    json.dumps(provenance, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                wheel_partial.replace(wheel_target)
                provenance_partial.replace(provenance_target)
            finally:
                wheel_partial.unlink(missing_ok=True)
                provenance_partial.unlink(missing_ok=True)
            retained_wheel = str(wheel_target)
            retained_provenance = str(provenance_target)

        print(
            json.dumps(
                {
                    "ok": True,
                    "wheel": wheels[0].name,
                    "wheel_generator": wheel_generator,
                    "wheel_sha256": first_wheel_digest,
                    "source_date_epoch": int(SOURCE_DATE_EPOCH),
                    "reproducible_clean_builds": 2,
                    "installed_without_extras": True,
                    "outside_checkout": True,
                    "pythonpath_removed": True,
                    "core_read_smoke": "search_empty_authorized_store",
                    "core_doctor_smoke": "full_integrity_exact_query_without_mcp_extra",
                    "retained_wheel": retained_wheel,
                    "retained_provenance": retained_provenance,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
