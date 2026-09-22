from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from jsonschema.validators import validator_for


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from standardsforge.pack import validate_pack_directory, write_pack_archive  # noqa: E402


FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
BUFFER_SIZE = 1024 * 1024
ACQUISITION_SCOPE = (
    "Active MIL-STD records; current public components are leading notices plus "
    "the first substantive revision or incorporated change."
)


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
        archive_member = archive_relative.replace("\\", "/")
        payloads.append((archive, f"corpus/{archive_member}"))

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


def _load_acquisition_snapshot(path: Path, index: dict) -> tuple[dict, str]:
    acquisition = _load_json(path)
    acquisition_sha256 = _sha256(path)
    if acquisition_sha256 != index.get("acquisition_manifest_sha256"):
        raise ValueError("The acquisition manifest does not match the corpus index snapshot.")
    return acquisition, acquisition_sha256


def _validate_release_wheel(path: Path, version: str) -> str:
    expected_prefix = f"standardsforge-{version}-"
    if not path.name.startswith(expected_prefix) or path.suffix != ".whl":
        raise ValueError("The wheel filename does not match the prepared-distribution version.")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if not infos or len(names) != len(set(names)):
                raise ValueError("The release wheel is empty or contains duplicate members.")
            if any(info.date_time != FIXED_ZIP_TIME for info in infos):
                raise ValueError("The release wheel was not built with the required SOURCE_DATE_EPOCH.")
            wheel_name = next(name for name in names if name.endswith(".dist-info/WHEEL"))
            metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
            wheel_metadata = archive.read(wheel_name).decode("utf-8")
            package_metadata = archive.read(metadata_name).decode("utf-8")
    except (OSError, zipfile.BadZipFile, KeyError, StopIteration, UnicodeDecodeError) as exc:
        raise ValueError("The release wheel metadata is missing or invalid.") from exc
    generator = next(
        (line.removeprefix("Generator: ") for line in wheel_metadata.splitlines() if line.startswith("Generator: ")),
        None,
    )
    if generator != "setuptools (84.0.0)":
        raise ValueError("The release wheel was not produced by the pinned build backend.")
    if f"Version: {version}" not in package_metadata.splitlines():
        raise ValueError("The release wheel metadata version does not match the distribution.")
    return generator


def _load_wheel_provenance(path: Path, wheel: Path, version: str) -> tuple[dict, str]:
    provenance = _load_json(path)
    schema = _load_json(REPOSITORY_ROOT / "contracts" / "wheel-build-provenance.schema.json")
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    validator_class(schema).validate(provenance)
    wheel_identity = provenance["wheel"]
    if provenance["version"] != version:
        raise ValueError("The wheel provenance version does not match the distribution.")
    if (
        wheel_identity["filename"] != wheel.name
        or wheel_identity["bytes"] != wheel.stat().st_size
        or wheel_identity["sha256"] != _sha256(wheel)
    ):
        raise ValueError("The wheel does not match its build provenance.")

    required_sources = {
        "build-toolchain.lock.json",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "LICENSE",
        "src/standardsforge/__init__.py",
    }
    observed_sources: set[str] = set()
    for item in provenance["source_files"]:
        relative = item["path"]
        source = (REPOSITORY_ROOT / relative).resolve()
        try:
            source.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError as exc:
            raise ValueError("The wheel provenance contains an unsafe source path.") from exc
        if relative in observed_sources or not source.is_file():
            raise ValueError("The wheel provenance source inventory is duplicate or missing.")
        observed_sources.add(relative)
        if source.stat().st_size != item["bytes"] or _sha256(source) != item["sha256"]:
            raise ValueError(f"The wheel provenance source changed: {relative}")
    if not required_sources <= observed_sources:
        raise ValueError("The wheel provenance omits required build inputs.")
    if provenance["wheel_source_paths"] != sorted(
        observed_sources - {"build-toolchain.lock.json", "uv.lock"}
    ):
        raise ValueError("The wheel provenance misclassifies wheel source inputs.")
    if provenance["release_metadata_paths"] != ["uv.lock"]:
        raise ValueError("The wheel provenance misclassifies release metadata inputs.")
    lock_path = REPOSITORY_ROOT / "build-toolchain.lock.json"
    if provenance["build_tool"]["lock_sha256"] != _sha256(lock_path):
        raise ValueError("The wheel provenance build-tool lock changed.")
    if provenance["authentication"] != "none":
        raise ValueError("Local wheel provenance must not claim authentication.")
    return provenance, _sha256(path)


