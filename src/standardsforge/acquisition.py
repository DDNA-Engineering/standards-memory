from __future__ import annotations

import hashlib
import html
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .errors import StandardsForgeError, require


QUICK_SEARCH_URL = "https://quicksearch.dla.mil/qsSearch.aspx"
DETAIL_URL = "https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number={ident_number}"
IMAGE_URL = "https://quicksearch.dla.mil/ImageRedirector.aspx?token={token}"
_USER_AGENT = "Mozilla/5.0 (compatible; StandardsForge/0.1; official-public-document-acquisition)"
_TOKEN = re.compile(r"ImageRedirector\.aspx\?token=(\d+\.\d+)", re.IGNORECASE)
_IDENT = re.compile(r"ident_number=(\d+)", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _clean_text(value: str) -> str:
    return _SPACE.sub(" ", html.unescape(value)).strip()


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        name = values.get("name", "")
        input_type = values.get("type", "text").lower()
        if name and input_type not in {"submit", "reset", "button", "image", "checkbox", "radio", "file"}:
            self.fields[name] = values.get("value", "")


class _TableParser(HTMLParser):
    def __init__(self, table_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.rows: list[dict[str, Any]] = []
        self._table_depth = 0
        self._target_depth: int | None = None
        self._row: dict[str, Any] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if name == "table":
            self._table_depth += 1
            if values.get("id") == self.table_id:
                self._target_depth = self._table_depth
            return
        if self._target_depth is None:
            return
        if name == "tr" and self._row is None:
            self._row = {"cells": [], "links": []}
        elif name in {"td", "th"} and self._row is not None:
            self._cell = []
        elif name == "a" and self._row is not None:
            href = values.get("href")
            if href:
                self._row["links"].append(href)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if self._target_depth is not None and name in {"td", "th"} and self._cell is not None:
            assert self._row is not None
            self._row["cells"].append(_clean_text("".join(self._cell)))
            self._cell = None
        elif self._target_depth is not None and name == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None
        if name == "table":
            if self._target_depth == self._table_depth:
                self._target_depth = None
            self._table_depth -= 1


def _form_fields(document: str) -> dict[str, str]:
    parser = _FormParser()
    parser.feed(document)
    return parser.fields


def _table_rows(document: str, table_id: str) -> list[dict[str, Any]]:
    parser = _TableParser(table_id)
    parser.feed(document)
    return parser.rows


def _iso_date(value: str) -> str | None:
    for pattern in ("%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.title(), pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _declared_bytes(value: str) -> int | None:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB|B)", value.strip(), re.IGNORECASE)
    if not match:
        return None
    multiplier = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}[match.group(2).upper()]
    return round(float(match.group(1)) * multiplier)


def _safe_name(value: str, *, maximum: int = 72) -> str:
    cleaned = _UNSAFE_FILENAME.sub("_", value).strip("._-")
    return (cleaned or "document")[:maximum]


@dataclass
class _HttpClient:
    delay_seconds: float
    retries: int = 4

    def __post_init__(self) -> None:
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._last_request = 0.0

    def _throttle(self) -> None:
        remaining = self.delay_seconds - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)

    def open(self, url: str, *, data: bytes | None = None, referer: str | None = None):
        headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8"}
        if referer:
            headers["Referer"] = referer
        for attempt in range(self.retries):
            self._throttle()
            try:
                response = self._opener.open(Request(url, data=data, headers=headers), timeout=90)
                self._last_request = time.monotonic()
                return response
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                self._last_request = time.monotonic()
                if attempt + 1 == self.retries:
                    raise StandardsForgeError(
                        "source_request_failed",
                        "The official DLA source did not complete a request after bounded retries.",
                        {"url": url, "reason": type(exc).__name__},
                    ) from exc
                time.sleep(min(2**attempt, 8))
        raise AssertionError("unreachable")

    def text(self, url: str, *, fields: dict[str, str] | None = None, referer: str | None = None) -> str:
        data = urlencode(fields).encode("ascii") if fields is not None else None
        with self.open(url, data=data, referer=referer) as response:
            payload = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")


