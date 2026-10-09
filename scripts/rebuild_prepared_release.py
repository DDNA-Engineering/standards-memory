"""Build the next prepared release from a published prepared release and new code.

The previous release's acquisition snapshot, corpus packs, automated outline,
recovery packs, coverage ledgers and real-document suites are reused unchanged
after their closed inventory is verified against the expected archive digest.
Because real-document runs are bound to the exact runtime sources, every suite is
re-run against the new wheel in a fresh environment and store before
``build_prepared_distribution.build_distribution`` binds the result. An optional
reviewed supplement (``scripts/build_reviewed_supplement.py``) is added the same way.

Nothing here acquires standards, compiles PDFs, or changes the previous archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import venv
import zipfile
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from build_prepared_distribution import build_distribution  # noqa: E402

RECOVERY_NAMES = ("transcription", "semantics")
CONTENT_CLASS = "public_government_standard"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def extract_previous(archive: Path, expected_sha256: str, destination: Path) -> Path:
    """Verify the archive digest, extract it safely, and close its inventory."""
    if _sha256(archive) != expected_sha256:
        raise ValueError("The previous prepared archive does not match the expected SHA-256.")
    with zipfile.ZipFile(archive) as bundle:
        roots = set()
        for info in bundle.infolist():
            relative = PurePosixPath(info.filename.rstrip("/"))
            if (not info.filename or "\\" in info.filename or relative.is_absolute() or ".." in relative.parts
                    or ":" in relative.parts[0] or ((info.external_attr >> 16) & 0o170000) == stat.S_IFLNK):
                raise ValueError(f"Unsafe previous archive member: {info.filename!r}")
            roots.add(relative.parts[0])
        if len(roots) != 1:
            raise ValueError("The previous archive must contain one distribution root.")
        bundle.extractall(destination)
    root = destination / roots.pop()
    manifest = _load_json(root / "bundle-manifest.json")
    expected = {item["path"]: item for item in manifest["files"]}
    observed = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and path.name != "bundle-manifest.json"
    }
    if observed != set(expected):
        raise ValueError("The previous prepared release has missing or unlisted files.")
    for relative, item in expected.items():
        target = root / relative
        if target.stat().st_size != item["bytes"] or _sha256(target) != item["sha256"]:
            raise ValueError(f"The previous prepared release failed inventory validation: {relative}")
    return root


def _find_wheel(wheel_dir: Path, version: str) -> tuple[Path, Path]:
    wheels = sorted(wheel_dir.glob(f"standardsforge-{version}-py3-none-any.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected exactly one standardsforge-{version} wheel in {wheel_dir}.")
    provenance = wheels[0].with_name(wheels[0].name + ".provenance.json")
    if not provenance.is_file():
        raise ValueError(f"The wheel provenance is missing: {provenance}")
    return wheels[0], provenance


class Runtime:
    """A fresh environment with only the new wheel, plus a fresh local store."""

    def __init__(self, work: Path, wheel: Path):
        self.root = work / "runtime"
        venv.EnvBuilder(with_pip=True, symlinks=False).create(self.root / "venv")
        self.python = self.root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
        self.environment.update(PIP_NO_INDEX="1", PYTHONDONTWRITEBYTECODE="1")
        self._run([str(self.python), "-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--no-deps", str(wheel)])

    def _run(self, command: list[str]) -> str:
        result = subprocess.run(command, cwd=self.root, env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command[3:6])}\n{result.stderr.decode('utf-8', 'replace')}")
        return result.stdout.decode("utf-8")

    def cli(self, *arguments: str) -> str:
        state = self.root / "state"
        return self._run([str(self.python), "-I", "-m", "standardsforge", "--db", str(state / "memory.db"),
                          "--store", str(state / "objects"), *arguments])


def _qualify(runtime: Runtime, suite: Path, output: Path) -> None:
    output.unlink(missing_ok=True)
    runtime.cli("qualify-real", str(suite), "--principal", "local-user", "--output", str(output))


def rebuild(previous_archive: Path, previous_sha256: str, wheel_dir: Path, mcp_wheelhouse: Path, tokenizer_artifact: Path,
            work: Path, output: Path, version: str, reviewed_supplement: Path | None = None) -> dict:
    work = work.resolve()
    if work.exists() and any(work.iterdir()):
        raise ValueError(f"The work directory must be new or empty: {work}")
    work.mkdir(parents=True, exist_ok=True)
    wheel, wheel_provenance = _find_wheel(wheel_dir.resolve(), version)
    print("Verifying and extracting the previous prepared release.", flush=True)
    previous = extract_previous(previous_archive.resolve(), previous_sha256, work / "previous")
    previous_manifest = _load_json(previous / "bundle-manifest.json")
    recovery_entries = {PurePosixPath(item["path"]).stem: item for item in previous_manifest["state"].get("qualified_packs", [])}
    if set(recovery_entries) != set(RECOVERY_NAMES):
        raise ValueError("The previous release must carry exactly the MIL-STD-1661 transcription and semantics packs.")

    print("Installing the previous content into a fresh store with the new wheel (several minutes).", flush=True)
    runtime = Runtime(work, wheel)
    policies = previous / "policies"
    runtime.cli("install-corpus", str(previous / "corpus" / "corpus.json"), "--policy", str(policies / "mil-std-corpus-local.json"))
    outline_archive = previous / "packs" / "mil-std-810h-derived-outline.zip"
    runtime.cli("install", str(outline_archive), "--policy", str(policies / "mil-std-810h-derived-outline-local.json"))

    recovery = work / "recovery"
    for name in RECOVERY_NAMES:
        entry = recovery_entries[name]
        (recovery / "packs").mkdir(parents=True, exist_ok=True)
        (recovery / "policies").mkdir(parents=True, exist_ok=True)
        (recovery / "qualification").mkdir(parents=True, exist_ok=True)
        archive = recovery / "packs" / f"mil-std-1661-{name}.zip"
        shutil.copyfile(previous / entry["path"], archive)
        policy = recovery / "policies" / f"{name}.json"
        runtime.cli("write-pack-policy", str(archive), str(policy), "--principal", "local-user", "--content-class", CONTENT_CLASS)
        runtime.cli("install", str(archive), "--policy", str(policy))
        shutil.copyfile(previous / entry["suite_path"], recovery / "qualification" / f"{name}-suite.json")
    shutil.copyfile(previous / "qualification" / "recovery" / "coverage.json", recovery / "qualification" / "coverage.json")

    reviewed = None
    if reviewed_supplement is not None:
        reviewed = work / "reviewed"
        shutil.copytree(reviewed_supplement.resolve(), reviewed)
        for item in _load_json(reviewed / "supplement.json")["packs"]:
            runtime.cli("install", str(reviewed / "packs" / f"{item['slug']}.zip"), "--policy", str(reviewed / "policies" / f"{item['slug']}.json"))

    print("Re-running every real-document suite against the new wheel.", flush=True)
    qualification = work / "qualification"
    shutil.copytree(previous / "qualification" / "coverage", qualification / "coverage")
    shutil.copyfile(previous / "qualification" / "real-suite.json", qualification / "real-suite.json")
    _qualify(runtime, qualification / "real-suite.json", qualification / "real-benchmark.json")
    for name in RECOVERY_NAMES:
        _qualify(runtime, recovery / "qualification" / f"{name}-suite.json", recovery / "qualification" / f"{name}-run.json")
    if reviewed is not None:
        for item in _load_json(reviewed / "supplement.json")["packs"]:
            slug = item["slug"]
            _qualify(runtime, reviewed / "qualification" / f"{slug}-suite.json", reviewed / "qualification" / f"{slug}-run.json")

    outline = work / "outline"
    with zipfile.ZipFile(outline_archive) as archive:
        archive.extractall(outline)

    print("Binding the new prepared distribution.", flush=True)
    result = build_distribution(
        previous / "corpus" / "corpus.json",
        previous / "provenance" / "acquisition-manifest.json",
        outline,
        wheel,
        wheel_provenance,
        mcp_wheelhouse,
        tokenizer_artifact,
        output,
        version,
        9,
        outline_policy_path=policies / "mil-std-810h-derived-outline-local.json",
        qualification_directory=qualification,
        recovery_directory=recovery,
        reviewed_directory=reviewed,
        corpus_policy_path=policies / "mil-std-corpus-local.json",
    )
    shutil.rmtree(runtime.root)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--previous-archive", required=True, type=Path)
    parser.add_argument("--previous-sha256", required=True)
    parser.add_argument("--wheel-dir", required=True, type=Path, help="Holds the new wheel and its .provenance.json")
    parser.add_argument("--mcp-wheelhouse", required=True, type=Path, help="Union of the three Windows MCP locks")
    parser.add_argument("--tokenizer-artifact", required=True, type=Path)
    parser.add_argument("--reviewed-supplement", type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    result = rebuild(args.previous_archive, args.previous_sha256, args.wheel_dir, args.mcp_wheelhouse, args.tokenizer_artifact,
                     args.work_dir, args.output, args.version, args.reviewed_supplement)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
