"""Regenerate reviews/agent-review-2026-10/index.json pinning sources, annotations, suites and bindings.

Usage: python reviews/agent-review-2026-10/tools/gen_index.py --corpus PATH/TO/corpus

Run after gen_suites.py and gen_bindings.py; the index pins their exact bytes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ORDER, REVIEW_DIR, SUITES_DIR, annotation_path, compile_reviewed, sha256_file, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True, help="Extracted prepared corpus directory or its corpus.json")
    args = parser.parse_args()
    compiled = compile_reviewed(args.corpus)
    corpus = compiled["corpus"]
    packs = []
    for slug in ORDER:
        item = compiled["packs"][slug]
        annotation, entry = item["annotation"], item["entry"]
        packs.append({
            "slug": slug,
            "content_class": "public_government_standard",
            "annotations": f"{slug}/annotations.json",
            "annotations_sha256": sha256_file(annotation_path(slug)),
            "suite": f"../../benchmarks/real/{slug}.json",
            "suite_sha256": sha256_file(SUITES_DIR / f"{slug}.json"),
            "expected_package_digest": item["package_digest"],
            "source": {"ident_number": entry["ident_number"], "document_id": entry["document_id"], "edition_id": entry["edition_id"],
                       "package_digest": entry["package_digest"], "archive_path": entry["archive_path"],
                       "archive_sha256": entry["archive_sha256"], "source_pdf_sha256": annotation["source_pdf_sha256"]},
        })
    index = {
        "schema_version": "0.1.0",
        "batch_id": "agent-review-2026-10",
        "review": {"kind": "agent", "independence_claim": "self_review",
                   "attestation": "extraction_review_not_project_applicability_or_approval"},
        "corpus": {key: corpus[key] for key in ("corpus_id", "acquisition_manifest_sha256", "compiler_version")},
        "packs": packs,
        "reference_bindings": {"path": "reference-bindings.json", "sha256": sha256_file(REVIEW_DIR / "reference-bindings.json")},
    }
    write_json(REVIEW_DIR / "index.json", index, indent=2)
    print("index written for", len(packs), "packs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
