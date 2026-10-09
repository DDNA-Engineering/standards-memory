"""Shared helpers for regenerating the derived review inputs of this batch.

The committed ``<slug>/annotations.json`` files are the reviewed inputs. These tools only
derive the regression suites, the reference-binding artifact and the pinned index from
them and from an extracted prepared corpus; they never alter the annotations.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
REVIEW_DIR = Path(__file__).resolve().parents[1]
SUITES_DIR = ROOT / "benchmarks" / "real"
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.coverage_ledger import digest  # noqa: E402,F401
from standardsforge.structure_compiler import compile_reviewed_page_section  # noqa: E402

ORDER = [
    "mil-std-882e-system-safety-requirements",
    "mil-std-461h-general-requirements",
    "mil-std-464d-e3-general-and-emi",
    "mil-std-704f-general-requirements",
    "mil-std-1474e-noise-general-requirements",
    "mil-std-1472h-acoustic-noise-design",
]
REVIEWED_AT = "2026-10-09T00:00:00Z"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_index_path(corpus: str | Path) -> Path:
    path = Path(corpus).resolve()
    return path / "corpus.json" if path.is_dir() else path


def record_id(edition_id: str, logical_id: str) -> str:
    return "struct-" + hashlib.sha256(f"{edition_id}\0{logical_id}".encode("utf-8")).hexdigest()[:24]


def annotation_path(slug: str) -> Path:
    return REVIEW_DIR / slug / "annotations.json"


def load_annotation(slug: str) -> dict[str, Any]:
    return json.loads(annotation_path(slug).read_text(encoding="utf-8"))


def compile_reviewed(corpus: str | Path) -> dict[str, dict[str, Any]]:
    """Compile every annotation against its pinned corpus archive in a temporary directory."""
    index_path = corpus_index_path(corpus)
    corpus_document = json.loads(index_path.read_text(encoding="utf-8"))
    entries = {entry["package_digest"]: entry for entry in corpus_document["entries"]}
    result = {}
    with tempfile.TemporaryDirectory(prefix="review-tools-") as temporary:
        for slug in ORDER:
            annotation = load_annotation(slug)
            entry = entries[annotation["source_page_pack_digest"]]
            compiled = compile_reviewed_page_section(index_path.parent / entry["archive_path"], annotation_path(slug), Path(temporary) / slug)
            result[slug] = {"package_digest": compiled["package_digest"], "annotation": annotation, "entry": entry}
    return {"corpus": corpus_document, "packs": result}


def write_json(path: Path, value: Any, indent: int) -> None:
    path.write_text(json.dumps(value, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
