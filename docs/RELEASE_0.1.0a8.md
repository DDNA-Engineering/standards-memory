# StandardsForge v0.1.0a8 release candidate

Status: **prepared, not published.** No tag, GitHub release, PyPI upload or native acceptance run exists for 0.1.0a8 yet. This page records what changed and what was observed locally; the publication section lists what must still happen.

## What changes for people installing it

- **Stray files no longer block setup.** Files that macOS Finder and Windows Explorer create on their own (`.DS_Store`, `._*`, `Thumbs.db`, `ehthumbs.db`, `desktop.ini`) are ignored. Any other missing or unexpected file is now named in the error, with what to do. Every other inventory check is unchanged.
- **Windows offline setup works with Python 3.11, 3.12 or 3.13.** One wheelhouse carries a hash lock per version; `setup.cmd` uses whichever supported 64-bit Python it finds.
- **Token budgets work in the prepared library.** The archive bundles the pinned `o200k_base` tokenizer and installs `tiktoken` with the model connection, so `select_evidence` with `max_tokens` works offline. A changed tokenizer file stops the server from starting.
- **Optional automatic host setup.** `--connect claude-desktop`, `--connect cursor` or `--connect codex` adds the StandardsForge entry after a byte-exact backup, changing nothing else, and refuses files it cannot rewrite safely. Without it, setup never touches host settings.
- **Disk space is checked first.** First setup stops before indexing if the drive lacks room, and states how much is needed (about 4 GB in total including the download).

## Content

<!-- filled after the reviewed supplement is integrated -->

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