def _count(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Prepared-distribution scope count is invalid: {name}")
    return value


def _build_distribution_scope(
    acquisition: dict,
    acquisition_sha256: str,
    index: dict,
    outline: object,
) -> dict:
    acquisition_summary = acquisition.get("summary")
    corpus_summary = index.get("summary")
    if not isinstance(acquisition_summary, dict) or not isinstance(corpus_summary, dict):
        raise ValueError("The acquisition manifest and corpus index require summaries.")
    if acquisition.get("catalog_id") != "dla-active-mil-std-current":
        raise ValueError("The prepared distribution requires the active MIL-STD acquisition catalog.")
    for field in ("generated_at", "completed_at", "scope", "source", "source_origin"):
        if not isinstance(acquisition.get(field), str) or not acquisition[field]:
            raise ValueError(f"The acquisition manifest is missing {field}.")
    if acquisition["scope"] != ACQUISITION_SCOPE:
        raise ValueError("The acquisition manifest has an unexpected component-selection rule.")
    if acquisition["source_origin"] != "official_dla_assist_quick_search":
        raise ValueError("The acquisition manifest has an unexpected source origin.")
    if acquisition.get("inventory_only") is not False:
        raise ValueError("A prepared distribution requires a completed source acquisition.")

    records = acquisition.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("The acquisition manifest has no records.")
    component_status_counts = {
        "downloaded": 0,
        "restricted_distribution": 0,
        "not_publicly_exposed": 0,
        "failed": 0,
    }
    compilable_records = 0
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("The acquisition manifest contains an invalid record.")
        document_id = record.get("document_id")
        if not isinstance(document_id, str) or not document_id.startswith("MIL-STD-"):
            raise ValueError("The acquisition manifest contains a record outside the MIL-STD selection.")
        if record.get("status") != "A":
            raise ValueError("The acquisition manifest contains a record outside the active-status filter.")
        if record.get("discovery_error") is not None:
            raise ValueError("A prepared distribution cannot omit a record after discovery failure.")
        components = record.get("current_components")
        if not isinstance(components, list) or not components:
            raise ValueError("Every acquisition record must retain its selected current components.")
        has_downloaded_component = False
        for component in components:
            if not isinstance(component, dict):
                raise ValueError("The acquisition manifest contains an invalid component.")
            status = component.get("acquisition_status")
            statement = component.get("distribution_statement")
            if status not in component_status_counts:
                raise ValueError("The acquisition manifest contains an unresolved component status.")
            if status == "downloaded" and statement != "A":
                raise ValueError("A downloaded prepared-distribution component is not Statement A.")
            if status == "restricted_distribution" and statement == "A":
                raise ValueError("A Statement A component is incorrectly classified as restricted.")
            if status in {"not_publicly_exposed", "failed"} and statement != "A":
                raise ValueError("An unavailable public component has an inconsistent distribution statement.")
            component_status_counts[status] += 1
            has_downloaded_component = has_downloaded_component or status == "downloaded"
        compilable_records += int(has_downloaded_component)

    manifest_record_count = _count(corpus_summary.get("manifest_record_count"), "manifest_record_count")
    current_component_count = _count(acquisition_summary.get("current_component_count"), "current_component_count")
    downloaded_count = _count(acquisition_summary.get("downloaded_count"), "downloaded_count")
    restricted_count = _count(acquisition_summary.get("restricted_count"), "restricted_count")
    not_public_count = _count(
        acquisition_summary.get("not_publicly_exposed_count"),
        "not_publicly_exposed_count",
    )
    failed_acquisition_count = _count(acquisition_summary.get("failed_count"), "failed_count")
    if manifest_record_count != _count(acquisition_summary.get("record_count"), "record_count"):
        raise ValueError("The acquisition and corpus record counts do not match.")
    if manifest_record_count != len(records):
        raise ValueError("The acquisition summary does not match its record inventory.")
    if current_component_count != downloaded_count + restricted_count + not_public_count + failed_acquisition_count:
        raise ValueError("The acquisition component outcome counts do not close.")
    if downloaded_count != _count(corpus_summary.get("verified_pdf_count"), "verified_pdf_count"):
        raise ValueError("The downloaded component and verified PDF counts do not match.")
    if downloaded_count != _count(corpus_summary.get("compiled_component_count"), "compiled_component_count"):
        raise ValueError("The downloaded and compiled component counts do not match.")
    if component_status_counts != {
        "downloaded": downloaded_count,
        "restricted_distribution": restricted_count,
        "not_publicly_exposed": not_public_count,
        "failed": failed_acquisition_count,
    }:
        raise ValueError("The acquisition summary does not match its component inventory.")
    if compilable_records != _count(corpus_summary.get("compilable_record_count"), "compilable_record_count"):
        raise ValueError("The acquisition and corpus compilable-record counts do not match.")
    if len(records) - compilable_records != _count(
        corpus_summary.get("restricted_only_record_count"), "restricted_only_record_count"
    ):
        raise ValueError("The acquisition and corpus restricted-only counts do not match.")
    if failed_acquisition_count:
        raise ValueError("A prepared distribution requires a failure-free public acquisition.")

    outline_manifest = getattr(outline, "manifest", None)
    outline_records = getattr(outline, "records", None)
    outline_digest = getattr(outline, "package_digest", None)
    if (
        not isinstance(outline_manifest, dict)
        or outline_manifest.get("representation") != "derived_structure"
        or not isinstance(outline_records, list)
        or not outline_records
        or not isinstance(outline_digest, str)
    ):
        raise ValueError("The prepared outline must be a non-empty derived_structure pack.")
    for record in outline_records:
        derivation = record.get("derivation") if isinstance(record, dict) else None
        if not isinstance(derivation, dict) or derivation.get("review_status") != "automated_unreviewed" or derivation.get("statement_role") != "unclassified":
            raise ValueError("The prepared outline cannot claim reviewed structure or classified obligations.")
    outline_coverage = outline_manifest.get("coverage")
    qualified_scope = (
        outline_coverage.get("parsed_source_coverage")
        if isinstance(outline_coverage, dict)
        else None
    )
    if not isinstance(qualified_scope, str) or not qualified_scope:
        raise ValueError("The prepared outline must declare its qualified source scope.")

    compiled_record_count = _count(corpus_summary.get("compiled_record_count"), "compiled_record_count")
    compilation_failure_count = _count(corpus_summary.get("failed_record_count"), "failed_record_count")
    if compilation_failure_count:
        raise ValueError("A prepared distribution requires failure-free corpus compilation.")
    page_records = _count(corpus_summary.get("page_records"), "page_records")
    pages_without_text = _count(corpus_summary.get("pages_without_text_records"), "pages_without_text_records")
    scope = {
        "schema_version": "0.1.0",
        "baseline_id": f"{index['corpus_id']}:{acquisition_sha256}",
        "publisher": {
            "organization": "United States Department of Defense, Defense Logistics Agency",
            "system": "DLA ASSIST Quick Search",
            "source_url": acquisition["source"],
        },
        "acquisition": {
            "catalog_id": acquisition["catalog_id"],
            "manifest_path": "provenance/acquisition-manifest.json",
            "manifest_sha256": acquisition_sha256,
            "generated_at": acquisition["generated_at"],
            "completed_at": acquisition["completed_at"],
            "source_data_updated": acquisition.get("source_data_updated"),
        },
        "selection": {
            "document_classes": {
                "included": ["MIL-STD"],
                "excluded": [
                    "military specifications",
                    "military handbooks",
                    "commercial item descriptions",
                    "data item descriptions",
                    "drawings",
                    "other DLA document classes",
                ],
            },
            "record_statuses": {
                "included": ["active"],
                "excluded": ["inactive", "canceled", "superseded historical records"],
            },
            "components": {
                "current_only": True,
                "selection_rule": acquisition["scope"],
                "historical_editions_included": False,
            },
            "distribution_statements": {
                "included_content": ["A"],
                "unavailable_metadata_retained": True,
                "rights_effect": "provenance_only_not_operational_authorization",
            },
            "exclusions": [
                {
                    "category": "other_document_classes",
                    "reason": "The recorded acquisition selected active MIL-STD records only.",
                    "observed_count": None,
                },
                {
                    "category": "historical_editions",
                    "reason": "The acquisition selected current components and did not inventory revision history.",
                    "observed_count": None,
                },
                {
                    "category": "restricted_or_not_publicly_exposed_content",
                    "reason": "Unavailable component metadata is retained, but its bytes are not included.",
                    "observed_count": restricted_count + not_public_count,
                },
                {
                    "category": "failed_acquisitions",
                    "reason": "A failed acquisition has no included source bytes and remains explicit.",
                    "observed_count": failed_acquisition_count,
                },
                {
                    "category": "failed_compilations",
                    "reason": "A failed record compilation is not represented as successfully compiled evidence.",
                    "observed_count": compilation_failure_count,
                },
                {
                    "category": "pages_without_text_records",
                    "reason": "Preserved source pages without extracted text are not silently represented as readable text.",
                    "observed_count": pages_without_text,
                },
                {
                    "category": "document_wide_semantic_review",
                    "reason": "The prepared corpus does not include document-wide reviewed semantic interpretation.",
                    "observed_count": None,
                },
            ],
        },
        "outcomes": {
            "manifest_record_count": manifest_record_count,
            "current_component_count": current_component_count,
            "downloaded_component_count": downloaded_count,
            "restricted_component_count": restricted_count,
            "not_publicly_exposed_component_count": not_public_count,
            "failed_acquisition_component_count": failed_acquisition_count,
            "compiled_record_count": compiled_record_count,
            "compilation_failure_count": compilation_failure_count,
            "source_pdf_count": _count(corpus_summary.get("verified_pdf_count"), "verified_pdf_count"),
            "physical_page_count": _count(corpus_summary.get("physical_pages"), "physical_pages"),
            "page_record_count": page_records,
            "pages_without_text_records": pages_without_text,
        },
        "representations": {
            "page_text": {
                "included": True,
                "package_count": compiled_record_count,
                "review_status": "unreviewed",
                "statement_role": "unclassified",
                "extraction_gap_pages": pages_without_text,
            },
            "derived_outline": {
                "included": True,
                "package_digest": outline_digest,
                "record_count": len(outline_records),
                "review_status": "automated_unreviewed",
                "statement_role": "unclassified",
                "qualified_scope": qualified_scope,
            },
            "reviewed_structure": {
                "included": False,
                "review_status": "not_included",
            },
            "semantic_review": {
                "document_wide_structure_interpreted": False,
                "obligations_classified": False,
                "governing_dependencies_resolved": False,
                "human_verified": False,
                "applicability_approved": False,
            },
        },
        "limitations": {
            "publisher_currentness_is_project_baseline": False,
            "ordinary_queries_refresh_sources": False,
            "completeness_claim": "complete_only_for_the_recorded_selection_and_included_representations",
        },
    }
    schema = _load_json(REPOSITORY_ROOT / "contracts" / "distribution-scope.schema.json")
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    validator_class(schema).validate(scope)
    return scope


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


def _validate_built_distribution(archive_path: Path, prefix: str) -> None:
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("The prepared distribution contains duplicate archive members.")
        manifest_name = prefix + "bundle-manifest.json"
        try:
            manifest = json.loads(archive.read(manifest_name))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("The prepared distribution manifest is missing or invalid.") from exc
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(files, list):
            raise ValueError("The prepared distribution manifest has no file inventory.")
        manifest_schema = _load_json(REPOSITORY_ROOT / "contracts" / "prepared-distribution.schema.json")
        manifest_validator_class = validator_for(manifest_schema)
        manifest_validator_class.check_schema(manifest_schema)
        manifest_validator_class(manifest_schema).validate(manifest)
        expected_names = {manifest_name}
        for item in files:
            if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
                raise ValueError("The prepared distribution inventory is malformed.")
            relative = item["path"]
            if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
                raise ValueError("The prepared distribution inventory contains an unsafe path.")
            name = prefix + relative
            if name in expected_names:
                raise ValueError("The prepared distribution inventory contains a duplicate path.")
            expected_names.add(name)
            try:
                payload = archive.read(name)
            except KeyError as exc:
                raise ValueError(f"The prepared distribution is missing an inventoried file: {relative}") from exc
            if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise ValueError(f"The prepared distribution file failed inventory validation: {relative}")
        if set(names) != expected_names:
            raise ValueError("The prepared distribution contains unlisted or missing files.")
        wheel_items = [item for item in files if item["path"].startswith("wheel/")]
        if len(wheel_items) != 1 or wheel_items[0]["sha256"] != manifest["build"]["wheel_sha256"]:
            raise ValueError("The distribution wheel identity is inconsistent.")

        try:
            scope = json.loads(archive.read(prefix + "provenance/source-baseline.json"))
            acquisition_bytes = archive.read(prefix + "provenance/acquisition-manifest.json")
            wheel_provenance_bytes = archive.read(prefix + "provenance/wheel-build.json")
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("The prepared distribution provenance is missing or invalid.") from exc
        schema = _load_json(REPOSITORY_ROOT / "contracts" / "distribution-scope.schema.json")
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        validator_class(schema).validate(scope)
        if scope["acquisition"]["manifest_path"] != "provenance/acquisition-manifest.json":
            raise ValueError("The source baseline points to an unexpected acquisition manifest.")
        if hashlib.sha256(acquisition_bytes).hexdigest() != scope["acquisition"]["manifest_sha256"]:
            raise ValueError("The bundled acquisition manifest does not match the source baseline.")
        if hashlib.sha256(wheel_provenance_bytes).hexdigest() != manifest["build"]["wheel_provenance_sha256"]:
            raise ValueError("The bundled wheel provenance does not match the distribution manifest.")
        try:
            wheel_provenance = json.loads(wheel_provenance_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("The bundled wheel provenance is invalid.") from exc
        wheel_schema = _load_json(REPOSITORY_ROOT / "contracts" / "wheel-build-provenance.schema.json")
        wheel_validator_class = validator_for(wheel_schema)
        wheel_validator_class.check_schema(wheel_schema)
        wheel_validator_class(wheel_schema).validate(wheel_provenance)
        if wheel_provenance["wheel"]["sha256"] != manifest["build"]["wheel_sha256"]:
            raise ValueError("The bundled wheel provenance identifies a different wheel.")


def build_distribution(
    corpus_index: Path,
    acquisition_manifest: Path,
    outline_pack: Path,
    wheel: Path,
    wheel_provenance: Path,
    output: Path,
    version: str,
    compresslevel: int,
) -> dict:
    corpus_index = corpus_index.resolve()
    acquisition_manifest = acquisition_manifest.resolve()
    outline_pack = outline_pack.resolve()
    wheel = wheel.resolve()
    wheel_provenance = wheel_provenance.resolve()
    output = output.resolve()
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    if output.exists() or checksum_path.exists():
        raise ValueError(f"Output already exists: {output}")
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError(f"Expected one built wheel: {wheel}")
    wheel_generator = _validate_release_wheel(wheel, version)
    _, wheel_provenance_sha256 = _load_wheel_provenance(
        wheel_provenance, wheel, version
    )

    index, corpus_payloads = _validate_corpus(corpus_index)
    acquisition, acquisition_sha256 = _load_acquisition_snapshot(
        acquisition_manifest, index
    )
    entries = index["entries"]
    outline = validate_pack_directory(outline_pack)
    distribution_scope = _build_distribution_scope(
        acquisition, acquisition_sha256, index, outline
    )
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
        (acquisition_manifest, "provenance/acquisition-manifest.json"),
        (wheel_provenance, "provenance/wheel-build.json"),
        (corpus_index, "corpus/corpus.json"),
        (corpus_policy, "policies/mil-std-corpus-local.json"),
        (outline_policy, "policies/mil-std-810h-derived-outline-local.json"),
        (wheel, f"wheel/{wheel.name}"),
    ]
    for source, _ in static_files:
        if not source.is_file():
            raise ValueError(f"Distribution input is missing: {source}")

    with tempfile.TemporaryDirectory(prefix="standardsforge-distribution-") as temporary:
        scope_path = Path(temporary) / "source-baseline.json"
        scope_path.write_text(
            json.dumps(distribution_scope, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        outline_archive = Path(temporary) / "mil-std-810h-derived-outline.zip"
        write_pack_archive(outline_pack, outline_archive, compresslevel=compresslevel)
        payload_files = [
            *static_files,
            (scope_path, "provenance/source-baseline.json"),
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
            "source_baseline_id": distribution_scope["baseline_id"],
        }
        manifest = {
            "schema_version": "1.1",
            "product": "StandardsForge prepared distribution",
            "version": version,
            "build": {
                "archive_source_date_epoch": 1767225600,
                "archive_timestamp": "2026-01-01T00:00:00Z",
                "wheel_build_backend": "setuptools==84.0.0",
                "wheel_generator": wheel_generator,
                "wheel_sha256": _sha256(wheel),
                "wheel_provenance_sha256": wheel_provenance_sha256,
                "corpus_compiler_version": index.get("compiler_version"),
            },
            "state": distribution_summary,
            "files": file_inventory,
        }
        manifest_schema = _load_json(REPOSITORY_ROOT / "contracts" / "prepared-distribution.schema.json")
        manifest_validator_class = validator_for(manifest_schema)
        manifest_validator_class.check_schema(manifest_schema)
        manifest_validator_class(manifest_schema).validate(manifest)
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
            _validate_built_distribution(partial, prefix)
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
    parser.add_argument("--acquisition-manifest", required=True, type=Path)
    parser.add_argument("--outline-pack", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--wheel-provenance", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--compresslevel", type=int, choices=range(1, 10), default=9)
    args = parser.parse_args()
    result = build_distribution(
        args.corpus_index,
        args.acquisition_manifest,
        args.outline_pack,
        args.wheel,
        args.wheel_provenance,
        args.output,
        args.version,
        args.compresslevel,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
