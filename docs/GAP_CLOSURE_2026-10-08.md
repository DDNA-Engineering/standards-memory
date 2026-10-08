# Knowledge access gap closure — 2026-10-08

Status: local, uncommitted, unpublished source changes after a6. The released a6 artifacts remain unchanged. Usage is documented in [knowledge access and compression](KNOWLEDGE_ACCESS.md).

## Implemented and observed

| Gap | Result | Evidence boundary |
|---|---|---|
| No complete structural navigation | `browse_records` exposes all records, roots, children, parents, adjacency and typed incoming/outgoing links through library, CLI and MCP. | Exact package pin; signed pagination; source verification; reauthorization; no query-time database writes. |
| Only one broadly structured standard | Outline compiler 0.4.0 generated 438 separate `outline-v4` packages containing **203,698 records**. Every record was installed and traversed; every package also passed an exact evidence read. Restarting the corpus compiler reused and revalidated all 438 outputs. | Entire base acquisition corpus; automated, unreviewed structure. Original source packages and previously released outlines remain intact. |
| Whole-corpus compiler failures | Fixed case/punctuation collisions in logical identities and added records 0.3.0 with exact structural byte offsets. | Six initial failures reduced to zero. MIL-STD-3031B's 14,772-record JSON fits in 27,972,513 bytes, below the unchanged 32 MiB limit. No source text was discarded. |
| Repeated span-file reads | Pack validation reuses already-read evidence bytes within one validation call. | No cache survives the call. Hash, UTF-8, exact quote, relationship and graph checks remain. One local validation of the 14,772-record outline took approximately 0.8 seconds; no general latency SLO is asserted. |
| Paraphrases absent from literal search | Explicit `concept_language` discloses its fixed local alternatives and distinct-concept ranking. | Existing lexical modes retain behavior. Across ten existing diagnostic questions, either natural or concept search found the known target in the first ten results for nine questions, versus seven previously. This is two explicit query modes, not an independently judged recall or answer-quality benchmark. |
| Byte-only response measurements | `select_evidence` chooses the smallest of three lossless profiles using a host-pinned local BPE tokenizer, or exact bytes when no tokenizer is configured. | Across 48 existing exact-read cases with `o200k_base`: **190,692 → 165,584 tokens** for canonical successful JSON responses including the selection envelope, a **13.2% reduction**. Nested evidence alone fell **18.6%**. Tool schemas, host formatting and model chat framing are excluded. |
| Repeated files across packs | Data-only content bundles store exact file blobs once and use LZMA for text when smaller than Deflate. All 441 original package identities reconstructed and validated. | For the same 441-pack content set: **1,060,421,845 → 1,009,446,904 bytes**, a **4.8% reduction**. Deduplication removes 54,159,018 raw duplicate bytes. Installed object files remain independent copies. |

## Verification

- 211 unit/integration tests ran: 209 passed and two Linux-only venv-alias tests were skipped on Windows.
- Machine-contract validation passed, including the new navigation, evidence selection, tokenizer, bundle and structural-record schemas.
- All 52 existing real-document regression cases passed: 810H outline, 1661 transcription and 1661 semantic evidence.
- All eight synthetic benchmark cases passed offline.
- The final wheel was built twice with identical bytes, installed outside the checkout without extras, and passed core read/doctor smoke checks. SHA-256: `318987ac9838193edb9b23f891a23c7d1974b4765e17262c6654c995026e0950`.
- The synthetic starter passed fresh and repeated installation with the final wheel. This local test wheel still carries the checkout's a6 version; it is not the published a6 wheel and must not replace that immutable release.
- The complete 441-package content bundle installed successfully in a fresh isolated store and on repeat (288.0 seconds and 241.5 seconds locally). All 52 real-document regressions passed against that installed bundle.

Local raw evidence is retained under `build/knowledge-audit-2026-10-08/`: `outline-v4-runtime-qualification.json`, `corpus-outlines-v4/outlines.json`, `content-bundle-report.json`, `final-access-measurements.json`, the three `final-mil-std-*.json` regressions, contract/test logs and wheel/starter provenance. These generated local artifacts are not committed source or public release artifacts.

## Remaining qualification

These changes do **not** establish corpus-wide semantic completeness. The new outlines remain unclassified. Subsequent local work adds 31 reviewed records across four more standards, exact reviewed cross-standard navigation, and a 12-question human answer-review packet; see [review and reference qualification](REVIEW_AND_REFERENCE_QUALIFICATION.md). Tables, figures, cross-page conditions and exceptions still require broader source-level review. Unresolved references are not silently promoted. The wheel and 211-test results above describe the earlier compression/navigation snapshot, not these subsequent changes.

Independent held-out questions and reviewed model answers are still needed to establish broad retrieval/answer quality. No exhaustive codec or retrieval comparison establishes global optimality. Native CI and publication of these source changes have not occurred.
