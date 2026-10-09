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

Built 2026-10-09 on Linux (CPython 3.13) with `scripts/rebuild_prepared_release.py` from the published a7 archive (SHA-256 `8555fcafa683c60186575193c7cc504331ca6d49c5d64b76bda431b83b1bda9b`) and the reviewed supplement. Two independent rebuilds produced the same bytes. These are local candidate identities, not published assets; re-record them if anything is rebuilt.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `standardsforge-ready-0.1.0a8.zip` | 1,129,980,850 | `1202166c12754adb22ac8182a4e905001ad4effc0f8636653db921ab8935ef87` |
| `standardsforge-0.1.0a8-py3-none-any.whl` (embedded) | 217,923 | `bef6391ba4cb8d568d383431062ed3ee60d4ae39328f737fbd75603d0209e92c` |
| `tokenizer/o200k_base.json` | 4,414,372 | `6c41d106375d7d241ee4fef5775478e49263a1719f5b9e623b4fd75cc8178dd2` |
| `references/reference-bindings.json` | — | `051f756fec1c4a2542fc67275b084aeb687eda396265330314d41f377ef776d3` |

The manifest inventories 984 files, including 49 wheels in the shared Windows wheelhouse (inventory digest `dca8398b258206318ba0a5b97cd0be539e5fd55b292e74cb7820ade80463f8da`). Lock digests: CPython 3.11 `d211224eaf2916f93d979b7a0446f97188c1011e602548c9418a7e13816f0d37`, 3.12 `b6bf2e4df78a1874ab2679adf280f1980bf36a23a7a9c11384e9c7cb7c4b40fb`, 3.13 `df3ba015b56a9f93b19340907ea501d47cfdf3b4c0feab783178d70097c59d0f`. Reviewed package digests are listed in [agent review 2026-10](AGENT_REVIEW_2026-10.md).

## Observed validation

All of the following ran locally on Linux x86_64 with CPython 3.13 on 2026-10-09. Nothing here is native Windows or macOS evidence.

- 368 unit and integration tests passed; contract validation passed (64 schema documents, 56 requirements, 30 validated instances).
- The core wheel built twice byte-identically and passed the installed-wheel smoke outside the checkout.
- The rebuild re-ran every real-document suite against the new wheel in a fresh environment and store: 52 existing and 242 new cases, all passing.
- Installation of the exact candidate archive into a path containing spaces and `ü`, with `.DS_Store` and `._setup.py` present, using `sh setup.sh --mcp-online --connect cursor --connect codex`: ready in 139 s, including full-integrity doctor, all 294 cases, and an MCP smoke over stdio that made a token-budgeted `select_evidence` call and followed a bundled reviewed reference to its target. Cursor's file was created; Codex's existing `config.toml` kept its other settings and was backed up byte for byte. A repeat run reported `already_ready` and `already_connected` in 39 s.
- An earlier build, which differed only in the blank line `--connect codex` leaves before its table, also passed with a Cursor connect and a Codex update of an existing a7 entry. There, `select-evidence --max-tokens 2000` through `run.py` measured all three profiles in `o200k_base` tokens, and `follow-references` from MIL-STD-1474E 4.1 returned MIL-STD-882E 4.3.4. An added `my-notes.txt` was rejected with its name.
- Installed footprint: 1.13 GB extracted, 1.81 GB index and object store, 0.08 GB environment.
- Not observed: native Windows (any Python version), macOS, the offline Windows MCP locks, Claude Desktop configuration, CI on this branch, and publication.

## Publication steps (maintainer)

1. Merge this change after CI passes on its pull request.
2. Rebuild the prepared archive with `scripts/rebuild_prepared_release.py` from the published a7 archive (see [maintainer workflows](wiki/MAINTAINER_WORKFLOWS.md#rebuild-from-the-previous-prepared-release)), or attach the locally built candidate after confirming its SHA-256.
3. Create the `v0.1.0a8` draft release with the ZIP and its `.sha256`, then run **Accept prepared distribution** with `allow_draft: true`. It now covers Windows with Python 3.11, 3.12 and 3.13, shell metadata files during setup, and a token-budgeted evidence selection through the generated launcher.
4. Publish the release, tag and run the PyPI workflow, then record the observed identities here.

## Known limitations

- Native Windows and macOS behaviour of these changes has not yet been observed; only Linux was exercised locally.
- Claude Desktop installed from the Microsoft Store keeps its settings in a different folder; use `--host-config` with that file.
- Reviewed content remains bounded. Corpus-wide semantic review, independent (non-agent) adjudication, applicability and approval remain open.
