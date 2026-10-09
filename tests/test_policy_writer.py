from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.cli import _parser as cli_parser, _run as cli_run  # noqa: E402
from standardsforge.policy import load_policy, write_pack_policy  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402


PACK = ROOT / "examples" / "packs" / "fictional-adapter-v1"


class PackPolicyWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-pack-policy-test-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_writes_exact_explicit_policy_and_installs_pack(self) -> None:
        policy_path = self.root / "policy.json"
        result = write_pack_policy(PACK, policy_path, "model-user", "synthetic")
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
        policy = load_policy(policy_path)

        self.assertEqual("write_pack_policy", result["operation"])
        self.assertEqual([result["pack_id"]], raw["allowed_pack_ids"])
        self.assertEqual(["synthetic"], raw["allowed_content_classes"])
        self.assertEqual("model-user", policy.principal_id)

        service = StandardsForgeService(self.root / "memory.db", self.root / "objects")
        installed = service.install_pack(PACK, policy_path)
        resolved = service.resolve_document(
            "EXAMPLE-SPEC-100",
            "model-user",
            "example:spec-100:2025-a",
            "curated_records",
        )
        self.assertEqual(installed["package_digest"], resolved["package_digest"])

    def test_rejects_implicit_classification_and_existing_output(self) -> None:
        mismatch = self.root / "mismatch.json"
        with self.assertRaises(StandardsForgeError) as caught:
            write_pack_policy(PACK, mismatch, "model-user", "public_government_standard")
        self.assertEqual("policy_content_class_mismatch", caught.exception.code)
        self.assertFalse(mismatch.exists())

        policy_path = self.root / "policy.json"
        write_pack_policy(PACK, policy_path, "model-user", "synthetic")
        with self.assertRaises(StandardsForgeError) as caught:
            write_pack_policy(PACK, policy_path, "model-user", "synthetic")
        self.assertEqual("policy_output_exists", caught.exception.code)

    def test_copy_paste_cli_shape_writes_policy(self) -> None:
        policy_path = self.root / "cli-policy.json"
        args = cli_parser().parse_args(
            [
                "write-pack-policy",
                str(PACK),
                str(policy_path),
                "--principal",
                "model-user",
                "--content-class",
                "synthetic",
            ]
        )
        result = cli_run(args)
        self.assertEqual("write_pack_policy", result["operation"])
        self.assertTrue(policy_path.is_file())

    def test_cli_rejects_padded_principal_instead_of_stripping_it(self) -> None:
        for principal in (" model-user", "model-user ", "model-user\t"):
            with self.subTest(principal=principal):
                policy_path = self.root / "padded-policy.json"
                args = cli_parser().parse_args(
                    [
                        "write-pack-policy",
                        str(PACK),
                        str(policy_path),
                        "--principal",
                        principal,
                        "--content-class",
                        "synthetic",
                    ]
                )
                with self.assertRaises(StandardsForgeError) as caught:
                    cli_run(args)
                self.assertEqual("invalid_principal", caught.exception.code)
                self.assertFalse(policy_path.exists())


    def test_library_writer_and_loader_reject_padded_or_unencodable_principal(self) -> None:
        for principal in (" model-user", "model-user ", "model-user\n", "model\ud800user"):
            with self.subTest(principal=principal):
                policy_path = self.root / "library-policy.json"
                with self.assertRaises(StandardsForgeError) as caught:
                    write_pack_policy(PACK, policy_path, principal, "synthetic")
                self.assertEqual("invalid_principal", caught.exception.code)
                self.assertFalse(policy_path.exists())

        written = self.root / "written.json"
        write_pack_policy(PACK, written, "model-user", "synthetic")
        raw = json.loads(written.read_text(encoding="utf-8"))
        for principal in ("model-user ", " model-user"):
            with self.subTest(loaded=principal):
                padded = self.root / "padded-loaded.json"
                padded.write_text(json.dumps({**raw, "principal_id": principal}), encoding="utf-8")
                with self.assertRaises(StandardsForgeError) as caught:
                    load_policy(padded)
                self.assertEqual("invalid_policy", caught.exception.code)

if __name__ == "__main__":
    unittest.main()
