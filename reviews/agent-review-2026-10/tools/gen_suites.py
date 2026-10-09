"""Regenerate benchmarks/real/<slug>.json from the committed review annotations.

Usage: python reviews/agent-review-2026-10/tools/gen_suites.py --corpus PATH/TO/corpus

Expectations derive only from the reviewed annotations (exact text digests, typed semantics,
declared required relationships) and the compiled package digest; they are not copied from
query output. They remain same-agent assertions (independence_claim: self_review).
"""
from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ORDER, REVIEWED_AT, SUITES_DIR, compile_reviewed, digest, record_id, write_json  # noqa: E402

IDENTITY = ("Claude Code agent self-review (independence_claim: self_review): the same agent authored the review annotations and "
            "these expectations from them; no human review or independent adjudication")

SEARCHES = {
    "mil-std-461h-general-requirements": [("search-navy-only-filtering", "Navy only filtering", ["4.2.2"]),
                                          ("search-manual-switching-exemption", "manually actuated switching exempt", ["4.2.6"])],
    "mil-std-464d-e3-general-and-emi": [("search-safety-critical-margin", "margins safety critical", ["5.1/minimum-safety-margin"]),
                                        ("search-emp-invoked", "invoked procuring activity", ["5.6/operational-after-emp"])],
    "mil-std-704f-general-requirements": [("search-half-wave", "rectified", ["4.2.4/no-half-wave-rectification"]),
                                          ("search-spikes-not-covered", "voltage spikes covered", ["4.2.1"])],
    "mil-std-882e-system-safety-requirements": [("search-serious-high-concurrence", "formal concurrence Serious High", ["4.3.7/user-concurrence-serious-high"]),
                                                ("search-level-f", "doctrine training warning", ["4.3.3.b"])],
    "mil-std-1474e-noise-general-requirements": [("search-combat-exteriors", "exteriors military combat equipment", ["4.2.2"]),
                                                 ("search-solely-relied", "solely relied", ["4.2.1/no-sole-reliance-on-protectors"])],
    "mil-std-1472h-acoustic-noise-design": [("search-earplugs", "earplugs", ["5.5.4.4.3.4.2"]),
                                            ("search-crew-system-conflict", "aircraft design conflict crew", ["1.3"])],
}


def build_suite(slug: str, annotation: dict, package_digest: str) -> dict:
    edition, pdf = annotation["edition_id"], annotation["source_pdf_sha256"]
    nodes = {n["logical_id"]: n for n in annotation["nodes"]}
    order = [n["logical_id"] for n in sorted(annotation["nodes"], key=lambda n: (n["ordinal"], n["logical_id"]))]
    edges: dict[str, list[str]] = {}
    for relationship in annotation["relationships"]:
        if relationship["target_status"] == "resolved" and relationship["required"]:
            edges.setdefault(relationship["source_logical_id"], []).append(relationship["target_logical_id"])

    def rid(lid):
        return record_id(edition, lid)

    def closure(root):
        seen, queue = [], deque([root])
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.append(current)
            queue.extend(edges.get(current, []))
        return seen

    def citation(lid):
        node = nodes[lid]
        return {"record_id": rid(lid), "page": node["source_spans"][0]["physical_page"], "source_sha256": pdf,
                "quote_sha256": node["content_sha256"]}

    def assertion(lid):
        semantics = nodes[lid]["semantics"]
        return {"record_id": rid(lid), "content_role": semantics["content_role"], "statement": semantics["statement"],
                "qualifiers": semantics["qualifiers"]}

    def facts(lid):
        semantics = nodes[lid].get("semantics") or {}
        out = [q["exact_text"] for q in semantics.get("qualifiers", [])
               if q["kind"] in {"exception", "condition", "source_applicability", "tailoring_instruction", "acceptance_criterion"}]
        if semantics.get("statement"):
            out.append(semantics["statement"]["exact_text"])
        if not out:
            out.append(nodes[lid]["exact_text"].split("\n")[-1])
        return list(dict.fromkeys(out))

    obligations = [lid for lid in order if nodes[lid]["statement_role"] == "obligation"]
    cases = []
    for lid in order:
        semantics = nodes[lid].get("semantics")
        if not semantics or (semantics["statement"] is None and not semantics["qualifiers"]):
            continue
        members = closure(lid)
        parent = nodes[lid].get("parent_logical_id")
        siblings = [o for o in order if o not in members and nodes[o].get("parent_logical_id") == parent and o != lid]
        if not siblings:
            siblings = [o for o in obligations if o not in members]
        cases.append({"case_id": f"review-{lid}", "operation": "get_clause", "request": {"record_id": rid(lid)},
                      "expected": {"record_ids": [rid(m) for m in members], "forbidden_record_ids": [rid(o) for o in siblings[:2]],
                                   "citations": [citation(m) for m in members], "critical_facts": facts(lid),
                                   "complete_for_requested_scope": False,
                                   "semantic_assertions": [assertion(m) for m in members if nodes[m].get("semantics")]}})
    # Scoped enumeration of every clause with two or more obligation descendants.
    for lid in order:
        cref = nodes[lid]["clause_reference"]
        scoped = [o for o in obligations if nodes[o]["clause_reference"] == cref or nodes[o]["clause_reference"].startswith(cref + ".")]
        if len(scoped) < 2 or len(scoped) > 100:
            continue
        in_closure = {m for o in scoped for m in closure(o)}
        outside = [o for o in obligations if o not in in_closure]
        cases.append({"case_id": f"enumerate-{cref}", "operation": "enumerate_obligations", "request": {"scope_prefix": cref, "limit": 100},
                      "expected": {"record_ids": [rid(o) for o in scoped], "forbidden_record_ids": [rid(o) for o in outside[:3] if o not in scoped],
                                   "citations": [citation(o) for o in scoped], "critical_facts": [], "complete_for_requested_scope": False,
                                   "semantic_assertions": [assertion(o) for o in scoped]}})
    for case_id, query, targets in SEARCHES[slug]:
        cases.append({"case_id": case_id, "operation": "search", "request": {"query": query, "query_mode": "all_terms", "limit": 20},
                      "expected": {"record_ids": [rid(t) for t in targets], "forbidden_record_ids": [],
                                   "citations": [citation(t) for t in targets], "critical_facts": [], "complete_for_requested_scope": None}})
    suite = {"suite_id": f"{slug}-agent-self-review-2026-10", "qualification": "bounded_real_document_regression",
             "package_digest": package_digest, "edition_id": edition, "cases": cases}
    return {"suite": suite, "review": {"kind": "agent", "identity": IDENTITY, "reviewed_at": REVIEWED_AT, "suite_sha256": digest(suite)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True, help="Extracted prepared corpus directory or its corpus.json")
    args = parser.parse_args()
    compiled = compile_reviewed(args.corpus)["packs"]
    for slug in ORDER:
        document = build_suite(slug, compiled[slug]["annotation"], compiled[slug]["package_digest"])
        write_json(SUITES_DIR / f"{slug}.json", document, indent=1)
        cases = document["suite"]["cases"]
        print(slug, len(cases), "cases", sum(len(c["expected"]["record_ids"]) for c in cases), "expected records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
