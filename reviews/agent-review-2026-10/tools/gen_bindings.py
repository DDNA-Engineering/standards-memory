"""Regenerate reviews/agent-review-2026-10/reference-bindings.json from the committed annotations.

Usage: python reviews/agent-review-2026-10/tools/gen_bindings.py --corpus PATH/TO/corpus

Each binding names an exact occurrence in a reviewed source record and either a reviewed target
record in this batch or no target (unresolved). Edition choices are reviewer-selected navigation
only (independence_claim: self_review); they are not source-mandated or project-approved.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REVIEW_DIR, REVIEWED_AT, compile_reviewed, digest, record_id, write_json  # noqa: E402
from standardsforge.reference_bindings import validate_bindings  # noqa: E402

H461, H464, H704, H882, H1474, H1472 = (
    "mil-std-461h-general-requirements", "mil-std-464d-e3-general-and-emi", "mil-std-704f-general-requirements",
    "mil-std-882e-system-safety-requirements", "mil-std-1474e-noise-general-requirements", "mil-std-1472h-acoustic-noise-design")
REVIEW = {"kind": "agent", "identity": ("Claude Code agent self-review (independence_claim: self_review); same agent that authored the "
                                        "reviewed scopes; no human review or independent adjudication"),
          "reviewed_at": REVIEWED_AT}
SELECTED = "reviewer_selected_navigation_edition"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True, help="Extracted prepared corpus directory or its corpus.json")
    args = parser.parse_args()
    compiled = compile_reviewed(args.corpus)["packs"]
    records = {}
    for slug, item in compiled.items():
        annotation = item["annotation"]
        for node in annotation["nodes"]:
            records[(slug, node["logical_id"])] = {
                "package_digest": item["package_digest"], "edition_id": annotation["edition_id"],
                "record_id": record_id(annotation["edition_id"], node["logical_id"]),
                "quote_sha256": node["content_sha256"], "text": node["exact_text"]}

    def selector(slug, lid):
        record = records[(slug, lid)]
        return {key: record[key] for key in ("package_digest", "edition_id", "record_id", "quote_sha256")}

    def reference(slug, lid, needle, occurrence=0):
        text = records[(slug, lid)]["text"]
        pattern = re.compile(r"\s+".join(re.escape(part) for part in needle.split()))
        match = list(pattern.finditer(text))[occurrence]
        start = len(text[: match.start()].encode("utf-8"))
        return {"start_byte": start, "end_byte": start + len(match.group(0).encode("utf-8")), "exact_text": match.group(0)}

    bindings = []

    def add(binding_id, src, needle, target, rationale, occurrence=0):
        slug, lid = src
        binding = {"binding_id": binding_id, "source": selector(slug, lid), "reference": reference(slug, lid, needle, occurrence),
                   "target": selector(*target) if target else None, "status": "resolved" if target else "unresolved",
                   "edition_basis": SELECTED if target else "unresolved", "rationale": rationale}
        binding["review"] = dict(REVIEW, binding_sha256=digest(binding))
        bindings.append(binding)

    NO_REV = "The source cites the document without a revision letter, so the installed edition is a reviewer-selected navigation edition, not a source-mandated or project-approved edition."
    add("461h-a41-mil-std-464-first", (H461, "A.4.1/discussion-system-level-documents"), "MIL-STD-464", (H464, "1.1"),
        "Non-contractual Appendix A discussion names MIL-STD-464 as containing system-level integration requirements; navigates to the reviewed MIL-STD-464D 1.1 Purpose. " + NO_REV)
    add("461h-a41-mil-std-464-second", (H461, "A.4.1/discussion-system-level-documents"), "MIL -ST D-464", (H464, "1.1"),
        "Second occurrence in the same discussion (text layer splits it as 'MIL / -ST D-464') describing MIL-STD-464 requirement areas; navigates to the reviewed MIL-STD-464D 1.1 Purpose. " + NO_REV)
    add("461h-a41-mil-std-188-125-1", (H461, "A.4.1/discussion-system-level-documents"), "MIL-STD-188- 125-1", None,
        "MIL-STD-188-125-1 is cited without revision; the a7 corpus contains MIL-STD-188-125-1A page text but no reviewed scope, so no target record is selected.")
    add("461h-a41-mil-std-3023", (H461, "A.4.1/discussion-system-level-documents"), "MIL- STD-3023", None,
        "MIL-STD-3023 is not in the a7 MIL-STD page-text corpus; the target is unresolved.")
    add("461h-a426-mil-std-704", (H461, "A.4.2.6/discussion-system-level-transient-controls"), "MIL- STD-704", (H704, "1.1"),
        "Non-contractual Appendix A discussion of 4.2.6 states MIL-STD-704 imposes system-level transient controls; navigates to the reviewed MIL-STD-704F (with Change 1) 1.1 Scope. " + NO_REV)
    add("461h-a426-mil-std-464", (H461, "A.4.2.6/discussion-system-level-transient-controls"), "MIL-STD-464", (H464, "1.1"),
        "Same discussion states MIL-STD-464 imposes system-level transient controls; navigates to the reviewed MIL-STD-464D 1.1 Purpose. " + NO_REV)
    add("461h-a426-mil-std-1399-300-1", (H461, "A.4.2.6/discussion-system-level-transient-controls"), "MIL- STD-1399- 300- 1", None,
        "MIL-STD-1399-300-1 page text is in the a7 corpus, but no reviewed target scope exists in this batch; not bound.")
    add("461h-4.2.4-sd-2", (H461, "4.2.4"), "SD-2", None, "SD-2 guidance is not in the a7 MIL-STD page-text corpus; the target is unresolved.")
    add("464d-5.7-mil-std-461-requirements", (H464, "5.7/emi-control-requirements"), "MIL-ST D -461", (H461, "1.1"),
        "Example citation ('such as ... requirements of MIL-STD-461') of subsystem and equipment interface control requirements; navigates to the reviewed MIL-STD-461H 1.1 Purpose. " + NO_REV)
    add("464d-5.7-mil-std-461-verification", (H464, "5.7/verification"), "MIL-STD-461", (H461, "4.3"),
        "Example citation ('such as testing in accordance with MIL-STD-461') in the verification directive; navigates to the reviewed MIL-STD-461H 4.3 Verification requirements. " + NO_REV)
    add("464d-5.7.1-mil-std-461-safety-critical", (H464, "5.7.1/minimum-emi-requirements"), "MIL-ST D -461", (H461, "1.1"),
        "Safety-critical PED requirements cite emissions and susceptibility requirements 'such as those defined in MIL-STD-461'; navigates to the reviewed MIL-STD-461H 1.1 Purpose. " + NO_REV)
    add("464d-5.7.1-mil-std-461-non-safety-critical", (H464, "5.7.1/minimum-emi-requirements"), "MIL - STD-461", (H461, "1.1"),
        "Non-safety-critical PED requirements cite emissions requirements 'such as those defined in MIL-STD-461' (text layer splits the identifier across lines); navigates to the reviewed MIL-STD-461H 1.1 Purpose. " + NO_REV)
    add("464d-5.7.1-mil-std-461-ce106", (H464, "5.7.1/transmitter-emissions"), "MIL-STD-461 Test Method CE106", None,
        "The reference is to a specific test method (CE106); MIL-STD-461H is installed but its CE106 method is outside every reviewed scope, so no target record is selected.")
    add("464d-5.6-mil-std-2169", (H464, "5.6/operational-after-emp"), "MIL-STD -2169", None,
        "MIL-STD-2169 is cited without revision as defining a classified environment; the a7 corpus contains MIL-STD-2169D page text but no reviewed scope; not bound.")
    add("464d-5.7.3-dod-std-1399-070-1", (H464, "5.7.3/not-degraded"), "DOD-STD-1399- 070-1 (NAVY)", None,
        "DOD-STD-1399-070-1 is not in the a7 MIL-STD page-text corpus; the target is unresolved.")
    add("704f-1.1-mil-hdbk-704", (H704, "1.1"), "M IL-HD BK-704-1 through- 8", None,
        "MIL-HDBK-704-1 through -8 are handbooks not in the a7 MIL-STD page-text corpus; the target is unresolved.")
    add("882e-4.3.7-dodi-5000", (H882, "4.3.7/accept-before-exposure"), "DoDI 5000 s eries", None,
        "The DoDI 5000 series is DoD instruction policy, not in the a7 MIL-STD page-text corpus; the risk acceptance authority target is unresolved.")
    add("1474e-4.1-mil-std-882", (H1474, "4.1"), "MIL-STD-882", (H882, "4.3.4"),
        "4.1 requires procurement using 'the design order of precedence in MIL-STD-882'; navigates to the reviewed MIL-STD-882E (with Change 1) 4.3.4 record that introduces the system safety design order of precedence (steps 4.3.4.a through e are separate records). " + NO_REV)
    add("1474e-4.2.2-mil-hdbk-1473", (H1474, "4.2.2/sign-conformance"), "MIL-HDBK-1473", None,
        "MIL-HDBK-1473 is a handbook not in the a7 MIL-STD page-text corpus; the target is unresolved.")
    add("1472h-5.5.4.2-mil-std-1474", (H1472, "5.5.4.2"), "MIL-ST D-1474", (H1474, "1.1"),
        "Equipment noise limits 'in accordance with MIL-STD-1474'; navigates to the reviewed MIL-STD-1474E 1.1 Scope. " + NO_REV)
    add("1472h-5.5.4.3-mil-std-1474", (H1472, "5.5.4.3/total-system-noise"), "MIL-STD-1474", (H1474, "4.1.1"),
        "Total system noise 'in accordance with MIL-STD-1474'; navigates to the reviewed MIL-STD-1474E 4.1.1 Total system noise. " + NO_REV)
    add("1472h-5.5.4.4.1-mil-std-1474", (H1472, "5.5.4.4.1"), "MI L-ST D-1474", (H1474, "4.2.1"),
        "Environments at or above 85 dBA / 140 dBP are evaluated 'in accordance with MIL-STD-1474'; navigates to the reviewed MIL-STD-1474E 4.2.1 Protection from hazardous noise. " + NO_REV)
    add("1472h-1.3-jssg-2010", (H1472, "1.3"), "JSSG-2010", None,
        "JSSG-2010 is a joint service specification guide not in the a7 MIL-STD page-text corpus; the target is unresolved.")

    body = {"binding_set_id": "agent-review-2026-10-reference-bindings", "bindings": bindings, "scope": "reviewed_navigation_only",
            "project_applicability": "not_decided"}
    document = {"schema_version": "0.1.0", "binding_set": body, "binding_set_sha256": digest(body)}
    validate_bindings(document)
    write_json(REVIEW_DIR / "reference-bindings.json", document, indent=1)
    print(len(bindings), "bindings;", sum(b["status"] == "resolved" for b in bindings), "resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
