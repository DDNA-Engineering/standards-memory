from __future__ import annotations

import argparse
import importlib.metadata
import re
from pathlib import Path


LOCK_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+) --hash=sha256:[0-9a-f]{64}$"
)


def _normalize(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _load_expected(path: Path, standardsforge_version: str) -> dict[str, str]:
    expected = {"standardsforge": standardsforge_version}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LOCK_PATTERN.fullmatch(line)
        if match is None:
            raise RuntimeError("The MCP requirements lock contains a malformed entry.")
        name = _normalize(match.group("name"))
        if name in expected:
            raise RuntimeError("The MCP requirements lock contains a duplicate package.")
        expected[name] = match.group("version")
    return expected


def verify_environment(
    requirements: Path,
    standardsforge_version: str,
    installed: list[tuple[str, str]] | None = None,
) -> None:
    expected = _load_expected(requirements, standardsforge_version)
    observed: dict[str, str] = {}
    records = installed
    if records is None:
        records = [
            (distribution.metadata["Name"], distribution.version)
            for distribution in importlib.metadata.distributions()
        ]
    for raw_name, version in records:
        name = _normalize(raw_name)
        if not name or name in observed:
            raise RuntimeError("The prepared environment contains an invalid or duplicate package identity.")
        observed[name] = version
    missing_or_wrong = {
        name: (version, observed.get(name))
        for name, version in expected.items()
        if observed.get(name) != version
    }
    extras = sorted(set(observed) - set(expected) - {"pip"})
    if missing_or_wrong or extras:
        raise RuntimeError(
            f"The prepared environment differs from its exact runtime lock; "
            f"missing_or_wrong={missing_or_wrong!r}; extras={extras!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument("--standardsforge-version", required=True)
    args = parser.parse_args()
    verify_environment(args.requirements, args.standardsforge_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
