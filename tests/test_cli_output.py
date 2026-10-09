from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.cli import _emit_json, _parser, _run  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402


PACK = ROOT / "examples" / "packs" / "fictional-adapter-v1"


class _Cp1252Console:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


class CLIOutputTests(unittest.TestCase):
    def test_emits_utf8_even_when_text_console_cannot_encode_source_characters(self) -> None:
        stream = _Cp1252Console()
        _emit_json(stream, {"snippet": "exact ⟦source⟧ evidence"})
        decoded = stream.buffer.getvalue().decode("utf-8")
        self.assertEqual({"snippet": "exact ⟦source⟧ evidence"}, json.loads(decoded))

    def test_search_query_mode_defaults_and_forwards_explicit_choice(self) -> None:
        parser = _parser()
        for extra, expected in (
            ([], "all_terms"),
            (["--query-mode", "any_terms"], "any_terms"),
            (["--query-mode", "natural_language"], "natural_language"),
        ):
            with self.subTest(query_mode=expected):
                args = parser.parse_args(
                    ["search", "axial ingress", "--principal", "local-user", *extra]
                )
                with patch("standardsforge.cli.StandardsForgeService.open_read_only") as open_store:
                    search = open_store.return_value.search
                    search.return_value = {"operation": "search"}
                    self.assertEqual({"operation": "search"}, _run(args))
                    open_store.assert_called_once_with(Path(args.db), Path(args.store))
                search.assert_called_once_with(
                    "axial ingress",
                    "local-user",
                    20,
                    package_digest=None,
                    scope_prefix=None,
                    query_mode=expected,
                )

    def test_list_documents_forwards_prefix_pagination_and_bound_principal(self) -> None:
        args = _parser().parse_args(
            [
                "list-documents",
                "--identifier-prefix",
                "MIL-STD-810",
                "--limit",
                "25",
                "--cursor",
                "signed-cursor",
                "--principal",
                "local-user",
            ]
        )
        with patch("standardsforge.cli.StandardsForgeService.open_read_only") as open_store:
            list_documents = open_store.return_value.list_documents
            list_documents.return_value = {"operation": "list_documents"}
            self.assertEqual({"operation": "list_documents"}, _run(args))
            open_store.assert_called_once_with(Path(args.db), Path(args.store))
        list_documents.assert_called_once_with(
            "local-user", "MIL-STD-810", 25, "signed-cursor"
        )

    def test_verify_pack_validates_without_opening_or_creating_a_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standardsforge-verify-pack-") as temporary:
            base = Path(temporary)
            db = base / "absent-state" / "memory.db"
            store = base / "absent-objects"
            args = _parser().parse_args(
                ["--db", str(db), "--store", str(store), "verify-pack", str(PACK)]
            )
            with patch.object(StandardsForgeService, "__init__", side_effect=AssertionError("store constructed")), \
                    patch.object(StandardsForgeService, "open_read_only", side_effect=AssertionError("store opened")):
                result = _run(args)
            self.assertEqual([], sorted(path.name for path in base.iterdir()))

            reference = StandardsForgeService(base / "reference.db", base / "reference-objects")
            self.assertEqual(reference.verify_pack(PACK), result)
            self.assertTrue(result["valid"])
            self.assertEqual("none", result["authorization_effect"])

            invalid = _parser().parse_args(
                ["--db", str(db), "--store", str(store), "verify-pack", str(base / "missing-pack")]
            )
            with self.assertRaises(StandardsForgeError):
                _run(invalid)
            self.assertFalse(db.parent.exists())
            self.assertFalse(store.exists())

    def test_padded_principal_is_rejected_before_any_store_is_opened(self) -> None:
        for principal in (" local-user", "local-user ", "local-user\n", "\tlocal-user", "  ", "local\ud800user"):
            with self.subTest(principal=principal):
                args = _parser().parse_args(
                    ["search", "axial ingress", "--principal", principal]
                )
                with patch("standardsforge.cli.StandardsForgeService") as service_class:
                    with self.assertRaises(StandardsForgeError) as caught:
                        _run(args)
                self.assertEqual("invalid_principal", caught.exception.code)
                service_class.open_read_only.assert_not_called()
                service_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
