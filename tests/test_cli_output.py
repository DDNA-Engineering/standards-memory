from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.cli import _emit_json, _parser, _run  # noqa: E402


class _Cp1252Console:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


class CLIOutputTests(unittest.TestCase):
    def test_emits_utf8_even_when_text_console_cannot_encode_source_characters(self) -> None:
        stream = _Cp1252Console()
        _emit_json(stream, {"snippet": "exact ⟦source⟧ evidence"})
        decoded = stream.buffer.getvalue().decode("utf-8")
        self.assertEqual({"snippet": "exact ⟦source⟧ evidence"}, json.loads(decoded))

    def test_list_documents_forwards_prefix_pagination_and_bound_principal(self) -> None:
        args = _parser().parse_args(
            ["list-documents", "--identifier-prefix", "MIL-STD-810", "--limit", "25", "--cursor", "signed-cursor", "--principal", "local-user"]
        )
        with patch("standardsforge.cli.StandardsForgeService.list_documents", return_value={"operation": "list_documents"}) as list_documents:
            self.assertEqual({"operation": "list_documents"}, _run(args))
        list_documents.assert_called_once_with("local-user", "MIL-STD-810", 25, "signed-cursor")


if __name__ == "__main__":
    unittest.main()
