# October 8 gap-closure evidence

This work fixes the two reproduced runtime defects and prepares a current-source release candidate. Full-corpus semantic and visual qualification is not complete. No commit or publication was performed.

| Original finding | Result |
|---|---|
| Edition comparison skips unchanged source verification | Fixed. Every before/after record is source-verified; corruption in either unchanged edition fails. Response shape stays compatible. |
| CLI/MCP query startup creates or migrates state | Fixed. Queries open SQLite read-only and reject missing or incompatible state without mutation. Administrative installation retains migration. |
| Comprehensive engineering-requirement extraction | Still open. Exact page/text coverage and reviewer disposition tooling now make the missing work explicit; they do not infer or approve semantic records. |
| No executable real-document quality gate | Partially closed. Eleven agent-reviewed 810H source-text cases pass, with exact runtime-source binding, raw results, and independently recomputed gates. Full-corpus recall and visual fidelity remain unmeasured. |
| Prepared release trails current source | Local candidate prepared with outline-v3 and qualification evidence. Public publication and native hosted CI remain outstanding. |

## Verification

- Full suite: 190 tests, two platform skips, no failures in the latest completed full run.
- Eight synthetic benchmark cases pass.
- Eleven real 810H cases pass, finding all ten explicitly expected record occurrences across exact retrieval and discovery. This denominator describes those selected cases only.
- All 438 package ledgers, their corpus manifest, and the real regression run pass their schemas.
- Corpus accounting: 35,235 physical pages; 35,218 page records; 159,752,989 extracted UTF-8 bytes awaiting disposition. The 17 pages without extracted text are all in the 18-page MIL-STD-1661 package `51261c722ce6458dbc3e8af1053d38416b1184d1d824655a1da9c15f400e9c48`.
- The separate compiler-0.4 rebuild remains incomplete at 437 packs because MIL-STD-1661 raises `pdf_page_extraction_failed` on page 2. The candidate preserves the verified 438-pack compiler-0.3 snapshot and its explicit fidelity limits; no failure was converted into successful extraction.
- The current 810H outline reproduces package `ff9824bb1adf8b55d53bd6f409294c012dd12479003796fc9637294fbb049e35`, with 8,319 automated, unreviewed records and 2,787 unsupported regions.
- The final core wheel built twice byte-identically and installed outside the checkout without extras. Its SHA-256 is `d03f5a46174feae4d499808d05d98917eb59cbaa0174eaa7ebe19fe22a8f693a`.
- The extracted synthetic starter passed first/repeat offline setup with unchanged immutable bundle contents.
- Final candidate WSL Ubuntu first/repeat offline core setup passed, including full-integrity doctor and installed real-regression replay. Linux MCP was not installed or qualified.
- Final candidate Windows PowerShell 7 first/repeat offline MCP setup passed, including exact dependency checks, full-integrity doctor, installed real-regression replay, and the seven-tool stdio smoke. Its receipt matches the Linux candidate manifest; evidence is retained in `build/gap-closure/windows-candidate-acceptance.json`. An initial Windows PowerShell 5 launch inherited an incompatible module environment and failed before installation because `Get-FileHash` was unavailable; that launch is not counted as acceptance.

## Candidate

The unpublished `0.1.0a6` candidate is `build/gap-closure/candidate/standardsforge-ready-0.1.0a6.zip`:

- Size: 1,062,803,275 bytes.
- SHA-256: `309267ba415474ce728355e462db13599b13a4f969c6db05045780f13a4179f7`.
- Included packages: 438 page-text packs plus the qualified automated 810H outline.
- Bundled evidence: all physical-page ledgers, the exact real suite, and its passing raw-result report.
- Both portable core setup and the Windows MCP setup replay the suite before writing readiness.

Build, contract, benchmark, and platform logs are retained under `build/gap-closure/`. The source changes remain uncommitted. This candidate has not been uploaded to GitHub or PyPI and has no new hosted CI or signed release-attestation claim.

## Work still needed for complete closure

1. Closed in the follow-up [MIL-STD-1661 recovery](SCAN_RECOVERY_2026-10-08.md): all 18 scanned pages were recovered in distinct packages. The earlier candidate below retains its original corpus snapshot.
2. Continue corpus-wide adjudication. The follow-up provides 36 reviewed records and exact semantic coverage links for a bounded MIL-STD-1661 scope; the rest of the corpus still needs reviewed obligations, conditions, exceptions, tables, figures, and cross-page dependency links. A text disposition is not a semantic record or proof that every obligation was found.
3. Build an independently adjudicated real-document reference set covering omitted obligations, wrong governing context, visual tables, cross-page clauses, and edition confusion. Measure full-scope recall and fidelity against that set rather than treating this selected regression suite as a substitute.
4. Run native hosted release acceptance for the final candidate and publish only with explicit direction.

The operational workflow and reviewer formats are documented in [coverage and real qualification](COVERAGE_AND_REAL_QUALIFICATION.md).
