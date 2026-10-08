"""Render retrieved detailed MCP evidence as a portable, script-free source sheet.

This host-side formatter does not query a store, authorize a user, or verify a PDF.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
from typing import Any


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def words(value: Any) -> str:
    if value is None:
        return "Not established"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value).replace("_", " ")


def packets_from(value: Any) -> list[dict[str, Any]]:
    values = value if isinstance(value, list) else [value]
    packets = []
    for item in values:
        if isinstance(item, dict) and "ok" in item:
            if item["ok"] is not True:
                raise ValueError("A failed tool response is not source evidence.")
            item = item.get("result")
        if (not isinstance(item, dict) or item.get("schema_version") != "0.1.0"
                or item.get("operation") not in {"get_clause", "build_context"}
                or "response_profile" in item):
            raise ValueError("Use detailed get_clause/build_context results; omit response_profile when retrieving.")
        if not item.get("evidence") or not isinstance(item.get("completeness"), dict):
            raise ValueError("Source evidence and coverage information are required.")
        for record in item["evidence"]:
            text = record["text"]
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != record["citation"]["quote_sha256"]:
                raise ValueError("Evidence text does not match its recorded quote digest.")
        packets.append(item)
    if not packets:
        raise ValueError("At least one evidence packet is required.")
    return packets


def coverage_html(packet: dict[str, Any]) -> str:
    coverage = packet["completeness"]
    dimensions = coverage.get("dimensions", {})
    rows = [
        ("Complete for requested scope", coverage.get("complete_for_requested_scope")),
        ("Source interpretation", dimensions.get("source_interpretation", {}).get("status")),
        ("Required context identified", dimensions.get("required_dependencies", {}).get("identification_status")),
        ("Required context retrieved", dimensions.get("required_dependencies", {}).get("retrieval_status", coverage.get("dependency_closure"))),
    ]
    return '<dl class="coverage">' + "".join(
        f"<div><dt>{escape(label)}</dt><dd>{escape(words(value))}</dd></div>" for label, value in rows
    ) + "</dl>"


def load_previews(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Read an explicit host-produced PNG mapping; never locate or render source PDFs."""
    previews = {}
    for entry in json.loads(path.read_text(encoding="utf-8-sig")):
        key = (entry["package_digest"], entry["record_id"])
        if key in previews:
            raise ValueError("Duplicate page preview selector.")
        png = (path.parent / entry["png_path"]).read_bytes()
        if not png.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(png).hexdigest() != entry["png_sha256"]:
            raise ValueError("Page preview must be a PNG matching its host-recorded digest.")
        previews[key] = {**entry, "data_url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}
    return previews


def render(value: Any, title: str = "StandardsForge source evidence", previews: dict | None = None) -> str:
    packets = packets_from(value)
    previews = previews or {}
    used_previews = set()
    cards = []
    navigation = []
    for number, packet in enumerate(packets, 1):
        package = packet["package"]
        identifier = package["identifier"]
        pages = ", ".join(str(record["citation"]["page"]) for record in packet["evidence"])
        navigation.append(f'<a href="#source-{number}">{escape(identifier)} · p. {escape(pages)}</a>')
        records = []
        for index, record in enumerate(packet["evidence"]):
            citation = record["citation"]
            clause = record["clause_reference"]
            page_label = "Physical PDF page" if citation["source_path"].lower().endswith(".pdf") else "Source page"
            location = f"{page_label} {citation['page']}"
            if record.get("kind") != "page" and not clause.startswith("pdf-component:"):
                location = f"{clause} · {location}"
            role = "Source passage"
            if packet["operation"] == "get_clause" and index:
                role = "Governing context"
            review = words(record.get("derivation", {}).get("review_status"))
            passage = f'<blockquote class="quote">{escape(record["text"])}</blockquote>'
            key = (package["package_digest"], record["record_id"])
            if key in previews:
                preview = previews[key]
                if preview["source_sha256"] != citation["source_sha256"] or preview["page"] != citation["page"]:
                    raise ValueError("Page preview does not match the cited source and physical page.")
                if not preview["data_url"].startswith("data:image/png;base64,"):
                    raise ValueError("Page previews must be embedded PNG images.")
                used_previews.add(key)
                passage = (
                    f'<figure><img class="page-preview" src="{escape(preview["data_url"])}" '
                    f'alt="{escape(identifier)} — physical PDF page {escape(citation["page"])}">'
                    '<figcaption>Original page preview rendered by the host from the cited local PDF.</figcaption></figure>'
                    '<details class="transcript"><summary>Read extracted text</summary>' + passage + '</details>'
                )
            records.append(
                f'<article class="passage"><p class="eyebrow">{role} · {escape(location)}</p>'
                f'<h3>{escape(record["heading"])}</h3>'
                f'<p class="review">Semantic review: {escape(review)}</p>'
                + passage + '</article>'
            )
        limitations = "".join(f"<li>{escape(text)}</li>" for text in packet["limitations"])
        # Keep the entire original packet, including full pins and relationships, in one closed disclosure.
        audit = escape(json.dumps(packet, indent=2, ensure_ascii=False))
        cards.append(
            f'<section id="source-{number}" class="source"><header><p class="eyebrow">Source {number}</p>'
            f'<h2>{escape(identifier)}</h2><p>{escape(package["title"])}</p></header>'
            + "".join(records)
            + '<aside><h3>What this evidence establishes</h3>' + coverage_html(packet)
            + f'<ul>{limitations}</ul><p>Source checks and review states are reported from the retrieved packet. '
              'This saved sheet does not reauthorize access or reverify the original source files.</p></aside>'
            + f'<details class="audit"><summary>Technical audit details</summary><pre>{audit}</pre></details></section>'
        )
    if set(previews) != used_previews:
        raise ValueError("A page preview has no matching evidence record.")
    return "".join([
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
        f'<title>{escape(title)}</title>',
        '<style>body{margin:0;background:#f1f4f6;color:#172a3b;font:16px/1.6 system-ui,sans-serif}'
        'main{max-width:1000px;margin:auto;padding:36px 24px}h1,h2,h3{line-height:1.2}h1{font-size:36px}'
        'h2{font-size:28px;margin:4px 0}h3{font-size:18px}.eyebrow{font-size:12px;letter-spacing:.07em;'
        'text-transform:uppercase;color:#486576;font-weight:700}.intro{margin-bottom:28px}'
        'nav{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}nav a{color:#174d70;background:white;'
        'border:1px solid #cedae2;border-radius:5px;padding:7px 12px;text-decoration:none}'
        '.source{background:white;border:1px solid #d5dfe6;border-radius:10px;margin:24px 0;overflow:hidden}'
        '.source>header{padding:24px 28px;background:#edf4f8;border-bottom:1px solid #d5dfe6}'
        '.passage{padding:12px 28px}.review{font-size:13px;color:#536570}'
        'figure{margin:16px 0}.page-preview{display:block;width:100%;height:auto;border:1px solid #d5dfe6}'
        'figcaption{font-size:12px;color:#536570;margin-top:8px}.transcript{margin:16px 0}'
        '.quote{margin:16px 0 24px;padding:18px 22px;border-left:3px solid #bd6a32;'
        'background:#fcfaf7;white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.7 Georgia,serif}'
        'aside{margin:8px 28px 24px;padding:18px;background:#f4f7f9;font-size:14px}'
        '.coverage{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}'
        '.coverage dt{color:#536570}.coverage dd{margin:0;font-weight:600}'
        '.audit{border-top:1px solid #d5dfe6;padding:16px 28px;color:#536570}'
        'summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}'
        '@media print{body{background:white}nav,.audit{display:none}main{padding:0}.source{break-inside:auto}}'
        '</style></head><body><main><div class="intro"><p class="eyebrow">StandardsForge · Source sheet</p>',
        f'<h1>{escape(title)}</h1>',
        '<p>Read the retrieved passages and their governing context below. Edition labels and physical PDF '
        'pages identify the sources; technical verification details are available beneath each source.</p>'
        '<p>These are source passages, not a decision about which standards or test limits your project must use. '
        'Extracted text retains its original spacing and extraction defects.</p></div><nav>',
        "".join(navigation), '</nav>', "".join(cards), '</main></body></html>',
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="One detailed packet/envelope or a JSON array of them")
    parser.add_argument("output", type=Path, help="New HTML source sheet to create")
    parser.add_argument("--title", default="StandardsForge source evidence")
    parser.add_argument("--page-images", type=Path, help="Optional explicit host-rendered PNG mapping; see the skill instructions")
    args = parser.parse_args()
    try:
        previews = load_previews(args.page_images) if args.page_images else None
        document = render(json.loads(args.input.read_text(encoding="utf-8-sig")), args.title, previews)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(document)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Could not render evidence: {error}\n")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
