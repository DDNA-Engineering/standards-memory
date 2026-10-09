from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_installed_wheel as wheel_build  # noqa: E402



def _workflow_steps(text: str) -> dict[tuple[str, str], str]:
    """Map (job, step name) to the step's text for this repository's two-space workflow layout."""

    steps: dict[tuple[str, str], str] = {}
    job = None
    current = None
    in_jobs = False
    for line in text.splitlines():
        if line == "jobs:":
            in_jobs = True
            continue
        job_match = re.fullmatch(r"  ([A-Za-z0-9_-]+):", line) if in_jobs else None
        if job_match:
            job, current = job_match.group(1), None
            continue
        step_match = re.fullmatch(r"      - name: (.+)", line)
        if step_match and job is not None:
            current = (job, step_match.group(1).strip())
            steps[current] = ""
            continue
        if re.match(r"      - ", line):
            current = None
        if current is not None:
            steps[current] += line + "\n"
    return steps

class WheelBuildTests(unittest.TestCase):
    def test_source_inventory_excludes_generated_egg_info(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-wheel-source-") as temporary:
            root = Path(temporary)
            package = root / "src" / "standardsforge"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("VERSION = 'test'\n", encoding="utf-8")
            egg_info = root / "src" / "standardsforge.egg-info"
            egg_info.mkdir()
            (egg_info / "PKG-INFO").write_text("generated\n", encoding="utf-8")
            for name in (
                "build-toolchain.lock.json",
                "pyproject.toml",
                "uv.lock",
                "README.md",
                "LICENSE",
            ):
                (root / name).write_text(name + "\n", encoding="utf-8")

            with patch.object(wheel_build, "ROOT", root):
                paths = [item["path"] for item in wheel_build._source_inventory()]

        self.assertIn("src/standardsforge/__init__.py", paths)
        self.assertNotIn("src/standardsforge.egg-info/PKG-INFO", paths)

    def test_each_reproducibility_build_gets_its_own_clean_source_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-wheel-stage-") as temporary:
            root = Path(temporary) / "repo"
            package = root / "src" / "standardsforge"
            package.mkdir(parents=True)
            # Exact bytes: write_text would emit CRLF on Windows.
            (package / "__init__.py").write_bytes(b"VERSION = 'test'\n")
            (root / "pyproject.toml").write_bytes(b"[project]\n")
            base = Path(temporary) / "base"
            base.mkdir()
            with patch.object(wheel_build, "ROOT", root):
                first, second = wheel_build._stage_clean_sources(
                    base, ["pyproject.toml", "src/standardsforge/__init__.py"], 2
                )
            self.assertNotEqual(first, second)
            # Simulate the in-tree artifacts an earlier build leaves behind.
            (first / "build" / "lib").mkdir(parents=True)
            (first / "src" / "standardsforge.egg-info").mkdir()
            for tree in (first, second):
                self.assertEqual(
                    b"VERSION = 'test'\n",
                    (tree / "src" / "standardsforge" / "__init__.py").read_bytes(),
                )
            self.assertEqual(
                ["pyproject.toml", "src"], sorted(child.name for child in second.iterdir())
            )
            self.assertEqual(["standardsforge"], [child.name for child in (second / "src").iterdir()])

    def test_main_builds_each_wheel_from_a_distinct_source(self) -> None:
        source = (ROOT / "scripts" / "validate_installed_wheel.py").read_text(encoding="utf-8")
        self.assertIn("for build_number, source in enumerate(sources, start=1):", source)
        self.assertIn("_stage_clean_sources(base, wheel_source_paths, 2)", source)

    def test_publish_workflow_compares_the_wheel_digest_with_the_wheel(self) -> None:
        steps = _workflow_steps((ROOT / ".github" / "workflows" / "publish-pypi.yml").read_text(encoding="utf-8"))
        publish_names = [name for job, name in steps if job == "publish"]
        verify_name = next(name for name in publish_names if name.startswith("Verify the candidate wheel"))
        publish_name = next(name for name in publish_names if name.startswith("Publish exact candidate"))
        self.assertLess(publish_names.index(verify_name), publish_names.index(publish_name))
        native_name = next(name for job, name in steps if job == "native-install" and name.startswith("Install and exercise"))
        scripts = {
            "publish": steps[("publish", verify_name)],
            "native-install": steps[("native-install", native_name)],
        }
        for job, run in scripts.items():
            script = textwrap.dedent(re.search(r"<<'PY'\n(.*?)\n\s*PY\s*$", run, re.S).group(1))
            # Only the digest gate is exercised; stop before installation side effects.
            gate = script.split("subprocess.run(", 1)[0] if job == "native-install" else script
            with self.subTest(job=job), tempfile.TemporaryDirectory(prefix="standardsforge-publish-gate-") as temporary:
                dist = Path(temporary) / "dist"
                (dist / "publish").mkdir(parents=True)
                wheel = dist / "publish" / "standardsforge-0.1.0-py3-none-any.whl"
                wheel.write_bytes(b"built wheel")
                (dist / "wheel.sha256").write_text(hashlib.sha256(b"built wheel").hexdigest() + "\n", encoding="ascii")
                accepted = subprocess.run([sys.executable, "-I", "-c", gate], cwd=temporary, capture_output=True, text=True)
                self.assertEqual(0, accepted.returncode, accepted.stderr)
                wheel.write_bytes(b"substituted wheel")
                rejected = subprocess.run([sys.executable, "-I", "-c", gate], cwd=temporary, capture_output=True, text=True)
                self.assertNotEqual(0, rejected.returncode)
                self.assertIn("does not match the build digest", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
