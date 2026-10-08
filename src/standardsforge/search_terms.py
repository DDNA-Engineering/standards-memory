"""Versioned local discovery vocabulary, never evidence or normative equivalence."""
from __future__ import annotations

POLICY = "standardsforge-engineering-discovery-v1"
# These are retrieval alternatives, not interchangeable engineering assertions.
# Every expansion is returned to the caller; exact evidence must be read next.
GROUPS = (
    ("rationale", "justification", "reason", "basis", "why"),
    ("assumption", "assumptions", "premise", "hypothesis"),
    ("tailored", "tailoring", "customized", "adapted"),
    ("criterion", "criteria"),
    ("selected", "chosen", "selection", "derived"),
    ("environmental", "environment", "ambient"),
    ("worldwide", "global", "world"),
    ("polar", "antarctic", "arctic"),
    ("excluded", "except", "exclusion", "exception"),
    ("replace", "substitute", "substitutes", "replacement"),
    ("standalone", "separately", "separate", "independent"),
    ("failure", "malfunction", "fault"),
    ("inspect", "inspection", "examine", "examination"),
    ("maximum", "upper", "ceiling"),
    ("minimum", "lower", "floor"),
    ("duration", "period", "time"),
)
_BY_TERM = {term: group for group in GROUPS for term in group}


def expand_terms(terms: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    for term in terms:
        alternatives = list(_BY_TERM.get(term.casefold(), (term,)))
        if alternatives not in groups:
            groups.append(alternatives)
    return groups