def _parse_search_rows(document: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in _table_rows(document, "GV"):
        cells = row["cells"]
        if len(cells) != 6:
            continue
        ident_number = None
        for href in row["links"]:
            match = _IDENT.search(href)
            if match:
                ident_number = match.group(1)
                break
        if not ident_number or not cells[1].upper().startswith("MIL-STD-"):
            continue
        records.append(
            {
                "ident_number": ident_number,
                "document_id": cells[1],
                "status": cells[2],
                "fsc_area": cells[3],
                "document_date": _iso_date(cells[4]),
                "title": cells[5],
                "detail_url": DETAIL_URL.format(ident_number=ident_number),
            }
        )
    return records


def _discover_records(client: _HttpClient) -> tuple[list[dict[str, Any]], str | None]:
    initial = client.text(QUICK_SEARCH_URL)
    updated_match = re.search(r"Data updated:\s*([^<.]+)", initial, re.IGNORECASE)
    data_updated = _iso_date(_clean_text(updated_match.group(1))) if updated_match else None
    fields = _form_fields(initial)
    fields.update(
        {
            "DocumentIDTextBox": "MIL-STD-",
            "IDNumberTextBox": "",
            "DropDownListStatus": "1",
            "DocumentTitleKeyWords": "",
            "DropDownListContains": "AND",
            "DropDownListTitleOrKeywords": "TOS",
            "GetFilteredButton": "Search",
        }
    )
    page = client.text(QUICK_SEARCH_URL, fields=fields, referer=QUICK_SEARCH_URL)
    total_match = re.search(r"Total records:\s*([0-9,]+)", page, re.IGNORECASE)
    require(total_match is not None, "source_index_changed", "DLA Quick Search did not return a recognizable result count.")
    expected = int(total_match.group(1).replace(",", ""))
    records = _parse_search_rows(page)
    while len(records) < expected:
        fields = _form_fields(page)
        fields.update(
            {
                "DocumentIDTextBox": "MIL-STD-",
                "DropDownListStatus": "1",
                "DropDownListContains": "AND",
                "DropDownListTitleOrKeywords": "TOS",
                "btnNextEx.x": "5",
                "btnNextEx.y": "5",
            }
        )
        next_page = client.text(QUICK_SEARCH_URL, fields=fields, referer=QUICK_SEARCH_URL)
        next_records = _parse_search_rows(next_page)
        require(next_records, "source_index_changed", "DLA Quick Search paging returned no document records.")
        require(
            next_records[0]["ident_number"] != records[-len(next_records)]["ident_number"] if len(records) >= len(next_records) else True,
            "source_index_changed",
            "DLA Quick Search paging did not advance.",
        )
        records.extend(next_records)
        page = next_page
    require(
        len(records) == expected and len({item["ident_number"] for item in records}) == expected,
        "source_index_changed",
        "DLA Quick Search result closure did not match the declared active-record count.",
        expected=expected,
        actual=len(records),
    )
    return records, data_updated


def _parse_current_components(document: str, ident_number: str) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for row in _table_rows(document, "GVRevisionHistory"):
        cells = row["cells"]
        if len(cells) != 6:
            continue
        if cells[1].casefold() == "document part description" or cells[2].casefold() == "dist stmt":
            continue
        token = None
        for href in row["links"]:
            match = _TOKEN.search(href)
            if match:
                token = match.group(1)
                break
        description = cells[1]
        component = {
            "description": description,
            "distribution_statement": cells[2],
            "document_date": _iso_date(cells[3]),
            "page_count": int(cells[4]) if cells[4].isdigit() else None,
            "declared_size": cells[5],
            "declared_bytes": _declared_bytes(cells[5]),
            "token": token,
            "source_url": IMAGE_URL.format(token=token) if token else None,
        }
        history.append(component)
    if not history:
        return []

    current: list[dict[str, Any]] = []
    for component in history:
        current.append(component)
        if "notice" not in component["description"].casefold():
            break
    for component in current:
        token_prefix = (component["token"] or "no-token").split(".", 1)[0]
        filename = "__".join(
            (
                _safe_name(component["description"], maximum=64),
                component["document_date"] or "unknown-date",
                token_prefix,
            )
        ) + ".pdf"
        component["local_path"] = f"{ident_number}/{filename}"
        if component["distribution_statement"] != "A":
            component["acquisition_status"] = "restricted_distribution"
        elif not component["token"]:
            component["acquisition_status"] = "not_publicly_exposed"
        else:
            component["acquisition_status"] = "pending"
        component["sha256"] = None
        component["byte_length"] = None
        component["error"] = None
    return current


def _load_prior_components(manifest_path: Path) -> dict[str, dict[str, Any]]:
    if not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    prior: dict[str, dict[str, Any]] = {}
    for record in manifest.get("records", []):
        for component in record.get("current_components", []):
            token = component.get("token")
            if isinstance(token, str):
                prior[token] = component
    return prior


def _load_reusable_inventory(manifest_path: Path) -> dict[str, Any] | None:
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    records = manifest.get("records")
    if (
        manifest.get("catalog_id") != "dla-active-mil-std-current"
        or not isinstance(records, list)
        or not records
        or any(record.get("discovery_error") for record in records)
    ):
        return None
    return manifest


def _checkpoint(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _download_component(
    client: _HttpClient,
    component: dict[str, Any],
    output_root: Path,
    detail_url: str,
) -> None:
    relative = Path(component["local_path"])
    target = output_root / relative
    require(
        target.resolve().is_relative_to(output_root.resolve()),
        "invalid_source_path",
        "A resolved acquisition path escaped the configured output root.",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    length = 0
    try:
        redirector_url = component["source_url"]
        public_token = component["token"].split(".", 1)[0]
        download_url = f"https://quicksearch.dla.mil/WMX/Default.aspx?token={public_token}"
        response = client.open(download_url, referer=redirector_url)
        try:
            with temporary.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
                    digest.update(chunk)
                    length += len(chunk)
        finally:
            response.close()
        with temporary.open("rb") as stream:
            signature = stream.read(5)
        require(signature == b"%PDF-", "source_not_public_pdf", "The DLA image endpoint did not return a public PDF.")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    component["sha256"] = digest.hexdigest()
    component["byte_length"] = length
    component["acquisition_status"] = "downloaded"


def _restore_download(component: dict[str, Any], prior: dict[str, Any] | None, output_root: Path) -> bool:
    if not prior or prior.get("acquisition_status") != "downloaded":
        return False
    path = output_root / component["local_path"]
    if not path.is_file() or not isinstance(prior.get("byte_length"), int) or path.stat().st_size != prior["byte_length"]:
        return False
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    if digest != prior.get("sha256"):
        return False
    component["sha256"] = digest
    component["byte_length"] = prior["byte_length"]
    component["acquisition_status"] = "downloaded"
    return True


def _summarize(manifest: dict[str, Any]) -> dict[str, Any]:
    components = [component for record in manifest["records"] for component in record["current_components"]]
    downloaded = [item for item in components if item["acquisition_status"] == "downloaded"]
    failed = [item for item in components if item["acquisition_status"] == "failed"]
    restricted = [item for item in components if item["acquisition_status"] == "restricted_distribution"]
    unavailable = [item for item in components if item["acquisition_status"] == "not_publicly_exposed"]
    return {
        "record_count": len(manifest["records"]),
        "current_component_count": len(components),
        "estimated_public_bytes": sum(item["declared_bytes"] or 0 for item in components if item["distribution_statement"] == "A"),
        "downloaded_count": len(downloaded),
        "downloaded_bytes": sum(item["byte_length"] or 0 for item in downloaded),
        "failed_count": len(failed),
        "restricted_count": len(restricted),
        "not_publicly_exposed_count": len(unavailable),
    }


def acquire_active_mil_stds(
    output_root: str | Path,
    *,
    manifest_path: str | Path | None = None,
    inventory_only: bool = False,
    reuse_inventory: bool = False,
    delay_seconds: float = 0.2,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    require(delay_seconds >= 0, "invalid_acquisition_option", "delay_seconds cannot be negative.")
    root = Path(output_root)
    manifest_file = Path(manifest_path) if manifest_path is not None else root / "manifest.json"
    prior = _load_prior_components(manifest_file)
    client = _HttpClient(delay_seconds=delay_seconds)
    emit = progress or (lambda _: None)

    reusable = _load_reusable_inventory(manifest_file) if reuse_inventory else None
    if reusable is None:
        emit("Discovering active MIL-STD records from DLA Quick Search...")
        records, data_updated = _discover_records(client)
    else:
        emit("Reusing the completed DLA inventory checkpoint...")
        records = reusable["records"]
        data_updated = reusable.get("source_data_updated")
        if data_updated is None:
            index_document = client.text(QUICK_SEARCH_URL)
            updated_match = re.search(r"Data updated:\s*([^<.]+)", index_document, re.IGNORECASE)
            data_updated = _iso_date(_clean_text(updated_match.group(1))) if updated_match else None
    manifest: dict[str, Any] = {
        "schema_version": "0.1.0",
        "catalog_id": "dla-active-mil-std-current",
        "scope": "Active MIL-STD records; current public components are leading notices plus the first substantive revision or incorporated change.",
        "source": QUICK_SEARCH_URL,
        "source_origin": "official_dla_assist_quick_search",
        "source_data_updated": data_updated,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "inventory_only": inventory_only,
        "records": [],
        "summary": {},
    }
    root.mkdir(parents=True, exist_ok=True)
    _checkpoint(manifest_file, manifest)

    if reusable is None:
        for index, record in enumerate(records, start=1):
            try:
                detail = client.text(record["detail_url"], referer=QUICK_SEARCH_URL)
                record["current_components"] = _parse_current_components(detail, record["ident_number"])
                record["discovery_error"] = None
            except StandardsForgeError as exc:
                record["current_components"] = []
                record["discovery_error"] = exc.code
            manifest["records"].append(record)
            if index % 25 == 0 or index == len(records):
                emit(f"Inventoried {index}/{len(records)} active MIL-STD records")
                manifest["summary"] = _summarize(manifest)
                _checkpoint(manifest_file, manifest)
    else:
        for record in records:
            for component in record["current_components"]:
                component["error"] = None
                if component["distribution_statement"] != "A":
                    component["acquisition_status"] = "restricted_distribution"
                elif not component["token"]:
                    component["acquisition_status"] = "not_publicly_exposed"
                else:
                    component["acquisition_status"] = "pending"
            manifest["records"].append(record)
        manifest["summary"] = _summarize(manifest)
        _checkpoint(manifest_file, manifest)

    if not inventory_only:
        components = [
            (record, component)
            for record in manifest["records"]
            for component in record["current_components"]
            if component["acquisition_status"] == "pending"
        ]
        for index, (record, component) in enumerate(components, start=1):
            restored = _restore_download(component, prior.get(component["token"]), root)
            if not restored:
                try:
                    _download_component(client, component, root, record["detail_url"])
                except StandardsForgeError as exc:
                    component["acquisition_status"] = "failed"
                    component["error"] = exc.code
            if index % 10 == 0 or index == len(components):
                emit(f"Acquired {index}/{len(components)} public current components")
            if not restored or index % 10 == 0 or index == len(components):
                manifest["summary"] = _summarize(manifest)
                _checkpoint(manifest_file, manifest)

    manifest["summary"] = _summarize(manifest)
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _checkpoint(manifest_file, manifest)
    return {**manifest["summary"], "manifest": str(manifest_file), "output_root": str(root)}


def verify_mil_std_acquisition(manifest_path: str | Path, output_root: str | Path) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    root = Path(output_root)
    require(manifest_file.is_file(), "acquisition_manifest_not_found", "The acquisition manifest does not exist.")
    require(root.is_dir(), "source_root_not_found", "The acquisition output root does not exist.")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StandardsForgeError("invalid_acquisition_manifest", "The acquisition manifest is not valid UTF-8 JSON.") from exc
    require(
        manifest.get("catalog_id") == "dla-active-mil-std-current" and isinstance(manifest.get("records"), list),
        "invalid_acquisition_manifest",
        "The acquisition manifest has an unsupported identity or shape.",
    )

    verified = 0
    verified_bytes = 0
    restricted = 0
    errors: list[dict[str, Any]] = []
    expected_paths: set[str] = set()
    resolved_root = root.resolve()
    for record in manifest["records"]:
        for component in record.get("current_components", []):
            status = component.get("acquisition_status")
            distribution_statement = component.get("distribution_statement")
            if status == "restricted_distribution":
                if distribution_statement == "A":
                    errors.append(
                        {
                            "token": component.get("token"),
                            "error": "public_component_marked_restricted",
                        }
                    )
                restricted += 1
                continue
            if status != "downloaded":
                errors.append({"token": component.get("token"), "error": f"unexpected_status:{status}"})
                continue
            if distribution_statement != "A":
                errors.append(
                    {
                        "token": component.get("token"),
                        "error": "downloaded_non_public_distribution",
                    }
                )
                continue
            relative = component.get("local_path")
            if not isinstance(relative, str):
                errors.append({"token": component.get("token"), "error": "missing_local_path"})
                continue
            path = root / relative
            expected_paths.add(Path(relative).as_posix())
            try:
                require(path.resolve().is_relative_to(resolved_root), "invalid_source_path", "A manifest path escaped the output root.")
                require(path.is_file() and not path.is_symlink(), "source_file_missing", "A downloaded component is missing or not a regular file.")
                require(path.stat().st_size == component.get("byte_length"), "source_size_mismatch", "A downloaded component byte count does not match.")
                hasher = hashlib.sha256()
                with path.open("rb") as stream:
                    require(stream.read(5) == b"%PDF-", "invalid_source_format", "A downloaded component is not a PDF.")
                    stream.seek(0)
                    while chunk := stream.read(1024 * 1024):
                        hasher.update(chunk)
                require(hasher.hexdigest() == component.get("sha256"), "source_hash_mismatch", "A downloaded component digest does not match.")
            except StandardsForgeError as exc:
                errors.append({"token": component.get("token"), "path": relative, "error": exc.code})
                continue
            verified += 1
            verified_bytes += path.stat().st_size

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.pdf")
        if path.is_file() and not path.is_symlink()
    }
    unexpected = sorted(actual_paths - expected_paths)
    require(
        not errors and not unexpected,
        "acquisition_verification_failed",
        "The acquired MIL-STD collection did not close against its manifest.",
        errors=errors[:25],
        unexpected=unexpected[:25],
    )
    return {
        "record_count": len(manifest["records"]),
        "verified_pdf_count": verified,
        "verified_bytes": verified_bytes,
        "restricted_component_count": restricted,
        "unexpected_pdf_count": 0,
        "verified_dimensions": ["path_containment", "regular_file", "pdf_signature", "byte_length", "sha256", "directory_closure"],
    }
