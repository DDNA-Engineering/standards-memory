from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import standardsforge.pdf_isolation as isolation_module  # noqa: E402
import standardsforge.pdf_worker as worker_module  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.pdf_isolation import isolated_pdf_pages  # noqa: E402
from standardsforge.pdf_protocol import (  # noqa: E402
    DEFAULT_LIMITS,
    build_request,
    canonical_json_bytes,
    sha256_bytes,
)


def _write_pdf(path: Path, text: bytes = b"Isolated parser output.") -> None:
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
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (" + text + b") Tj ET")
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

        limits = replace(DEFAULT_LIMITS, page_text_bytes=8, aggregate_text_bytes=16, result_bytes=8)
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



def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
    except OSError:
        return True
    return fields[0] != "Z"


# A stand-in for a compromised worker leader: it forks a descendant that
# outlives the leader and tampers with the parser output, then the leader
# exits successfully.
_FORKING_LEADER = r"""
import os, sys, time
pid_file, target = sys.argv[1], sys.argv[2]
child = os.fork()
if child == 0:
    with open(pid_file + ".partial", "w") as handle:
        handle.write(str(os.getpid()))
    os.replace(pid_file + ".partial", pid_file)
    time.sleep(0.5)
    with open(target, "ab") as handle:
        handle.write(b" tampered by a surviving descendant")
    time.sleep(30)
    os._exit(0)
deadline = time.monotonic() + 10
while not os.path.exists(pid_file) and time.monotonic() < deadline:
    time.sleep(0.01)
os._exit(0)
"""


class PDFIsolationHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-pdf-hardening-")
        self.root = Path(self.temp.name)
        self.pdf = self.root / "fixture.pdf"
        _write_pdf(self.pdf)
        self.digest = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.survivors: list[int] = []

    def tearDown(self) -> None:
        for pid in self.survivors:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        self.temp.cleanup()

    def _request(self, encryption_policy: str = "reject") -> tuple[dict[str, object], str]:
        request = build_request(
            source_sha256=self.digest,
            source_bytes=self.pdf.stat().st_size,
            expected_pages=2,
            extraction_mode="layout_rotated_included",
            encryption_policy=encryption_policy,
        )
        return request, sha256_bytes(canonical_json_bytes(request))

    def _real_output(self, output: Path, encryption_policy: str = "reject") -> tuple[dict[str, object], str]:
        request, digest = self._request(encryption_policy)
        request_path = output.parent / f"{output.name}-request.json"
        request_path.write_bytes(canonical_json_bytes(request))
        process, job = isolation_module._start_worker(request_path, self.pdf, output, DEFAULT_LIMITS)
        try:
            self.assertEqual(0, process.wait(timeout=60))
        finally:
            isolation_module._kill_process(process, job)
            if job is not None:
                job.close()
        return request, digest

    def _rewrite_result(self, output: Path, **changes: object) -> None:
        result_path = output / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result.update(changes)
        result_path.write_bytes(canonical_json_bytes(result))

    @unittest.skipIf(os.name == "nt" or not hasattr(os, "fork"), "POSIX process-group behaviour")
    def test_surviving_descendant_is_killed_before_output_is_validated(self) -> None:
        pid_file = self.root / "descendant.pid"
        real_start = isolation_module._start_worker

        def forking_start(request_path, source_path, output, limits):
            process, job = real_start(request_path, source_path, output, limits)
            self.assertEqual(0, process.wait(timeout=60))
            leader = subprocess.Popen(
                [sys.executable, "-I", "-c", _FORKING_LEADER, str(pid_file), str(output / "page-0001.txt")],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return leader, job

        with patch.object(isolation_module, "_start_worker", side_effect=forking_start):
            with isolated_pdf_pages(
                self.pdf,
                source_sha256=self.digest,
                source_bytes=self.pdf.stat().st_size,
                expected_pages=2,
                extraction_mode="layout_rotated_included",
                encryption_policy="reject",
            ) as parsed:
                descendant = int(pid_file.read_text(encoding="ascii"))
                self.survivors.append(descendant)
                # Outlast the descendant's tamper delay while the output is live.
                time.sleep(1.0)
                self.assertFalse(_process_alive(descendant))
                first = parsed.pages[0]
                self.assertEqual(b"Isolated parser output.", first.data)
                self.assertEqual(first.sha256, sha256_bytes(first.data))
                self.assertEqual(first.data, first.path.read_bytes())
        self.assertFalse(_process_alive(descendant))

    @unittest.skipIf(os.name == "nt" or not hasattr(os, "fork"), "POSIX process-group behaviour")
    def test_descendant_of_failed_worker_does_not_survive(self) -> None:
        pid_file = self.root / "descendant.pid"

        failing = _FORKING_LEADER.rstrip().rsplit("os._exit(0)", 1)
        leader_script = "os._exit(4)".join(failing) + "\n"

        def start(request_path, source_path, output, limits):
            return (
                subprocess.Popen(
                    [sys.executable, "-I", "-c", leader_script, str(pid_file), str(self.root / "ignored.txt")],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                ),
                None,
            )

        with patch.object(isolation_module, "_start_worker", side_effect=start):
            with self.assertRaises(StandardsForgeError) as failed:
                with isolated_pdf_pages(
                    self.pdf,
                    source_sha256=self.digest,
                    source_bytes=self.pdf.stat().st_size,
                    expected_pages=2,
                    extraction_mode="layout_rotated_included",
                    encryption_policy="reject",
                ):
                    pass
        self.assertEqual("parser_worker_terminated", failed.exception.code)
        descendant = int(pid_file.read_text(encoding="ascii"))
        self.survivors.append(descendant)
        deadline = time.monotonic() + 5
        while _process_alive(descendant) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(_process_alive(descendant))

    def test_windows_job_assignment_failure_kills_blocked_worker_promptly(self) -> None:
        started: list[subprocess.Popen[bytes]] = []
        real_popen = subprocess.Popen

        def popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            process._handle = 0  # the Windows handle attribute read by job.assign
            started.append(process)
            return process

        class FailingJob:
            instances: list["FailingJob"] = []

            def __init__(self, memory_bytes: int, cpu_seconds: int) -> None:
                self.terminated = False
                self.closed = False
                FailingJob.instances.append(self)

            def assign(self, process_handle: int) -> None:
                raise OSError(5, "AssignProcessToJobObject failed")

            def terminate(self) -> None:
                # An unassigned job holds no processes: terminating it is a no-op.
                self.terminated = True

            def close(self) -> None:
                self.closed = True

        fake_module = type(sys)("standardsforge._windows_job")
        fake_module.WindowsJob = FailingJob
        request_path = self.root / "request.json"
        request_path.write_bytes(canonical_json_bytes(self._request()[0]))
        safety = threading.Timer(30, lambda: [process.kill() for process in started])
        safety.start()
        try:
            with (
                patch.object(isolation_module, "_IS_WINDOWS", True),
                patch.dict(sys.modules, {"standardsforge._windows_job": fake_module}),
                patch.object(isolation_module.subprocess, "Popen", side_effect=popen),
            ):
                begun = time.monotonic()
                with self.assertRaises(StandardsForgeError) as failed:
                    isolation_module._start_worker(request_path, self.pdf, self.root / "output", DEFAULT_LIMITS)
                elapsed = time.monotonic() - begun
        finally:
            safety.cancel()
        self.assertEqual("parser_limits_unavailable", failed.exception.code)
        self.assertLess(elapsed, 15)
        self.assertEqual(1, len(started))
        self.assertIsNotNone(started[0].poll())
        self.assertTrue(started[0].stdin.closed)
        self.assertTrue(FailingJob.instances[0].closed)
        self.assertFalse((self.root / "output").exists())

    def test_oversized_page_file_is_rejected_before_it_is_read(self) -> None:
        output = self.root / "output"
        request, digest = self._real_output(output)
        limits = replace(DEFAULT_LIMITS, page_text_bytes=64)
        page = output / "page-0001.txt"
        with page.open("ab") as handle:
            handle.truncate(10 * 1024 * 1024)
        reads: list[tuple[Path, int]] = []
        real_read = isolation_module._read_bounded

        def tracking_read(path: Path, limit: int) -> bytes | None:
            reads.append((Path(path), limit))
            return real_read(path, limit)

        with (
            patch.object(isolation_module, "_read_bounded", side_effect=tracking_read),
            patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded read")),
        ):
            with self.assertRaises(StandardsForgeError) as oversized:
                isolation_module._validate_output(output, request, digest, limits)
        self.assertEqual("parser_protocol_error", oversized.exception.code)
        self.assertNotIn(page, [path for path, _ in reads])

    def test_aggregate_limit_is_enforced_before_reading_the_page(self) -> None:
        output = self.root / "output"
        request, digest = self._real_output(output)
        first_size = (output / "page-0001.txt").stat().st_size
        self.assertGreater(first_size, 0)
        limits = replace(DEFAULT_LIMITS, aggregate_text_bytes=first_size - 1)
        reads: list[Path] = []
        real_read = isolation_module._read_bounded

        def tracking_read(path: Path, limit: int) -> bytes | None:
            reads.append(Path(path))
            return real_read(path, limit)

        with patch.object(isolation_module, "_read_bounded", side_effect=tracking_read):
            with self.assertRaises(StandardsForgeError) as aggregate:
                isolation_module._validate_output(output, request, digest, limits)
        self.assertEqual("parser_output_limit_exceeded", aggregate.exception.code)
        self.assertNotIn(output / "page-0001.txt", reads)

    def test_bounded_read_rejects_oversized_and_symlinked_files(self) -> None:
        output = self.root / "output"
        request, digest = self._real_output(output)
        page = output / "page-0001.txt"
        self.assertIsNone(isolation_module._read_bounded(page, page.stat().st_size - 1))
        self.assertEqual(page.read_bytes(), isolation_module._read_bounded(page, page.stat().st_size))
        if hasattr(os, "symlink"):
            link = self.root / "link.txt"
            try:
                os.symlink(page, link)
            except OSError:
                return
            self.assertIsNone(isolation_module._read_bounded(link, 1024))

    def test_encryption_status_must_be_allowed_by_the_request_policy(self) -> None:
        output = self.root / "output"
        request, digest = self._real_output(output)
        self.assertEqual("not_encrypted", isolation_module._validate_output(output, request, digest, DEFAULT_LIMITS).encryption_status)
        for status in ("empty_password_decrypted_for_extraction", "decrypted_with_guess", "", None, 1):
            self._rewrite_result(output, encryption_status=status)
            with self.assertRaises(StandardsForgeError, msg=repr(status)) as rejected:
                isolation_module._validate_output(output, request, digest, DEFAULT_LIMITS)
            self.assertEqual("parser_protocol_error", rejected.exception.code)

        permissive_output = self.root / "permissive"
        permissive, permissive_digest = self._real_output(permissive_output, "empty_password_only")
        self._rewrite_result(permissive_output, encryption_status="empty_password_decrypted_for_extraction")
        parsed = isolation_module._validate_output(permissive_output, permissive, permissive_digest, DEFAULT_LIMITS)
        self.assertEqual("empty_password_decrypted_for_extraction", parsed.encryption_status)
        self._rewrite_result(permissive_output, encryption_status="owner_password_decrypted")
        with self.assertRaises(StandardsForgeError) as unknown:
            isolation_module._validate_output(permissive_output, permissive, permissive_digest, DEFAULT_LIMITS)
        self.assertEqual("parser_protocol_error", unknown.exception.code)

    def test_dependency_roots_include_platlib_in_order_without_duplicates(self) -> None:
        purelib = self.root / "purelib"
        platlib = self.root / "platlib"
        purelib.mkdir()
        platlib.mkdir()
        with patch.object(isolation_module.sysconfig, "get_paths", return_value={"purelib": str(purelib), "platlib": str(platlib)}):
            self.assertEqual([str(purelib.resolve()), str(platlib.resolve())], isolation_module._dependency_roots())
        with patch.object(isolation_module.sysconfig, "get_paths", return_value={"purelib": str(purelib), "platlib": str(purelib)}):
            self.assertEqual([str(purelib.resolve())], isolation_module._dependency_roots())

    def test_worker_finds_dependencies_installed_only_in_platlib(self) -> None:
        import pypdf

        installed = str(Path(pypdf.__file__).resolve().parents[1])
        empty_purelib = self.root / "empty-purelib"
        empty_purelib.mkdir()
        paths = {"purelib": str(empty_purelib), "platlib": installed}
        with patch.object(isolation_module.sysconfig, "get_paths", return_value=paths):
            with isolated_pdf_pages(
                self.pdf,
                source_sha256=self.digest,
                source_bytes=self.pdf.stat().st_size,
                expected_pages=2,
                extraction_mode="layout_rotated_included",
                encryption_policy="reject",
            ) as parsed:
                self.assertEqual(b"Isolated parser output.", parsed.pages[0].data)


class PDFWorkerSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-pdf-worker-")
        self.root = Path(self.temp.name)
        self.source = self.root / "source.pdf"
        self.substitute = self.root / "substitute.pdf"
        _write_pdf(self.source, b"Verified original text")
        _write_pdf(self.substitute, b"Substituted after hash")
        self.assertEqual(self.source.stat().st_size, self.substitute.stat().st_size)
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        request = build_request(
            source_sha256=self.digest,
            source_bytes=self.source.stat().st_size,
            expected_pages=2,
            extraction_mode="simple",
            encryption_policy="reject",
        )
        self.request_path = self.root / "request.json"
        self.request_path.write_bytes(canonical_json_bytes(request))
        self.output = self.root / "output"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_parser_consumes_the_verified_bytes_not_a_swapped_file(self) -> None:
        import pypdf

        real_reader = pypdf.PdfReader

        def racing_reader(stream, *args, **kwargs):
            # A concurrent writer replaces the source after it was verified.
            shutil.copyfile(self.substitute, self.source)
            return real_reader(stream, *args, **kwargs)

        with (
            patch.object(worker_module, "_apply_posix_limits", lambda limits: None),
            patch.object(pypdf, "PdfReader", side_effect=racing_reader),
        ):
            worker_module._extract(self.request_path, self.source, self.output)
        self.assertNotEqual(self.digest, hashlib.sha256(self.source.read_bytes()).hexdigest())
        result = json.loads((self.output / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(self.digest, result["source_sha256"])
        self.assertEqual(b"Verified original text", (self.output / "page-0001.txt").read_bytes())

    def test_source_with_wrong_digest_or_symlink_is_rejected(self) -> None:
        shutil.copyfile(self.substitute, self.source)
        with patch.object(worker_module, "_apply_posix_limits", lambda limits: None):
            with self.assertRaises(worker_module.WorkerFailure) as changed:
                worker_module._extract(self.request_path, self.source, self.output)
        self.assertEqual("parser_source_changed", changed.exception.code)
        if hasattr(os, "symlink"):
            link = self.root / "link.pdf"
            try:
                os.symlink(self.substitute, link)
            except OSError:
                return
            with patch.object(worker_module, "_apply_posix_limits", lambda limits: None):
                with self.assertRaises(worker_module.WorkerFailure) as linked:
                    worker_module._extract(self.request_path, link, self.output)
            self.assertEqual("parser_source_changed", linked.exception.code)

    def test_memory_error_while_opening_or_counting_is_a_memory_limit(self) -> None:
        import pypdf

        with (
            patch.object(worker_module, "_apply_posix_limits", lambda limits: None),
            patch.object(pypdf, "PdfReader", side_effect=MemoryError),
        ):
            with self.assertRaises(worker_module.WorkerFailure) as opening:
                worker_module._extract(self.request_path, self.source, self.output)
        self.assertEqual(("parser_memory_limit_exceeded", "reader"), (opening.exception.code, opening.exception.stage))

        class ExhaustedReader:
            is_encrypted = False

            def __init__(self, *args, **kwargs) -> None:
                pass

            @property
            def pages(self):
                raise MemoryError

        with (
            patch.object(worker_module, "_apply_posix_limits", lambda limits: None),
            patch.object(pypdf, "PdfReader", ExhaustedReader),
        ):
            with self.assertRaises(worker_module.WorkerFailure) as counting:
                worker_module._extract(self.request_path, self.source, self.output)
        self.assertEqual(("parser_memory_limit_exceeded", "metadata"), (counting.exception.code, counting.exception.stage))

        with (
            patch.object(worker_module, "_apply_posix_limits", lambda limits: None),
            patch.object(pypdf, "PdfReader", side_effect=ValueError("broken xref")),
        ):
            with self.assertRaises(worker_module.WorkerFailure) as invalid:
                worker_module._extract(self.request_path, self.source, self.output)
        self.assertEqual("invalid_pdf", invalid.exception.code)


if __name__ == "__main__":
    unittest.main()
