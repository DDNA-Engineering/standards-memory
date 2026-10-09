"""Data-only content-addressed transport; installed packs remain independent."""
from __future__ import annotations

import hashlib
import json
import lzma
import os
import re
import stat
import tempfile
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import StandardsForgeError, require
from .pack import (MAX_FILES, MAX_JSON_BYTES, MAX_TOTAL_BYTES, _safe_relative_path,
                   iter_zip_member, open_validated_pack, validate_pack_directory)

FORMAT = "standardsforge-content-bundle-v1"
_DIGEST = re.compile(r"[a-f0-9]{64}")
_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_LZMA}


def _member_chunks(archive: zipfile.ZipFile, name: str, limit: int) -> Iterator[bytes]:
    return iter_zip_member(archive, archive.getinfo(name), limit=limit, methods=_METHODS,
                           limit_code="bundle_limit_exceeded", invalid_code="invalid_bundle")


def _info(name: str, method: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = method
    info._compresslevel = 9
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_bundle(sources: list[str | Path], destination: str | Path) -> dict[str, Any]:
    require(0 < len(sources) <= 5000, "invalid_bundle", "A bundle requires 1 through 5000 explicit local packs.")
    output = Path(destination).resolve()
    require(not output.exists(), "bundle_exists", "Bundle output already exists.")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".bundle-", suffix=".zip", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    packs, blobs, identities = [], {}, set()
    logical_bytes, methods = 0, {"deflate": 0, "lzma": 0}
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            for source in sources:
                with open_validated_pack(source) as pack:
                    require(pack.package_digest not in identities, "invalid_bundle", "Duplicate package identity.")
                    identities.add(pack.package_digest)
                    files = []
                    for relative in sorted(["inventory.json", *(e.path for e in pack.inventory)]):
                        data = (pack.root / relative).read_bytes()
                        digest = hashlib.sha256(data).hexdigest()
                        files.append({"path": relative, "sha256": digest, "bytes": len(data)})
                        logical_bytes += len(data)
                        if digest in blobs:
                            continue
                        method = zipfile.ZIP_DEFLATED
                        if Path(relative).suffix in {".json", ".txt", ".md"}:
                            if len(lzma.compress(data, preset=6)) + 32 < len(zlib.compress(data, 9)):
                                method = zipfile.ZIP_LZMA
                        archive.writestr(_info("blobs/" + digest, method), data)
                        blobs[digest] = len(data)
                        methods["lzma" if method == zipfile.ZIP_LZMA else "deflate"] += 1
                    packs.append({"package_digest": pack.package_digest, "pack_id": pack.manifest["pack_id"], "files": files})
            manifest = {"schema_version": "0.1.0", "format": FORMAT,
                        "packs": sorted(packs, key=lambda p: p["package_digest"])}
            encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
            require(len(encoded) <= MAX_JSON_BYTES, "bundle_limit_exceeded", "Bundle manifest exceeds its size bound.")
            archive.writestr(_info("bundle.json", zipfile.ZIP_DEFLATED), encoded)
        verified = verify_bundle(temporary)
        # Existing source packages and public distributions are never overwritten.
        with temporary.open("rb") as reader, output.open("xb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
        with output.open("rb") as reader:
            output_digest = hashlib.file_digest(reader, "sha256").hexdigest()
        return {"operation": "bundle_packs", "path": str(output), "bundle_bytes": output.stat().st_size,
                "bundle_sha256": output_digest,
                "packages": verified["packages"], "unique_blobs": len(blobs),
                "logical_file_bytes": logical_bytes, "unique_file_bytes": sum(blobs.values()),
                "deduplicated_file_bytes": logical_bytes - sum(blobs.values()), "compression_methods": methods}
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _open(source: str | Path) -> Iterator[tuple[zipfile.ZipFile, dict[str, Any]]]:
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            require(1 <= len(infos) <= 250001, "bundle_limit_exceeded", "Bundle member count exceeds its bound.")
            names = [info.filename for info in infos]
            require(len(names) == len(set(names)), "invalid_bundle", "Duplicate bundle members.")
            names = set(names)
            for info in infos:
                require(info.filename == "bundle.json" or re.fullmatch(r"blobs/[a-f0-9]{64}", info.filename) is not None,
                        "invalid_bundle", "Unsafe bundle member path.")
                require(not stat.S_ISLNK(info.external_attr >> 16) and not info.flag_bits & 1 and info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_LZMA},
                        "invalid_bundle", "Unsupported bundle member.")
                require(info.file_size <= MAX_TOTAL_BYTES, "bundle_limit_exceeded", "Bundle blob exceeds pack limits.")
            require("bundle.json" in names and archive.getinfo("bundle.json").file_size <= MAX_JSON_BYTES,
                    "invalid_bundle", "Missing or oversized bundle manifest.")
            manifest = json.loads(b"".join(_member_chunks(archive, "bundle.json", MAX_JSON_BYTES)))
            require(isinstance(manifest, dict) and set(manifest) == {"schema_version", "format", "packs"}
                    and manifest["schema_version"] == "0.1.0" and manifest["format"] == FORMAT,
                    "invalid_bundle", "Unsupported bundle manifest.")
            packs = manifest["packs"]
            require(isinstance(packs, list) and 0 < len(packs) <= 5000, "invalid_bundle", "Invalid package count.")
            needed, identities = {"bundle.json"}, set()
            for pack in packs:
                require(isinstance(pack, dict) and set(pack) == {"package_digest", "pack_id", "files"}, "invalid_bundle", "Invalid package entry.")
                digest = pack["package_digest"]
                require(isinstance(digest, str) and _DIGEST.fullmatch(digest) is not None and digest not in identities,
                        "invalid_bundle", "Invalid or duplicate package identity.")
                identities.add(digest)
                require(isinstance(pack["pack_id"], str) and bool(pack["pack_id"]), "invalid_bundle", "Invalid pack ID.")
                files = pack["files"]
                require(isinstance(files, list) and 1 <= len(files) <= MAX_FILES + 1, "invalid_bundle", "Invalid package file count.")
                paths, total = set(), 0
                for entry in files:
                    require(isinstance(entry, dict) and set(entry) == {"path", "sha256", "bytes"}, "invalid_bundle", "Invalid file entry.")
                    relative = _safe_relative_path(entry["path"]).as_posix()
                    require(relative not in paths, "invalid_bundle", "Duplicate package path.")
                    paths.add(relative)
                    digest = entry["sha256"]
                    require(isinstance(digest, str) and _DIGEST.fullmatch(digest) is not None
                            and type(entry["bytes"]) is int and entry["bytes"] >= 0, "invalid_bundle", "Invalid blob identity.")
                    member = "blobs/" + digest
                    needed.add(member)
                    require(member in names and archive.getinfo(member).file_size == entry["bytes"], "invalid_bundle", "Missing blob or wrong size.")
                    total += entry["bytes"]
                require("inventory.json" in paths and total <= MAX_TOTAL_BYTES + MAX_JSON_BYTES, "bundle_limit_exceeded", "Invalid reconstructed package size.")
            require(set(names) == needed, "invalid_bundle", "Bundle inventory is not closed.")
            yield archive, manifest
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, lzma.LZMAError) as exc:
        raise StandardsForgeError("invalid_bundle", "Bundle could not be read or verified.") from exc


