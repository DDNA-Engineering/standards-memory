from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from standardsforge.pack import validate_pack_directory, write_pack_archive  # noqa: E402


FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
BUFFER_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _validate_corpus(corpus_index: Path) -> tuple[dict, list[tuple[Path, str]]]:
    index = _load_json(corpus_index)
    entries = index.get("entries")
    summary = index.get("summary")
    if not isinstance(entries, list) or not isinstance(summary, dict):
        raise ValueError("Corpus index is missing entries or summary.")
    if summary.get("status") != "complete" or index.get("failures") not in ({}, []):
        raise ValueError("Only a complete, failure-free corpus may be distributed.")

    corpus_root = corpus_index.parent.resolve()
    payloads: list[tuple[Path, str]] = []
    digests: set[str] = set()
    pack_ids: set[str] = set()
    for entry in entries:
        archive_relative = entry.get("archive_path")
        package_digest = entry.get("package_digest")
        pack_id = entry.get("pack_id")
        if not all(isinstance(value, str) and value for value in (archive_relative, package_digest, pack_id)):
            raise ValueError("Every corpus entry must identify its archive, package digest, and pack ID.")
        archive = (corpus_root / archive_relative).resolve()
        try:
            archive.relative_to(corpus_root)
        except ValueError as exc:
            raise ValueError(f"Corpus archive escapes its root: {archive_relative}") from exc
        if not archive.is_file():
            raise ValueError(f"Corpus archive is missing: {archive}")
        if archive.stat().st_size != entry.get("archive_bytes") or _sha256(archive) != entry.get("archive_sha256"):
            raise ValueError(f"Corpus archive failed its recorded size or digest: {archive}")
        if package_digest in digests or pack_id in pack_ids:
            raise ValueError("Corpus package digests and pack IDs must be unique.")
        digests.add(package_digest)
        pack_ids.add(pack_id)
        payloads.append((archive, f"corpus/{archive_relative.replace('\\', '/')}"))

    if len(entries) != summary.get("compiled_record_count"):
        raise ValueError("Corpus summary count does not match its entries.")
    return index, payloads


def _validate_policy(policy_path: Path, expected_pack_ids: set[str], principal: str) -> None:
    policy = _load_json(policy_path)
    if policy.get("principal_id") != principal:
        raise ValueError(f"Distribution policy must be bound to {principal}: {policy_path}")
    if set(policy.get("allowed_pack_ids", [])) != expected_pack_ids:
        raise ValueError(f"Distribution policy does not exactly authorize its pack set: {policy_path}")
    if policy.get("allowed_content_classes") != ["public_government_standard"]:
        raise ValueError(f"Distribution policy has an unexpected content class: {policy_path}")


def _write_file(archive: zipfile.ZipFile, source: Path, destination: str) -> None:
    info = zipfile.ZipInfo(destination, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED if source.suffix.lower() in {".zip", ".whl"} else zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    with source.open("rb") as input_stream, archive.open(info, "w", force_zip64=True) as output_stream:
        shutil.copyfileobj(input_stream, output_stream, BUFFER_SIZE)


def _write_bytes(archive: zipfile.ZipFile, value: bytes, destination: str) -> None:
    info = zipfile.ZipInfo(destination, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, value)


def build_distribution(
    corpus_index: Path,
    outline_pack: Path,
    wheel: Path,
    output: Path,
    version: str,
    compresslevel: int,
) -> dict:
    corpus_index = corpus_index.resolve()
    outline_pack = outline_pack.resolve()
    wheel = wheel.resolve()
    output = output.resolve()
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    if output.exists() or checksum_path.exists():
        raise ValueError(f"Output already exists: {output}")
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError(f"Expected one built wheel: {wheel}")

    index, corpus_payloads = _validate_corpus(corpus_index)
    entries = index["entries"]
    outline = validate_pack_directory(outline_pack)
    corpus_policy = REPOSITORY_ROOT / ".standardsforge" / "policies" / "mil-std-corpus-local.json"
    outline_policy = REPOSITORY_ROOT / ".standardsforge" / "policies" / "mil-std-810h-derived-outline-local.json"
    _validate_policy(corpus_policy, {entry["pack_id"] for entry in entries}, "local-user")
    _validate_policy(outline_policy, {outline.manifest["pack_id"]}, "local-user")

    static_root = REPOSITORY_ROOT / "scripts" / "prepared_distribution"
    static_files = [
        (static_root / "README.md", "README.md"),
        (static_root / "setup.ps1", "setup.ps1"),
        (static_root / "standardsforge.ps1", "standardsforge.ps1"),
        (static_root / "CONTENT-NOTICE.md", "CONTENT-NOTICE.md"),
        (REPOSITORY_ROOT / "LICENSE", "LICENSE"),
        (corpus_index, "corpus/corpus.json"),
        (corpus_policy, "policies/mil-std-corpus-local.json"),
        (outline_policy, "policies/mil-std-810h-derived-outline-local.json"),
        (wheel, f"wheel/{wheel.name}"),
    ]
    for source, _ in static_files:
        if not source.is_file():
            raise ValueError(f"Distribution input is missing: {source}")

    with tempfile.TemporaryDirectory(prefix="standardsforge-distribution-") as temporary:
        outline_archive = Path(temporary) / "mil-std-810h-derived-outline.zip"
        write_pack_archive(outline_pack, outline_archive, compresslevel=compresslevel)
        payload_files = [
            *static_files,
            *corpus_payloads,
            (outline_archive, "packs/mil-std-810h-derived-outline.zip"),
        ]
        file_inventory = [
            {"path": destination, "bytes": source.stat().st_size, "sha256": _sha256(source)}
            for source, destination in payload_files
        ]
        summary = index["summary"]
        distribution_summary = {
            "corpus_id": index.get("corpus_id"),
            "corpus_package_count": len(entries),
            "included_package_count": len(entries) + 1,
            "page_record_count": summary.get("page_records"),
            "source_pdf_count": summary.get("verified_pdf_count"),
            "physical_page_count": summary.get("physical_pages"),
            "principal_id": "local-user",
            "mil_std_810h_derived_package_digest": outline.package_digest,
        }
        manifest = {
            "schema_version": "1.0",
            "product": "StandardsForge prepared distribution",
            "version": version,
            "state": distribution_summary,
            "files": file_inventory,
        }
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_suffix(output.suffix + ".partial")
        prefix = f"standardsforge-ready-{version}/"
        try:
            with zipfile.ZipFile(
                partial,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=compresslevel,
                allowZip64=True,
            ) as archive:
                for source, destination in payload_files:
                    _write_file(archive, source, prefix + destination)
                _write_bytes(archive, manifest_bytes, prefix + "bundle-manifest.json")
            partial.replace(output)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    archive_sha256 = _sha256(output)
    checksum_path.write_text(f"{archive_sha256}  {output.name}\n", encoding="ascii", newline="\n")
    return {
        "output": str(output),
        "bytes": output.stat().st_size,
        "sha256": archive_sha256,
        **distribution_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a self-contained, precompiled StandardsForge distribution.")
    parser.add_argument("--corpus-index", required=True, type=Path)
    parser.add_argument("--outline-pack", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--compresslevel", type=int, choices=range(1, 10), default=9)
    args = parser.parse_args()
    result = build_distribution(
        args.corpus_index,
        args.outline_pack,
        args.wheel,
        args.output,
        args.version,
        args.compresslevel,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
