from __future__ import annotations

import hashlib
import json
import shutil
import socket
import struct
import sys
import tempfile
import tracemalloc
import unittest
import zipfile
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import standardsforge.acquisition as acquisition  # noqa: E402
from standardsforge.bundle import build_bundle, verify_bundle  # noqa: E402
from standardsforge.errors import StandardsForgeError  # noqa: E402
from standardsforge.pack import (  # noqa: E402
    _safe_relative_path,
    _validate_semantic_record,
    iter_zip_member,
    open_validated_pack,
    validate_pack_directory,
    write_pack_archive,
)

EXAMPLE_PACKS = [ROOT / "examples" / "packs" / f"fictional-adapter-v{i}" for i in (1, 2)]
# Expanding a member fully would allocate at least this much; bounded reads stay far below it.
BOMB_BYTES = 64 * 1024 * 1024
PEAK_LIMIT = 16 * 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rewrite_zip(path: Path, members: list[tuple[str, bytes | None, int]], *, declared: dict[str, int] | None = None,
                 bombs: dict[str, int] | None = None) -> None:
    """Write members in order; bombs append zero bytes; declared patches the recorded uncompressed size."""

    with zipfile.ZipFile(path, "w") as archive:
        for name, data, method in members:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = method
            with archive.open(info, "w", force_zip64=False) as writer:
                writer.write(data or b"")
                for _ in range((bombs or {}).get(name, 0) // (1 << 20)):
                    writer.write(b"\0" * (1 << 20))
    if declared:
        _patch_declared_sizes(path, declared)


def _patch_declared_sizes(path: Path, declared: dict[str, int]) -> None:
    data = bytearray(path.read_bytes())
    position = data.find(b"PK\x01\x02")
    while position != -1:
        name_length, extra_length, comment_length = struct.unpack_from("<HHH", data, position + 28)
        name = bytes(data[position + 46:position + 46 + name_length]).decode("utf-8")
        if name in declared:
            struct.pack_into("<I", data, position + 24, declared[name])
            local = struct.unpack_from("<I", data, position + 42)[0]
            struct.pack_into("<I", data, local + 22, declared[name])
        position = data.find(b"PK\x01\x02", position + 46 + name_length + extra_length + comment_length)
    path.write_bytes(bytes(data))


class _Bounded:
    """Measure peak traced allocation while a call runs."""

    def __enter__(self) -> "_Bounded":
        tracemalloc.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()


class ArchiveHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-hardening-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_bundle_manifest_lzma_bomb_stops_at_declared_size(self) -> None:
        bomb = self.root / "bomb.zip"
        _rewrite_zip(bomb, [("bundle.json", b"", zipfile.ZIP_LZMA)], declared={"bundle.json": 100}, bombs={"bundle.json": BOMB_BYTES})
        with _Bounded() as bounded, self.assertRaises(StandardsForgeError) as caught:
            verify_bundle(bomb)
        self.assertEqual("bundle_limit_exceeded", caught.exception.code)
        self.assertLess(bounded.peak, PEAK_LIMIT)

    def test_bundle_blob_bombs_stop_at_declared_size(self) -> None:
        bundle = self.root / "bundle.zip"
        report = build_bundle(EXAMPLE_PACKS, bundle)
        self.assertGreater(report["compression_methods"]["lzma"] + report["compression_methods"]["deflate"], 0)
        with zipfile.ZipFile(bundle) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        blob = next(name for name in sorted(entries) if name.startswith("blobs/"))
        for method in (zipfile.ZIP_LZMA, zipfile.ZIP_DEFLATED):
            with self.subTest(method=method):
                target = self.root / f"blob-bomb-{method}.zip"
                members = [(name, data, method if name == blob else zipfile.ZIP_DEFLATED) for name, data in entries.items()]
                _rewrite_zip(target, members, declared={blob: len(entries[blob])}, bombs={blob: BOMB_BYTES})
                with _Bounded() as bounded, self.assertRaises(StandardsForgeError) as caught:
                    verify_bundle(target)
                self.assertEqual("bundle_limit_exceeded", caught.exception.code)
                self.assertLess(bounded.peak, PEAK_LIMIT)

    def test_bundle_rejects_short_member_and_crc_mismatch(self) -> None:
        short = self.root / "short.zip"
        _rewrite_zip(short, [("bundle.json", b"{}", zipfile.ZIP_DEFLATED)], declared={"bundle.json": 1024})
        with self.assertRaises(StandardsForgeError) as caught:
            verify_bundle(short)
        self.assertEqual("invalid_bundle", caught.exception.code)
        crc = self.root / "crc.zip"
        with zipfile.ZipFile(crc, "w") as archive:
            archive.writestr("bundle.json", b'{"a":1}')
        data = bytearray(crc.read_bytes())
        position = data.find(b'{"a":1}')
        data[position + 5] = ord("2")
        crc.write_bytes(bytes(data))
        with self.assertRaises(StandardsForgeError) as caught:
            verify_bundle(crc)
        self.assertEqual("invalid_bundle", caught.exception.code)

    def test_bundle_lzma_roundtrip_still_verifies(self) -> None:
        bundle = self.root / "bundle.zip"
        build_bundle(EXAMPLE_PACKS, bundle)
        with zipfile.ZipFile(bundle) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        rewritten = self.root / "all-lzma.zip"
        _rewrite_zip(rewritten, [(name, data, zipfile.ZIP_LZMA) for name, data in entries.items()])
        self.assertEqual(2, verify_bundle(rewritten)["packages"])

    def test_bundle_materializes_normalized_member_paths(self) -> None:
        bundle = self.root / "bundle.zip"
        build_bundle(EXAMPLE_PACKS, bundle)
        with zipfile.ZipFile(bundle) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(entries["bundle.json"])
        file_entry = next(item for item in manifest["packs"][0]["files"] if "/" in item["path"])
        file_entry["path"] = file_entry["path"].replace("/", "\\")
        entries["bundle.json"] = json.dumps(manifest).encode()
        backslashed = self.root / "backslashed.zip"
        _rewrite_zip(backslashed, [(name, data, zipfile.ZIP_DEFLATED) for name, data in entries.items()])
        self.assertEqual(2, verify_bundle(backslashed)["packages"])
        for unsafe in ("D:/evil.txt", "//server/share/x.txt", "a.txt:stream", "sources/CON.txt"):
            with self.subTest(path=unsafe):
                file_entry["path"] = unsafe
                entries["bundle.json"] = json.dumps(manifest).encode()
                target = self.root / "unsafe.zip"
                target.unlink(missing_ok=True)
                _rewrite_zip(target, [(name, data, zipfile.ZIP_DEFLATED) for name, data in entries.items()])
                with self.assertRaises(StandardsForgeError) as caught:
                    verify_bundle(target)
                self.assertEqual("invalid_pack_path", caught.exception.code)

    def test_pack_archive_rejects_lzma_bombs_and_bounds_deflate(self) -> None:
        for method, code in ((zipfile.ZIP_LZMA, "invalid_pack_archive"), (zipfile.ZIP_DEFLATED, "pack_limit_exceeded")):
            with self.subTest(method=method):
                bomb = self.root / f"pack-bomb-{method}.zip"
                _rewrite_zip(bomb, [("sources/x.txt", b"", method)], declared={"sources/x.txt": 100}, bombs={"sources/x.txt": BOMB_BYTES})
                with _Bounded() as bounded, self.assertRaises(StandardsForgeError) as caught:
                    with open_validated_pack(bomb):
                        pass
                self.assertEqual(code, caught.exception.code)
                self.assertLess(bounded.peak, PEAK_LIMIT)

    def test_pack_archive_unsupported_members_raise_typed_errors(self) -> None:
        for label, offset, value in (("encrypted", 8, 1), ("unknown-compression", 10, 99), ("bzip2", 10, zipfile.ZIP_BZIP2)):
            with self.subTest(label=label):
                path = self.root / f"{label}.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("manifest.json", "{}")
                data = bytearray(path.read_bytes())
                central = data.rfind(b"PK\x01\x02")
                struct.pack_into("<H", data, central + offset, value)
                local = data.find(b"PK\x03\x04")
                struct.pack_into("<H", data, local + offset - 2, value)
                path.write_bytes(bytes(data))
                with self.assertRaises(StandardsForgeError) as caught:
                    with open_validated_pack(path):
                        pass
                self.assertEqual("invalid_pack_archive", caught.exception.code)

    def test_highly_compressible_members_roundtrip(self) -> None:
        # Valid repetitive text compresses beyond 1000:1; bounded reads must still accept it.
        source = self.root / "compressible-pack"
        shutil.copytree(EXAMPLE_PACKS[0], source)
        filler = b" " * (3 * 1024 * 1024)
        (source / "sources" / "filler.txt").write_bytes(filler)
        inventory = json.loads((source / "inventory.json").read_text(encoding="utf-8"))
        inventory["files"].append({"path": "sources/filler.txt", "bytes": len(filler), "sha256": _sha256(filler)})
        inventory["files"].sort(key=lambda item: item["path"])
        (source / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
        archive = self.root / "compressible.zip"
        result = write_pack_archive(source, archive)
        with open_validated_pack(archive) as pack:
            self.assertEqual(result["package_digest"], pack.package_digest)
        bundle = self.root / "compressible-bundle.zip"
        build_bundle([source], bundle)
        self.assertEqual(1, verify_bundle(bundle)["packages"])

    def test_empty_member_with_zero_length_deflate_stream_reads_empty(self) -> None:
        path = self.root / "empty.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("empty.txt", b"")
        data = bytearray(path.read_bytes())
        local = data.find(b"PK\x03\x04")
        central = data.rfind(b"PK\x01\x02")
        struct.pack_into("<H", data, local + 8, zipfile.ZIP_DEFLATED)
        struct.pack_into("<H", data, central + 10, zipfile.ZIP_DEFLATED)
        path.write_bytes(bytes(data))
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("empty.txt")
            self.assertEqual((0, 0), (info.compress_size, info.file_size))
            chunks = list(
                iter_zip_member(
                    archive, info, limit=10, methods={zipfile.ZIP_DEFLATED},
                    limit_code="pack_limit_exceeded", invalid_code="invalid_pack_archive",
                )
            )
        self.assertEqual(b"", b"".join(chunks))

    def test_pack_archive_roundtrip_unchanged(self) -> None:
        archive = self.root / "pack.zip"
        result = write_pack_archive(EXAMPLE_PACKS[0], archive)
        with open_validated_pack(archive) as pack:
            self.assertEqual(result["package_digest"], pack.package_digest)


class PathHardeningTests(unittest.TestCase):
    def test_rejects_windows_drive_unc_stream_and_device_names(self) -> None:
        for value in (
            "D:/evil.txt", "C:evil.txt", "//server/share/x.txt", "\\\\server\\share\\x.txt", "a.txt:stream",
            "sources/a.pdf:Zone.Identifier", "CON.txt", "sources/nul.json", "com1.txt", "LPT9.md", "aux.tar.json",
            "CONIN$.txt", "sources./a.txt", "sources /a.txt", "a.txt.", "a.txt ", "a//b.txt", "./a.txt",
            "a\x00.txt", "../a.txt", "/abs.txt",
            "sources/a?.txt", "a*b.txt", "a<b>.txt", "a|b.txt", 'a"b.txt',
        ):
            with self.subTest(path=value), self.assertRaises(StandardsForgeError) as caught:
                _safe_relative_path(value)
            self.assertEqual("invalid_pack_path", caught.exception.code)

    def test_accepts_ordinary_names(self) -> None:
        for value in ("sources/a.pdf", "sources\\a.extracted.txt", "CONFIG.txt", "console.md", "com10.txt", "a.b.json"):
            with self.subTest(path=value):
                self.assertEqual(value.replace("\\", "/"), _safe_relative_path(value).as_posix())

    def test_zip_member_with_drive_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "drive.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("C:evil.txt", "x")
            with self.assertRaises(StandardsForgeError) as caught:
                with open_validated_pack(path):
                    pass
            self.assertEqual("invalid_pack_path", caught.exception.code)


class StructuralEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-span-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "pack"

    def _write_pack(self, *, mutate=None, derivation: bool = True, semantics: dict | None = None) -> Path:
        root = self.root
        shutil.rmtree(root, ignore_errors=True)
        (root / "sources").mkdir(parents=True)
        pdf = b"%PDF-1.4 fake\n"
        (root / "sources/a.pdf").write_bytes(pdf)
        page = "The supplier shall pay all fees.\n".encode()
        (root / "sources/a.extracted.txt").write_bytes(page)
        manifest = {
            "schema_version": "0.1.0", "pack_id": "p", "document_family_id": "f", "edition_id": "e",
            "publisher": "P", "identifier": "DOC-1", "title": "T", "revision": "A", "publication_date": "2020-01-01",
            "category": "c", "representation": "reviewed_structure", "inventory_path": "inventory.json",
            "rights_path": "rights.json", "records_path": "records.json",
            "coverage": {key: "x" for key in ("corpus_scope", "edition_composition", "parsed_source_coverage",
                                              "dependency_closure", "enumeration_traversal", "output_budget_coverage")},
        }
        rights = {"rights_schema_version": "0.1.0", "content_class": "c", "redistribution": "r", "processing": [],
                  "model_use": "m", "statement": "The supplier shall pay all fees."}
        rights_bytes = json.dumps(rights).encode()
        (root / "manifest.json").write_text(json.dumps(manifest))
        (root / "rights.json").write_bytes(rights_bytes)
        quote = b"The supplier shall pay all fees."
        span = {"path": "sources/a.pdf", "sha256": _sha256(pdf), "text_path": "sources/a.extracted.txt",
                "text_sha256": _sha256(page), "physical_page": 1, "start_byte": 0, "end_byte": len(quote),
                "quote_sha256": _sha256(quote)}
        record = {
            "record_id": "r1", "edition_id": "e", "kind": "clause", "clause_reference": "1", "heading": "h",
            "text": quote.decode(),
            "source": {"path": "sources/a.pdf", "sha256": _sha256(pdf), "text_path": "sources/a.extracted.txt",
                       "text_sha256": _sha256(page), "page": 1, "locator": "p1", "quote_sha256": _sha256(quote)},
            "derivation": {"statement_role": "obligation", "method": "m", "review_status": "x"},
            "dependencies": [],
            "structure": {
                "logical_id": "L1", "content_sha256": _sha256(quote), "parent_logical_id": None, "ordinal": 1,
                "source_spans": [span],
                "relationships": [{
                    "relationship": "references", "target_status": "unresolved", "target_logical_id": None,
                    "target_locator": "Other document", "candidate_logical_ids": [], "required": False,
                    "method": "m", "review_status": "x", "evidence_spans": [dict(span)],
                }],
            },
        }
        if not derivation:
            del record["derivation"]
        if semantics is not None:
            record["structure"]["semantics"] = semantics
        if mutate is not None:
            mutate(record, rights_bytes)
        (root / "records.json").write_text(json.dumps({"schema_version": "0.1.0", "records": [record]}))
        files = [{"path": path, "sha256": _sha256((root / path).read_bytes()), "bytes": (root / path).stat().st_size}
                 for path in ("manifest.json", "rights.json", "records.json", "sources/a.pdf", "sources/a.extracted.txt")]
        (root / "inventory.json").write_text(json.dumps({"schema_version": "0.1.0", "algorithm": "sha256", "files": files}))
        return root

    def test_baseline_pack_is_valid(self) -> None:
        self.assertEqual(1, len(validate_pack_directory(self._write_pack()).records))

    def test_span_text_cannot_come_from_a_non_source_file(self) -> None:
        def from_rights(span: dict, rights_bytes: bytes) -> None:
            start = rights_bytes.index(b"The supplier shall pay all fees.")
            span.update(text_path="rights.json", text_sha256=_sha256(rights_bytes), start_byte=start,
                        end_byte=start + len(b"The supplier shall pay all fees."))

        def structural(record: dict, rights_bytes: bytes) -> None:
            from_rights(record["structure"]["source_spans"][0], rights_bytes)

        def relationship_text(record: dict, rights_bytes: bytes) -> None:
            from_rights(record["structure"]["relationships"][0]["evidence_spans"][0], rights_bytes)

        def relationship_path(record: dict, rights_bytes: bytes) -> None:
            span = record["structure"]["relationships"][0]["evidence_spans"][0]
            span.update(path="rights.json", sha256=_sha256(rights_bytes))

        def relationship_pdf_as_text(record: dict, rights_bytes: bytes) -> None:
            span = record["structure"]["relationships"][0]["evidence_spans"][0]
            span.update(text_path="sources/a.pdf", text_sha256=span["sha256"], start_byte=0, end_byte=4,
                        quote_sha256=_sha256(b"%PDF"))

        for mutate in (structural, relationship_text, relationship_path, relationship_pdf_as_text):
            with self.subTest(mutate=mutate.__name__), self.assertRaises(StandardsForgeError) as caught:
                validate_pack_directory(self._write_pack(mutate=mutate))
            self.assertEqual("invalid_record", caught.exception.code)

    def test_semantics_without_derivation_is_typed(self) -> None:
        semantics = {"schema_version": "0.1.0", "content_role": "prose", "normativity": "informative", "statement": None,
                     "qualifiers": [], "quantities": [], "unresolved_issues": [], "project_applicability": "not_decided"}
        with self.assertRaises(StandardsForgeError) as caught:
            validate_pack_directory(self._write_pack(derivation=False, semantics=semantics))
        self.assertEqual("invalid_record", caught.exception.code)

    def test_malformed_semantic_shapes_are_typed(self) -> None:
        base = {"schema_version": "0.1.0", "content_role": "prose", "normativity": "informative", "statement": None,
                "qualifiers": [], "quantities": [], "unresolved_issues": [], "project_applicability": "not_decided"}
        for field, value in (("qualifiers", 5), ("quantities", None), ("content_role", ["prose"]),
                             ("normativity", {"a": 1}), ("unresolved_issues", [["x"]]),
                             ("qualifiers", [{"kind": "condition", "exact_text": "x", "span_indices": [[0]]}])):
            with self.subTest(field=field), self.assertRaises(StandardsForgeError):
                _validate_semantic_record({**base, field: value}, record_text="x", statement_role="informative",
                                          kind="clause", span_fragments=["x"])

    def test_unhashable_manifest_value_is_typed(self) -> None:
        root = self._write_pack()
        manifest = json.loads((root / "manifest.json").read_text())
        manifest["representation"] = ["page_text"]
        (root / "manifest.json").write_text(json.dumps(manifest))
        inventory = json.loads((root / "inventory.json").read_text())
        for entry in inventory["files"]:
            data = (root / entry["path"]).read_bytes()
            entry.update(sha256=_sha256(data), bytes=len(data))
        (root / "inventory.json").write_text(json.dumps(inventory))
        with self.assertRaises(StandardsForgeError) as caught:
            validate_pack_directory(root)
        self.assertEqual("invalid_pack", caught.exception.code)


class _FakeResponse:
    def __init__(self, url: str, payload: bytes, *, content_length: int | None = None) -> None:
        self.url = url
        self.payload = payload
        self.offset = 0
        self.closed = False
        self.headers = Message()
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def geturl(self) -> str:
        return self.url

    def read(self, size: int = -1) -> bytes:
        size = len(self.payload) - self.offset if size < 0 else size
        chunk = self.payload[self.offset:self.offset + min(size, 7)]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class _FakeOpener:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requests: list[str] = []

    def open(self, request: Request, timeout: float) -> _FakeResponse:
        self.requests.append(request.full_url)
        return self.response


class AcquisitionHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(socket, "socket", side_effect=AssertionError("network access attempted"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="standardsforge-acquisition-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = acquisition._HttpClient(delay_seconds=0, retries=1)
        self.component = {"local_path": "101/doc.pdf", "token": "123.456",
                          "source_url": acquisition.IMAGE_URL.format(token="123.456")}

    def test_redirects_only_to_official_https_host(self) -> None:
        self.assertTrue(any(isinstance(handler, acquisition._OfficialRedirectHandler) for handler in self.client._opener.handlers))
        handler = acquisition._OfficialRedirectHandler()
        request = Request("https://quicksearch.dla.mil/WMX/Default.aspx?token=123")
        for target in ("https://evil.example/doc.pdf", "http://quicksearch.dla.mil/doc.pdf",
                       "https://quicksearch.dla.mil:8443/doc.pdf", "https://quicksearch.dla.mil.evil.example/doc.pdf",
                       "https://user@quicksearch.dla.mil/doc.pdf", "ftp://quicksearch.dla.mil/doc.pdf"):
            with self.subTest(target=target), self.assertRaises(StandardsForgeError) as caught:
                handler.redirect_request(request, None, 302, "Found", Message(), target)
            self.assertEqual("source_redirect_rejected", caught.exception.code)
        allowed = handler.redirect_request(request, None, 302, "Found", Message(), "https://quicksearch.dla.mil/doc.pdf")
        self.assertEqual("https://quicksearch.dla.mil/doc.pdf", allowed.full_url)

    def test_rejects_unofficial_request_and_final_url(self) -> None:
        with self.assertRaises(StandardsForgeError) as caught:
            self.client.open("https://evil.example/doc.pdf")
        self.assertEqual("source_url_rejected", caught.exception.code)
        response = _FakeResponse("https://evil.example/doc.pdf", b"%PDF-forged")
        self.client._opener = _FakeOpener(response)
        with self.assertRaises(StandardsForgeError) as caught:
            self.client.open(acquisition.QUICK_SEARCH_URL)
        self.assertEqual("source_redirect_rejected", caught.exception.code)
        self.assertTrue(response.closed)

    def test_download_enforces_byte_limit_while_streaming(self) -> None:
        payload = b"%PDF-" + b"x" * 59
        for content_length in (None, len(payload)):
            with self.subTest(content_length=content_length):
                self.client._opener = _FakeOpener(_FakeResponse("https://quicksearch.dla.mil/doc.pdf", payload, content_length=content_length))
                with patch.object(acquisition, "MAX_SOURCE_DOWNLOAD_BYTES", 32), self.assertRaises(StandardsForgeError) as caught:
                    acquisition._download_component(self.client, dict(self.component), self.root, "detail")
                self.assertEqual("source_limit_exceeded", caught.exception.code)
                self.assertEqual([], list(self.root.rglob("*.pdf*")))
        self.client._opener = _FakeOpener(_FakeResponse("https://quicksearch.dla.mil/doc.pdf", payload))
        component = dict(self.component)
        acquisition._download_component(self.client, component, self.root, "detail")
        self.assertEqual(("downloaded", _sha256(payload), len(payload)),
                         (component["acquisition_status"], component["sha256"], component["byte_length"]))
        self.assertEqual(acquisition.MAX_SOURCE_DOWNLOAD_BYTES, 256 * 1024 * 1024)

    def test_html_pages_are_bounded(self) -> None:
        self.client._opener = _FakeOpener(_FakeResponse(acquisition.QUICK_SEARCH_URL, b"<html>" + b"x" * 100))
        with patch.object(acquisition, "MAX_SOURCE_PAGE_BYTES", 50), self.assertRaises(StandardsForgeError) as caught:
            self.client.text(acquisition.QUICK_SEARCH_URL)
        self.assertEqual("source_limit_exceeded", caught.exception.code)
        self.client._opener = _FakeOpener(_FakeResponse(acquisition.QUICK_SEARCH_URL, b"<html>ok</html>"))
        self.assertEqual("<html>ok</html>", self.client.text(acquisition.QUICK_SEARCH_URL))


if __name__ == "__main__":
    unittest.main()
