"""Restartable administrative outline derivation from an exact local corpus."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from standardsforge.errors import StandardsForgeError, require
from standardsforge.outline_compiler import OUTLINE_COMPILER_VERSION, compile_derived_outline_pack
from standardsforge.pack import validate_pack_directory


def compile_corpus(index_path: Path, output: Path) -> dict:
    data = index_path.read_bytes()
    index = json.loads(data)
    require(index.get("summary", {}).get("status") == "complete", "incomplete_corpus", "Require a complete local page-text corpus.")
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for ordinal, entry in enumerate(index["entries"], 1):
        source = (index_path.parent / entry["archive_path"]).resolve(strict=True)
        source.relative_to(index_path.parent.resolve())
        with source.open("rb") as reader:
            source_digest = hashlib.file_digest(reader, "sha256").hexdigest()
        require(source_digest == entry["archive_sha256"] and source.stat().st_size == entry["archive_bytes"],
                "source_integrity_failure", "Source archive changed.")
        digest = entry["package_digest"]
        from standardsforge.service import StandardsForgeService
        StandardsForgeService._validate_package_digest(digest)
        target = output / digest
        try:
            if not target.exists():
                compile_derived_outline_pack(source, target)
            pack = validate_pack_directory(target)
            report = json.loads((target / "derived-outline-report.json").read_text(encoding="utf-8"))
            require(report["base_package_digest"] == digest and report["compiler"]["version"] == OUTLINE_COMPILER_VERSION,
                    "stale_outline", "Existing outline does not match the requested source and compiler.")
            entries.append({"source_package_digest": digest, "outline_package_digest": pack.package_digest,
                            "records": len(pack.records), "status": "compiled", "error": None})
        except StandardsForgeError as exc:
            entries.append({"source_package_digest": digest, "outline_package_digest": None,
                            "records": 0, "status": "failed", "error": exc.code})
        print(f"{ordinal}/{len(index['entries'])}: {entries[-1]['status']} {entry['document_id']}", file=sys.stderr, flush=True)
    result = {"schema_version": "0.1.0", "operation": "compile_corpus_outlines",
              "source_index_sha256": hashlib.sha256(data).hexdigest(), "compiler_version": OUTLINE_COMPILER_VERSION,
              "classification": "automated_unreviewed_not_semantic_qualification", "entries": entries}
    (output / "outlines.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = compile_corpus(args.corpus, args.output)
    failures = sum(e["status"] == "failed" for e in result["entries"])
    print(json.dumps({"packages": len(result["entries"]), "failures": failures,
                      "records": sum(e["records"] for e in result["entries"])}))
    raise SystemExit(1 if failures else 0)
