# StandardsForge v0.1.0a7 release evidence

Published October 8, 2026 from source commit `0ece9507325cbcf9cf9a97ce35e360637400f93d`, tagged `v0.1.0a7`.

## Install

Download the [prepared library](https://github.com/DDNA-Engineering/standards-memory/releases/tag/v0.1.0a7) and extract it into a permanent folder. Windows x64 CPython 3.12 users double-click `setup.cmd`. Linux/macOS users with Python 3.11+ run `sh setup.sh --mcp-online`. Both paths generate absolute host configuration after a real stdio query. Core-only `python setup.py` remains offline; only the explicit online MCP option resolves dependencies over the network.

The [PyPI code package](https://pypi.org/project/standardsforge/0.1.0a7/) installs with `python -m pip install "standardsforge==0.1.0a7"`. It contains code only. See the [quickstart](../README.md#install-and-connect-your-model) for platform prerequisites and model host configuration.

## Changes

One portable setup implementation replaces the duplicate Windows installation path. Setup validates bundle ownership, source identity and installed evidence before readiness; failed inventory or runtime revalidation invalidates the old ready receipt. CLI and MCP launchers no longer perform implicit installation. The MCP launcher validates bundle-bound readiness and accepts no caller overrides.

The runtime includes eleven read-only operations, including structural browsing, measured evidence selection, reviewed-reference navigation and original source PDF delivery. Query paths retain local authorization and source verification. In the prepared distribution, reviewed-reference navigation and token budgets are unavailable without further host configuration; see [known limitations](#known-limitations).

## Published identities

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `standardsforge-ready-0.1.0a7.zip` | 1,080,468,608 | `8555fcafa683c60186575193c7cc504331ca6d49c5d64b76bda431b83b1bda9b` |
| `standardsforge-0.1.0a7-py3-none-any.whl` | 206,227 | `d9f05d03ac09e55c87ea9a0ba265edd62420de439229c5d0ff53223406c19d37` |
| `standardsforge-0.1.0a7.tar.gz` | 311,537 | `2852ab536d56c114780be93bcc7cd356e2b14e9d6396035564ecc9cb173ec7c1` |

The prepared archive embeds the exact Linux-built PyPI wheel and its source/build provenance. Two independent prepared builds produced identical bytes. Local Windows-built wheels were qualification artifacts and are not the published wheel above.

## Observed validation

- [Source CI and release attestation](https://github.com/DDNA-Engineering/standards-memory/actions/runs/37847186582): successful on the tagged source. The full 242-test suite passed on Windows and Linux under Python 3.11/3.12, with the expected Windows platform skips; portable-core checks passed on Intel and Apple silicon macOS. Contracts, the offline synthetic benchmark, reproducible wheel, installed core, starter and release evidence checks passed. The published wheel's signed CycloneDX SBOM also passed `gh attestation verify --repo DDNA-Engineering/standards-memory --predicate-type https://cyclonedx.org/bom`.
- [Prepared native acceptance](https://github.com/DDNA-Engineering/standards-memory/actions/runs/37847176631): the exact draft archive and checksum passed first/repeated core and MCP setup on Windows, Ubuntu, Intel macOS and Apple silicon macOS. Paths contained spaces and non-ASCII text. Windows used the offline wheelhouse; POSIX used the explicit online dependency path. Each runner exercised the actual generated host launcher, eleven-tool inventory, real stdio search, full-integrity doctor, exact resolution and source evidence retrieval before publication.
- [PyPI trusted publication](https://github.com/DDNA-Engineering/standards-memory/actions/runs/37848239191): tagged wheel and sdist, eight native installed-wheel checks, then successful OIDC publication with attestations.
- Real-document qualification: all 52 runtime-bound cases passed, covering 11 outline, 18 transcription and 23 semantic/context cases (137 expected record occurrences). Setup replays those suites before readiness.
- Local prepared acceptance: a fresh Windows installation and repeat installation passed. The generated JSON and TOML agreed; a client using that actual launcher observed 441 packages and all eleven tools, retrieved exact source evidence and independently hashed the PDF returned by `get_source_pdfs`.
- Public readback: the ZIP and checksum downloaded anonymously and matched the recorded identity. The wheel downloaded from PyPI matched the bundled wheel exactly. A fresh environment outside the source import path successfully ran both the CLI module and installed console command and confirmed version `0.1.0a7`.

## Content and remaining limits

The prepared content baseline is unchanged from a6: 438 acquisition-pinned page packs from 912 PDFs (35,218 page-text records across 35,235 physical pages), the automated 8,319-record MIL-STD-810H outline-v3 and two bounded MIL-STD-1661 recovery packs, totaling 441 packages. Additional representations preserve the same original source documents.

This remains an alpha release. Upgrading the runtime does not add outline-v4 or establish corpus-wide semantic review, visual completeness, applicability, compliance or independent human approval. The broader source-bound semantic review task remains open. Historical edition selection, restricted components and unresolved context remain explicit in the evidence.

## Known limitations

Recorded 2026-10-09 after publication. The published identities and observed validation above are unchanged.

- The prepared MCP launcher (`run_mcp.py`) starts the server with only its database, object store, principal and result mode. It passes no `--reference-bindings` or `--tokenizer-*` options and accepts no overrides, and the archive contains no reviewed reference-binding artifact. In a prepared installation, `follow_references` therefore returns `reference_bindings_not_configured`; reviewed-reference navigation needs a separately configured source or PyPI runtime with a trusted, digest-pinned binding artifact. No reviewed binding artifact is published.
- In the same installation, `select_evidence` works with byte budgets or no budget, but a `max_tokens` budget returns `tokenizer_unavailable`. Neither setup profile installs the optional `tokens` extra, and no tokenizer artifact is bundled.
- Both error codes were observed on 2026-10-09 through the CLI of the exact release source (`0ece950`), started without binding or tokenizer options, against the fictional example pack. They were not separately exercised through the extracted prepared archive or its MCP launcher. The release acceptance above exercised the eleven-tool inventory, search, resolution, evidence retrieval and `get_source_pdfs`, not `follow_references` or token-budget selection.
