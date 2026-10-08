"""Inventory a verified corpus locally, with no content acquisition or query writes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from standardsforge.corpus_compiler import _load_complete_corpus_index
from standardsforge.coverage_ledger import digest, page_ledger, write_artifact
from standardsforge.errors import require
from standardsforge.pack import open_validated_pack


def build(index_path: Path, output: Path) -> dict:
    index_path, index = _load_complete_corpus_index(index_path)
    require(not output.exists(), "output_exists", "Coverage output already exists.")
    output.mkdir(parents=True)
    packages = []
    for entry in index["entries"]:
        relative = PurePosixPath(entry["archive_path"])
        require(not relative.is_absolute() and ".." not in relative.parts and relative.parts[0] == "packs", "invalid_corpus_index", "Unsafe corpus archive path.")
        archive = index_path.parent.joinpath(*relative.parts)
        require(archive.resolve().is_relative_to(index_path.parent) and not archive.is_symlink(), "invalid_corpus_index", "Corpus archive escaped its root.")
        with archive.open("rb") as stream:
            require(hashlib.file_digest(stream, "sha256").hexdigest() == entry["archive_sha256"], "corpus_archive_mismatch", "Corpus archive digest mismatch.")
        with open_validated_pack(archive) as pack:
            require(pack.package_digest == entry["package_digest"], "corpus_archive_mismatch", "Corpus package identity mismatch.")
            artifact = page_ledger(pack)
        relative_output = f"{pack.package_digest}.json"
        write_artifact(output / relative_output, artifact)
        ledger = artifact["ledger"]
        packages.append({"path": relative_output, "ledger_sha256": artifact["ledger_sha256"], **{k: ledger[k] for k in ("package_digest", "identifier", "physical_pages", "pages_without_text", "text_bytes", "unavailable_components")}})
        if len(packages) % 25 == 0:
            print(f"Verified coverage for {len(packages)}/{len(index['entries'])} packs", flush=True)
    require(len({p["package_digest"] for p in packages}) == len(packages), "invalid_corpus_index", "Repeated package identity.")
    total_pages = sum(p["physical_pages"] for p in packages)
    require(total_pages == index["summary"]["physical_pages"], "invalid_corpus_index", "Corpus physical-page total mismatch.")
    body = {"corpus_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(), "packages": packages,
            "physical_pages": total_pages, "pages_without_text": sum(p["pages_without_text"] for p in packages),
            "undisposed_text_bytes": sum(p["text_bytes"] for p in packages), "semantic_qualification": "not_established",
            "visual_review": "pending", "approval": "not_granted"}
    artifact = {"schema_version": "0.1.0", "coverage": body, "coverage_sha256": digest(body)}
    write_artifact(output / "coverage.json", artifact)
    return artifact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build(args.index, args.output)
    print(json.dumps({k: v for k, v in result["coverage"].items() if k != "packages"}, indent=2))
