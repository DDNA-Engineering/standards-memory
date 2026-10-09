"""Rebuild the agent-reviewed semantic supplement from committed review inputs.

Administrative and offline. Given an extracted prepared corpus (its ``corpus.json``
and page-text archives) and the committed review index, this script:

* verifies every pinned source archive, review annotation, real-document suite and
  reference-binding artifact before use (changed, stale or missing inputs fail closed);
* compiles each reviewed pack twice and requires identical package digests and
  identical deterministic ZIP bytes;
* writes an exact one-pack ``local-user`` policy per pack (``write-pack-policy``);
* installs every pack into a fresh temporary store and replays each real suite and
  every reviewed reference binding with socket creation denied;
* writes a new output directory only after every gate passed.

The supplement is agent self-review evidence. It does not establish human review,
independent adjudication, corpus-wide coverage, applicability, compliance or approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.coverage_ledger import digest, link_semantic_evidence, page_ledger, write_artifact  # noqa: E402
from standardsforge.errors import StandardsForgeError, require  # noqa: E402
from standardsforge.pack import open_validated_pack, write_pack_archive  # noqa: E402
from standardsforge.policy import load_policy, write_pack_policy  # noqa: E402
from standardsforge.real_benchmark import run_real_benchmark, validate_run, validate_suite  # noqa: E402
from standardsforge.reference_bindings import validate_bindings  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402
from standardsforge.structure_compiler import compile_reviewed_page_section  # noqa: E402

DEFAULT_INDEX = ROOT / "reviews" / "agent-review-2026-10" / "index.json"
SUPPLEMENT_SCHEMA_VERSION = "0.1.0"
_SLUG = re.compile(r"[a-z0-9-]+")
_HEX = re.compile(r"[0-9a-f]{64}")
_INDEX_KEYS = {"schema_version", "batch_id", "review", "corpus", "packs", "reference_bindings"}
_REVIEW = {"kind": "agent", "independence_claim": "self_review",
           "attestation": "extraction_review_not_project_applicability_or_approval"}
_CORPUS_KEYS = {"corpus_id", "acquisition_manifest_sha256", "compiler_version"}
_PACK_KEYS = {"slug", "content_class", "annotations", "annotations_sha256", "suite", "suite_sha256", "expected_package_digest", "source"}
_SOURCE_KEYS = {"ident_number", "document_id", "edition_id", "package_digest", "archive_path", "archive_sha256", "source_pdf_sha256"}
LIMITATIONS = [
    "Agent self-review only (independence_claim: self_review): the same agent authored the annotations, suites and bindings; no human review or independent adjudication.",
    "Each pack covers only an explicitly selected bounded scope of one source component; all other pages, components and documents remain unreviewed.",
    "Review used the exact verified page-text layer; PDF pages were not visually inspected and table column association is from text-layer order.",
    "Real-document suites are bounded regressions derived from the reviewed annotations; they do not measure corpus-wide recall or answer quality.",
    "Reference bindings are reviewer-selected one-hop navigation only; they are not source-mandated or project-approved editions.",
    "Nothing in this supplement decides applicability, compliance, tailoring, baseline selection or approval, and no redistribution right is granted.",
]


def _fail(code: str, message: str, **details: Any) -> None:
    raise StandardsForgeError(code, message, details)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError(code, "A required supplement input is unreadable JSON.", {"path": path.name}) from exc


def _relative(base: Path, value: Any, label: str) -> Path:
    require(isinstance(value, str) and value and "\\" not in value and not PurePosixPath(value).is_absolute(),
            "invalid_supplement_index", f"{label} must be a relative POSIX path.")
    return (base / Path(*PurePosixPath(value).parts)).resolve()


def load_index(index_path: str | Path) -> tuple[dict[str, Any], Path]:
    path = Path(index_path).resolve()
    require(path.is_file(), "supplement_review_missing", "The review index does not exist.")
    index = _load_json(path, "invalid_supplement_index")
    require(isinstance(index, dict) and set(index) == _INDEX_KEYS and index["schema_version"] == "0.1.0",
            "invalid_supplement_index", "Review index fields are closed.")
    require(index["review"] == _REVIEW, "invalid_supplement_index", "The index must declare agent self-review without approval.")
    require(isinstance(index["batch_id"], str) and _SLUG.fullmatch(index["batch_id"]) is not None, "invalid_supplement_index", "Invalid batch ID.")
    require(isinstance(index["corpus"], dict) and set(index["corpus"]) == _CORPUS_KEYS, "invalid_supplement_index", "Corpus pin fields are closed.")
    packs = index["packs"]
    require(isinstance(packs, list) and packs, "invalid_supplement_index", "At least one reviewed pack is required.")
    slugs = set()
    for pack in packs:
        require(isinstance(pack, dict) and set(pack) == _PACK_KEYS, "invalid_supplement_index", "Pack entry fields are closed.")
        require(isinstance(pack["slug"], str) and _SLUG.fullmatch(pack["slug"]) is not None and pack["slug"] not in slugs,
                "invalid_supplement_index", "Slugs must be unique and match [a-z0-9-]+.", slug=pack.get("slug"))
        slugs.add(pack["slug"])
        require(isinstance(pack["source"], dict) and set(pack["source"]) == _SOURCE_KEYS, "invalid_supplement_index", "Source pin fields are closed.")
        for key in ("annotations_sha256", "suite_sha256", "expected_package_digest"):
            require(isinstance(pack[key], str) and _HEX.fullmatch(pack[key]) is not None, "invalid_supplement_index", f"{key} must be SHA-256.")
        for key in ("package_digest", "archive_sha256", "source_pdf_sha256"):
            require(isinstance(pack["source"][key], str) and _HEX.fullmatch(pack["source"][key]) is not None,
                    "invalid_supplement_index", f"source {key} must be SHA-256.")
        require(isinstance(pack["content_class"], str) and pack["content_class"], "invalid_supplement_index", "Content class is required.")
    bindings = index["reference_bindings"]
    require(isinstance(bindings, dict) and set(bindings) == {"path", "sha256"} and isinstance(bindings["sha256"], str)
            and _HEX.fullmatch(bindings["sha256"]) is not None, "invalid_supplement_index", "Reference binding pin fields are closed.")
    return index, path.parent


def _corpus_index(corpus: str | Path) -> Path:
    path = Path(corpus).resolve()
    if path.is_dir():
        path = path / "corpus.json"
    require(path.is_file(), "supplement_source_missing", "The corpus index does not exist.", path=str(path))
    return path


def _verify_source(pack: dict[str, Any], corpus_root: Path, entries: dict[str, dict[str, Any]]) -> Path:
    source = pack["source"]
    entry = entries.get(source["package_digest"])
    if entry is None:
        _fail("supplement_source_changed", "The pinned source package is absent from the corpus index.", slug=pack["slug"])
    for key, entry_key in (("ident_number", "ident_number"), ("document_id", "document_id"), ("edition_id", "edition_id"),
                           ("archive_path", "archive_path"), ("archive_sha256", "archive_sha256")):
        if entry.get(entry_key) != source[key]:
            _fail("supplement_source_changed", "The corpus index entry differs from the pinned source.", slug=pack["slug"], field=key)
    archive = _relative(corpus_root, source["archive_path"], "archive_path")
    require(corpus_root in archive.parents, "invalid_supplement_index", "Source archives must stay inside the corpus directory.")
    if not archive.is_file():
        _fail("supplement_source_missing", "The pinned source archive is missing.", slug=pack["slug"], path=source["archive_path"])
    if _sha256_file(archive) != source["archive_sha256"]:
        _fail("supplement_source_changed", "The source archive bytes differ from the pinned digest.", slug=pack["slug"])
    return archive


def _verify_annotations(pack: dict[str, Any], base: Path) -> Path:
    path = _relative(base, pack["annotations"], "annotations")
    if not path.is_file():
        _fail("supplement_review_missing", "The committed review annotation is missing.", slug=pack["slug"])
    if _sha256_file(path) != pack["annotations_sha256"]:
        _fail("supplement_review_stale", "The review annotation differs from its pinned digest.", slug=pack["slug"])
    annotation = _load_json(path, "supplement_review_stale")
    source = pack["source"]
    if (annotation.get("schema_version") != "0.6.0" or annotation.get("source_page_pack_digest") != source["package_digest"]
            or annotation.get("edition_id") != source["edition_id"] or annotation.get("source_pdf_sha256") != source["source_pdf_sha256"]
            or annotation.get("review", {}).get("reviewer_type") != "agent"):
        _fail("supplement_review_stale", "The review annotation does not bind the pinned agent-reviewed source.", slug=pack["slug"])
    return path


def _compile_twice(slug: str, archive: Path, annotations: Path, work: Path, destination: Path) -> str:
    first, second = work / f"{slug}-a", work / f"{slug}-b"
    digests = [compile_reviewed_page_section(archive, annotations, target)["package_digest"] for target in (first, second)]
    write_pack_archive(first, destination)
    replay = work / f"{slug}-b.zip"
    write_pack_archive(second, replay)
    if digests[0] != digests[1] or destination.read_bytes() != replay.read_bytes():
        _fail("supplement_not_reproducible", "Two compilations of the same review produced different bytes.", slug=slug)
    return digests[0]


def _verify_suite(pack: dict[str, Any], base: Path, package_digest: str, edition_id: str) -> tuple[Path, dict[str, Any]]:
    path = _relative(base, pack["suite"], "suite")
    if not path.is_file():
        _fail("supplement_review_missing", "The committed real-document suite is missing.", slug=pack["slug"])
    if _sha256_file(path) != pack["suite_sha256"]:
        _fail("supplement_review_stale", "The real-document suite differs from its pinned digest.", slug=pack["slug"])
    document = _load_json(path, "supplement_review_stale")
    suite = validate_suite(document)
    if suite["package_digest"] != package_digest or suite["edition_id"] != edition_id:
        _fail("supplement_review_stale", "The suite pins a different reviewed package or edition.", slug=pack["slug"])
    if document["review"]["kind"] != "agent":
        _fail("supplement_review_stale", "The suite must declare agent review.", slug=pack["slug"])
    return path, document


def _verify_bindings(index: dict[str, Any], base: Path, service: StandardsForgeService, principal: str,
                     packages: dict[str, str]) -> tuple[Path, dict[str, Any], dict[str, int]]:
    path = _relative(base, index["reference_bindings"]["path"], "reference_bindings")
    if not path.is_file():
        _fail("supplement_review_missing", "The reviewed reference-binding artifact is missing.")
    sha256 = _sha256_file(path)
    if sha256 != index["reference_bindings"]["sha256"]:
        _fail("supplement_review_stale", "The reference-binding artifact differs from its pinned digest.")
    document = _load_json(path, "supplement_review_stale")
    body = validate_bindings(document)
    by_source: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for binding in body["bindings"]:
        selectors = [binding["source"]] + ([binding["target"]] if binding["target"] is not None else [])
        for selector in selectors:
            if packages.get(selector["package_digest"]) != selector["edition_id"]:
                _fail("supplement_review_stale", "A reference binding names a package outside this supplement.", binding_id=binding["binding_id"])
        if binding["review"]["kind"] != "agent":
            _fail("supplement_review_stale", "Reference bindings must declare agent review.", binding_id=binding["binding_id"])
        by_source.setdefault((binding["source"]["package_digest"], binding["source"]["record_id"]), []).append(binding)
    service.configure_reference_bindings(path, sha256)
    returned = resolved = 0
    for (package_digest, record_id), expected in by_source.items():
        packet = service.follow_references(package_digest, record_id, principal)
        ids = sorted(reference["binding"]["binding_id"] for reference in packet["references"])
        if ids != sorted(binding["binding_id"] for binding in expected):
            _fail("supplement_review_stale", "Followed references differ from the reviewed bindings.", record_id=record_id)
        for reference in packet["references"]:
            target = reference["target_evidence"]
            if (reference["binding"]["status"] == "resolved") != (target is not None):
                _fail("supplement_review_stale", "A reviewed binding did not resolve as declared.", binding_id=reference["binding"]["binding_id"])
            returned += 1
            resolved += target is not None
    counts = {"bindings": len(body["bindings"]), "followed": returned, "resolved": resolved,
              "unresolved": len(body["bindings"]) - resolved, "source_records": len(by_source)}
    return path, document, counts


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def build_supplement(corpus: str | Path, output: str | Path, *, index_path: str | Path = DEFAULT_INDEX,
                     principal: str = "local-user") -> dict[str, Any]:
    """Build and verify the supplement; returns the written supplement manifest."""
    output_path = Path(output).resolve()
    require(not output_path.exists(), "supplement_output_exists", "The supplement output already exists.", path=str(output_path))
    index, base = load_index(index_path)
    corpus_path = _corpus_index(corpus)
    corpus_document = _load_json(corpus_path, "supplement_source_changed")
    for key in _CORPUS_KEYS:
        if corpus_document.get(key) != index["corpus"][key]:
            _fail("supplement_source_changed", "The corpus index differs from the pinned corpus identity.", field=key)
    entries = {entry["package_digest"]: entry for entry in corpus_document.get("entries", [])}
    corpus_root = corpus_path.parent
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".reviewed-supplement-", dir=output_path.parent))
    try:
        with tempfile.TemporaryDirectory(prefix="standardsforge-supplement-") as temporary, \
                patch.object(socket, "socket", side_effect=RuntimeError("Network is forbidden while building the supplement")):
            work = Path(temporary)
            built: list[dict[str, Any]] = []
            for pack in index["packs"]:
                slug = pack["slug"]
                archive = _verify_source(pack, corpus_root, entries)
                annotations = _verify_annotations(pack, base)
                pack_path = staging / "packs" / f"{slug}.zip"
                pack_path.parent.mkdir(parents=True, exist_ok=True)
                package_digest = _compile_twice(slug, archive, annotations, work, pack_path)
                if package_digest != pack["expected_package_digest"]:
                    _fail("supplement_review_stale", "The compiled package differs from the pinned reviewed package.", slug=slug)
                with open_validated_pack(pack_path) as reviewed, open_validated_pack(archive) as source:
                    manifest = reviewed.manifest
                    records = reviewed.records
                    coverage = link_semantic_evidence(source, reviewed, page_ledger(source))
                suite_path, suite_document = _verify_suite(pack, base, package_digest, manifest["edition_id"])
                policy_path = staging / "policies" / f"{slug}.json"
                write_pack_policy(pack_path, policy_path, principal, pack["content_class"])
                policy = load_policy(policy_path)
                require(policy.allowed_pack_ids == frozenset({manifest["pack_id"]}), "supplement_policy_invalid", "Policy scope is not exact.")
                (staging / "qualification").mkdir(exist_ok=True)
                shutil.copyfile(suite_path, staging / "qualification" / f"{slug}-suite.json")
                _write_json(staging / "qualification" / f"{slug}-coverage.json", coverage)
                linked_pages = [page for page in coverage["ledger"]["pages"] if page["semantically_linked_bytes"]]
                built.append({
                    "slug": slug, "pack": pack, "pack_path": pack_path, "policy_path": policy_path, "suite": suite_document,
                    "package_digest": package_digest, "manifest": manifest,
                    "records": len(records),
                    "obligations": sum(record["derivation"]["statement_role"] == "obligation" for record in records),
                    "coverage": {"physical_pages": coverage["ledger"]["physical_pages"], "text_bytes": coverage["ledger"]["text_bytes"],
                                 "pages_with_linked_spans": len(linked_pages),
                                 "linked_bytes": sum(page["semantically_linked_bytes"] for page in coverage["ledger"]["pages"]),
                                 "ledger_sha256": coverage["ledger_sha256"]},
                })
            admin = StandardsForgeService(work / "memory.db", work / "objects")
            for item in built:
                installed = admin.install_pack(item["pack_path"], item["policy_path"])
                require(installed["package_digest"] == item["package_digest"], "supplement_install_failed", "Installed digest differs.")
            reader = StandardsForgeService.open_read_only(work / "memory.db", work / "objects")
            runtime = None
            for item in built:
                artifact = run_real_benchmark(reader, principal, item["suite"])
                validate_run(artifact, item["suite"])
                run_path = staging / "qualification" / f"{item['slug']}-run.json"
                write_artifact(run_path, artifact)
                if not artifact["run"]["gate"]["passed"]:
                    _fail("supplement_suite_failed", "A real-document regression suite failed.", slug=item["slug"], metrics=artifact["run"]["metrics"])
                runtime = artifact["run"]["runtime_source_sha256"]
                item["run"] = artifact
            packages = {item["package_digest"]: item["manifest"]["edition_id"] for item in built}
            bindings_path, _, binding_counts = _verify_bindings(index, base, reader, principal, packages)
            shutil.copyfile(bindings_path, staging / "reference-bindings.json")
        entries_out = []
        for item in built:
            source = item["pack"]["source"]
            entries_out.append({
                "slug": item["slug"],
                "pack_id": item["manifest"]["pack_id"],
                "package_digest": item["package_digest"],
                "edition_id": item["manifest"]["edition_id"],
                "document_id": item["manifest"]["identifier"],
                "source_package_digest": source["package_digest"],
                "source_archive_sha256": source["archive_sha256"],
                "source_pdf_sha256": source["source_pdf_sha256"],
                "annotations_sha256": item["pack"]["annotations_sha256"],
                "pack": f"packs/{item['slug']}.zip",
                "pack_sha256": _sha256_file(item["pack_path"]),
                "policy": f"policies/{item['slug']}.json",
                "suite": f"qualification/{item['slug']}-suite.json",
                "suite_sha256": item["pack"]["suite_sha256"],
                "run": f"qualification/{item['slug']}-run.json",
                "run_sha256": item["run"]["run_sha256"],
                "coverage": f"qualification/{item['slug']}-coverage.json",
                "records": item["records"],
                "obligation_records": item["obligations"],
                "real_suite_metrics": item["run"]["run"]["metrics"],
                "source_coverage": item["coverage"],
            })
        supplement = {
            "schema_version": SUPPLEMENT_SCHEMA_VERSION,
            "batch_id": index["batch_id"],
            "review": index["review"],
            "principal": principal,
            "corpus": index["corpus"],
            "runtime_source_sha256": runtime,
            "packs": entries_out,
            "reference_bindings": {"path": "reference-bindings.json", "sha256": index["reference_bindings"]["sha256"], **binding_counts},
            "limitations": LIMITATIONS,
        }
        _write_json(staging / "supplement.json", supplement)
        os.replace(staging, output_path)
        return supplement
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild and verify the agent-reviewed semantic supplement offline.")
    parser.add_argument("--corpus", required=True, help="Extracted prepared corpus directory or its corpus.json")
    parser.add_argument("--output", required=True, help="New output directory")
    parser.add_argument("--index", default=str(DEFAULT_INDEX), help="Committed review index (default: reviews/agent-review-2026-10/index.json)")
    parser.add_argument("--principal", default="local-user")
    args = parser.parse_args(argv)
    try:
        supplement = build_supplement(args.corpus, args.output, index_path=args.index, principal=args.principal)
    except StandardsForgeError as exc:
        print(json.dumps({"ok": False, "error": exc.as_dict()}, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "packs": [{k: p[k] for k in ("slug", "package_digest", "real_suite_metrics")} for p in supplement["packs"]],
                      "reference_bindings": supplement["reference_bindings"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