@contextmanager
def _materialize(archive: zipfile.ZipFile, entry: dict[str, Any]) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="standardsforge-bundle-pack-") as temporary:
        root = Path(temporary)
        for file in entry["files"]:
            # Join the validated parts, never the raw manifest string.
            target = root.joinpath(*_safe_relative_path(file["path"]).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, count = hashlib.sha256(), 0
            with target.open("xb") as writer:
                for chunk in _member_chunks(archive, "blobs/" + file["sha256"], file["bytes"]):
                    count += len(chunk)
                    digest.update(chunk)
                    writer.write(chunk)
            require(count == file["bytes"] and digest.hexdigest() == file["sha256"], "invalid_bundle", "Blob digest or size mismatch.")
        pack = validate_pack_directory(root)
        require(pack.package_digest == entry["package_digest"] and pack.manifest["pack_id"] == entry["pack_id"],
                "invalid_bundle", "Reconstructed package identity changed.")
        yield root


def verify_bundle(source: str | Path) -> dict[str, Any]:
    with _open(source) as (archive, manifest):
        for entry in manifest["packs"]:
            with _materialize(archive, entry):
                pass
        return {"operation": "verify_bundle", "status": "verified", "packages": len(manifest["packs"]),
                "package_digests": [p["package_digest"] for p in manifest["packs"]]}


def install_bundle(source: str | Path, service: Any, policy_path: str | Path) -> dict[str, Any]:
    from .policy import authorize_install, load_policy
    policy = load_policy(policy_path)
    installed = []
    # Preflight every package and local grant before any database mutation.
    with _open(source) as (archive, manifest):
        for entry in manifest["packs"]:
            with _materialize(archive, entry) as root:
                authorize_install(policy, validate_pack_directory(root))
        for entry in manifest["packs"]:
            with _materialize(archive, entry) as root:
                installed.append(service.install_pack(root, policy_path))
    return {"operation": "install_bundle", "packages": len(installed), "installed": installed}
