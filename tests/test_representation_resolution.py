from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.cli import _parser  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402


PACK = ROOT / "examples" / "packs" / "fictional-adapter-v1"
POLICY = ROOT / "examples" / "policies" / "local-synthetic.json"


class RepresentationResolutionTests(unittest.TestCase):
    def test_same_edition_representations_are_explicit_and_selectable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-representation-test-") as temporary:
            root = Path(temporary)
            alternate = root / "alternate"
            shutil.copytree(PACK, alternate)
            manifest_path = alternate / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["representation"] = "reviewed_structure"
            manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
            inventory_path = alternate / "inventory.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            entry = next(item for item in inventory["files"] if item["path"] == "manifest.json")
            entry.update({"sha256": hashlib.sha256(manifest_bytes).hexdigest(), "bytes": len(manifest_bytes)})
            inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

            service = StandardsForgeService(root / "memory.db", root / "objects")
            curated_digest = service.install_pack(PACK, POLICY)["package_digest"]
            structural_digest = service.install_pack(alternate, POLICY)["package_digest"]

            with self.assertRaises(StandardsForgeError) as caught:
                service.resolve_document("EXAMPLE-SPEC-100", "local-user", "example:spec-100:2025-a")
            self.assertEqual("ambiguous_document", caught.exception.code)
            self.assertEqual(
                {"curated_records", "reviewed_structure"},
                {candidate["representation"] for candidate in caught.exception.details["candidates"]},
            )
            self.assertEqual(
                curated_digest,
                service.resolve_document(
                    "EXAMPLE-SPEC-100",
                    "local-user",
                    "example:spec-100:2025-a",
                    "curated_records",
                )["package_digest"],
            )
            self.assertEqual(
                structural_digest,
                service.resolve_document(
                    "EXAMPLE-SPEC-100",
                    "local-user",
                    "example:spec-100:2025-a",
                    "reviewed_structure",
                )["package_digest"],
            )
            self.assertEqual(
                curated_digest,
                service.get_clause(curated_digest, "4.2.1", "local-user")["package"]["package_digest"],
            )

        args = _parser().parse_args(
            [
                "resolve",
                "EXAMPLE-SPEC-100",
                "--principal",
                "local-user",
                "--representation",
                "reviewed_structure",
            ]
        )
        self.assertEqual("reviewed_structure", args.representation)


if __name__ == "__main__":
    unittest.main()
