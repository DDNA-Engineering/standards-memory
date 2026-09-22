from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_installed_wheel as wheel_build  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
