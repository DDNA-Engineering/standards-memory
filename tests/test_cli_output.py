from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.cli import _emit_json  # noqa: E402


class _Cp1252Console:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


class CLIOutputTests(unittest.TestCase):
    def test_emits_utf8_even_when_text_console_cannot_encode_source_characters(self) -> None:
        stream = _Cp1252Console()
        _emit_json(stream, {"snippet": "exact ⟦source⟧ evidence"})
        decoded = stream.buffer.getvalue().decode("utf-8")
        self.assertEqual({"snippet": "exact ⟦source⟧ evidence"}, json.loads(decoded))


if __name__ == "__main__":
    unittest.main()
