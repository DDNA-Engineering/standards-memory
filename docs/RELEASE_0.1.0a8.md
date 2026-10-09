# StandardsForge v0.1.0a8 release candidate

Status: **prepared, not published.** No tag, GitHub release, PyPI upload or native acceptance run exists for 0.1.0a8 yet. This page records what changed and what was observed locally; the publication section lists what must still happen.

## What changes for people installing it

- **Stray files no longer block setup.** Files that macOS Finder and Windows Explorer create on their own (`.DS_Store`, `._*`, `Thumbs.db`, `ehthumbs.db`, `desktop.ini`) are ignored. Any other missing or unexpected file is now named in the error, with what to do. Every other inventory check is unchanged.
- **Windows offline setup works with Python 3.11, 3.12 or 3.13.** One wheelhouse carries a hash lock per version; `setup.cmd` uses whichever supported 64-bit Python it finds.
- **Token budgets work in the prepared library.** The archive bundles the pinned `o200k_base` tokenizer and installs `tiktoken` with the model connection, so `select_evidence` with `max_tokens` works offline. A changed tokenizer file stops the server from starting.
- **Optional automatic host setup.** `--connect claude-desktop`, `--connect cursor` or `--connect codex` adds the StandardsForge entry after a byte-exact backup, changing nothing else, and refuses files it cannot rewrite safely. Without it, setup never touches host settings.
- **Disk space is checked first.** First setup stops before indexing if the drive lacks room, and states how much is needed (about 4 GB in total including the download).
- **Reviewed cross-standard navigation works in the prepared library.** The launcher passes 23 bundled, hash-pinned reviewed references; `follow_references` returns their exact targets.

## Content

447 packages. The 441-package source baseline of a6 and a7 is unchanged: 438 acquisition-pinned page-text packs (912 verified PDFs, 35,218 page-text records across 35,235 physical pages), the automated MIL-STD-810H `outline-v3` and two MIL-STD-1661 recovery packs.

New: six agent-reviewed packs for bounded requirement sections of MIL-STD-882E, 461H, 464D, 704F, 1474E and 1472H, with 232 records (123 obligation records, 139 typed qualifiers) and 23 reviewed cross-standard references (12 resolved, 11 recorded as unresolved). They link 40,830 of the 7,289,021 extracted text bytes in those six source packages. They are **agent self-review** of extracted page text (`independence_claim: self_review`): not human or independent review, visual PDF validation, applicability, compliance or approval. Each pack carries its own real-document suite; setup replays 294 cases in total (52 existing and 242 new). Details, scope and method: [agent review 2026-10](AGENT_REVIEW_2026-10.md).

## Local candidate identities

<!-- filled from the final local build -->

## Observed validation

<!-- filled from the final local build -->

## Publication steps (maintainer)

1. Merge this change after CI passes on its pull request.
2. Rebuild the prepared archive with `scripts/rebuild_prepared_release.py` from the published a7 archive (see [maintainer workflows](wiki/MAINTAINER_WORKFLOWS.md#rebuild-from-the-previous-prepared-release)), or attach the locally built candidate after confirming its SHA-256.
3. Create the `v0.1.0a8` draft release with the ZIP and its `.sha256`, then run **Accept prepared distribution** with `allow_draft: true`. It now covers Windows with Python 3.11, 3.12 and 3.13, shell metadata files during setup, and a token-budgeted evidence selection through the generated launcher.
4. Publish the release, tag and run the PyPI workflow, then record the observed identities here.

## Known limitations

- Native Windows and macOS behaviour of these changes has not yet been observed; only Linux was exercised locally.
- Claude Desktop installed from the Microsoft Store keeps its settings in a different folder; use `--host-config` with that file.
- Reviewed content remains bounded. Corpus-wide semantic review, independent (non-agent) adjudication, applicability and approval remain open.
