from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import standardsforge.pdf_isolation as isolation_module  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.pdf_isolation import isolated_pdf_pages  # noqa: E402
from standardsforge.pdf_protocol import (  # noqa: E402
    DEFAULT_LIMITS,
    build_request,
    canonical_json_bytes,
    sha256_bytes,
)


def _write_pdf(path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Isolated parser output.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as output:
        writer.write(output)


class PDFIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-pdf-isolation-")
        self.root = Path(self.temp.name)
        self.pdf = self.root / "fixture.pdf"
        _write_pdf(self.pdf)
        self.digest = hashlib.sha256(self.pdf.read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _extract(self, limits=DEFAULT_LIMITS) -> tuple[object, ...]:
        with isolated_pdf_pages(
            self.pdf,
            source_sha256=self.digest,
            source_bytes=self.pdf.stat().st_size,
            expected_pages=2,
            extraction_mode="layout_rotated_included",
            encryption_policy="reject",
            limits=limits,
        ) as parsed:
            return tuple(
                (
                    page.physical_page,
                    page.path.read_bytes(),
                    page.sha256,
                    page.content_stream_bytes,
                    page.text_layer_status,
                )
                for page in parsed.pages
            )

    def test_worker_replay_is_byte_identical_and_parent_accepts_closed_output(self) -> None:
        first = self._extract()
        second = self._extract()
        self.assertEqual(first, second)
        self.assertEqual(b"Isolated parser output.", first[0][1])
        self.assertEqual(b"", first[1][1])

    def test_source_change_and_output_limit_fail_with_typed_errors(self) -> None:
        with self.assertRaises(StandardsForgeError) as changed:
            with isolated_pdf_pages(
                self.pdf,
                source_sha256="0" * 64,
                source_bytes=self.pdf.stat().st_size,
                expected_pages=2,
                extraction_mode="layout_rotated_included",
                encryption_policy="reject",
            ):
                pass
        self.assertEqual("parser_source_changed", changed.exception.code)

        limits = replace(DEFAULT_LIMITS, page_text_bytes=8, aggregate_text_bytes=16)
        with self.assertRaises(StandardsForgeError) as oversized:
            self._extract(limits)
        self.assertEqual("parser_output_limit_exceeded", oversized.exception.code)
        self.assertEqual("page_text_bytes", oversized.exception.details["limit"])

    def test_wall_timeout_kills_worker_and_missing_result_is_not_success(self) -> None:
        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
        )
        limits = replace(DEFAULT_LIMITS, wall_seconds=1)
        with patch.object(isolation_module, "_start_worker", return_value=(sleeper, None)):
            with self.assertRaises(StandardsForgeError) as timed_out:
                self._extract(limits)
        self.assertEqual("parser_wall_time_exceeded", timed_out.exception.code)
        self.assertIsNotNone(sleeper.returncode)

        completed = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
        )
        with patch.object(isolation_module, "_start_worker", return_value=(completed, None)):
            with self.assertRaises(StandardsForgeError) as missing:
                self._extract()
        self.assertEqual("parser_protocol_error", missing.exception.code)

    def test_extra_file_and_changed_page_digest_are_protocol_failures(self) -> None:
        request = build_request(
            source_sha256=self.digest,
            source_bytes=self.pdf.stat().st_size,
            expected_pages=2,
            extraction_mode="layout_rotated_included",
            encryption_policy="reject",
        )
        request_bytes = canonical_json_bytes(request)
        request_path = self.root / "request.json"
        request_path.write_bytes(request_bytes)
        output = self.root / "worker-output"
        process, job = isolation_module._start_worker(request_path, self.pdf, output, DEFAULT_LIMITS)
        try:
            self.assertEqual(0, process.wait(timeout=10))
        finally:
            if job is not None:
                job.close()
        parsed = isolation_module._validate_output(
            output, request, sha256_bytes(request_bytes), DEFAULT_LIMITS
        )
        self.assertEqual(2, parsed.page_count)

        (output / "extra.txt").write_text("extra", encoding="utf-8")
        with self.assertRaises(StandardsForgeError) as extra:
            isolation_module._validate_output(
                output, request, sha256_bytes(request_bytes), DEFAULT_LIMITS
            )
        self.assertEqual("parser_protocol_error", extra.exception.code)
        (output / "extra.txt").unlink()

        first_page = output / "page-0001.txt"
        first_page.write_bytes(first_page.read_bytes() + b"tamper")
        with self.assertRaises(StandardsForgeError) as tampered:
            isolation_module._validate_output(
                output, request, sha256_bytes(request_bytes), DEFAULT_LIMITS
            )
        self.assertEqual("parser_protocol_error", tampered.exception.code)


if __name__ == "__main__":
    unittest.main()
