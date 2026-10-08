# Source coverage and real-document qualification

Source coverage accounting and semantic qualification are separate. A ledger records every physical page from each inventoried extraction report, including pages without extracted text, and binds each text record to its package, source PDF digest, physical page, exact text digest, and byte count. It does not infer requirements from normative keywords or mark tables, figures, or cross-page dependencies reviewed.

Generate the complete corpus ledger administratively:

```sh
python scripts/build_coverage_ledger.py PATH/TO/corpus.json NEW_OUTPUT_DIRECTORY
```

The manifest `coverage.json` is written last. A missing manifest means the collection is incomplete. Existing output directories are never overwritten. Every archive and pack is validated, and the corpus manifest binds the package ledgers by content digest. The October 8 local run accounted for 438 packs and 35,235 physical pages, including 17 without text and 159,752,989 extracted UTF-8 bytes awaiting disposition. These are source-accounting totals, not requirement counts.

A reviewer can disposition a complete page-local text partition with `requires_semantic_extraction`, `non_normative`, or `unresolved`. Each interval needs a rationale. Missing pages, stale ledger or text digests, unknown fields, gaps, overlaps, repeated pages, and split UTF-8 characters are rejected. Unsubmitted pages remain pending. `requires_semantic_extraction` is a work item, not a reviewed requirement. Human and agent provenance are explicit claims; neither grants applicability or approval.

```sh
standardsforge coverage-ledger PATH/TO/PAGE_PACK NEW_LEDGER.json
standardsforge coverage-ledger PATH/TO/PAGE_PACK NEW_REVIEWED_LEDGER.json --review REVIEW.json
```

The review format is defined in `contracts/coverage-review.schema.json`. Its `ledger_sha256` binds the original unreviewed ledger. Page keys and text hashes come from that ledger; byte offsets are local to the exact page-record text. Dispositions do not change installed source or query completeness.

## Real-document regressions

`benchmarks/real/mil-std-810h-outline-v3.json` contains eleven agent-reviewed source-text cases for one exact 810H package. They exercise eight passages, two discovery queries, and incomplete obligation enumeration. They include tailoring rationale, test-report limitations, a full table designator, Part Three scope, and the Antarctic exception. Expectations bind exact source and quote hashes independently of search output. They do not qualify visual table interpretation, full-document obligation recall, or human approval.

```sh
standardsforge --db PATH/TO/memory.db --store PATH/TO/objects qualify-real benchmarks/real/mil-std-810h-outline-v3.json --principal local-user --output NEW_RUN.json
```

The store must already be installed and authorized. The command opens it read-only. Every case is retained with its raw response and verdict, failed cases cannot be dropped, and the zero-failure gate and metric denominators are recomputed. Synthetic packs cannot receive real-document qualification. Results bind the full runtime Python source inventory, suite review, package, and edition. `scripts/run_real_benchmark.py` additionally denies socket creation while running the suite.

The prepared-distribution CLI requires a qualification directory containing `coverage/coverage.json`, every referenced page ledger, `real-suite.json`, and `real-benchmark.json`, plus an explicit `--outline-policy`. The builder verifies exact corpus coverage identities, suite and result integrity, a passing gate, and runtime-source equality with the bundled wheel. It includes these files in the closed bundle inventory. Portable setup replays the actual suite with the installed wheel before readiness, on both first and repeated setup. Historical bundles without qualification files retain their existing setup behavior.

## Remaining qualification work

The ledger makes missing work enumerable; it does not close full-corpus semantic extraction. Source-region adjudication, reviewed obligations and dependency links, visual verification of tables and figures, and cross-page continuity still need corpus-wide completion. The 18-page MIL-STD-1661 recovery and selected semantic links below are now locally qualified. Bounded agent-reviewed regressions do not replace an independently adjudicated quality corpus. Neither the ledger nor its regression report authorizes publishing a release or a project compliance decision.

## Reviewed scan recovery and direct semantic review

`compile-page-transcription SOURCE_PACK TRANSCRIPTION.json RASTER_DIRECTORY NEW_PACK` imports an explicit full-component transcription. The closed input binds the prior package, original PDF hash, renderer/text methods, every physical page, PNG hash, text, page-specific review notes, and a content-bound agent or human review. The importer preserves the PDF and inventories all text and PNG evidence in a distinct package. It rejects missing or duplicate pages, stale text review, wrong sources, changed images, and existing output. Rendering and OCR run explicitly outside the query core. The importer verifies identity; raster correspondence and visual correctness remain reviewer claims.

The schema is `contracts/page-transcription.schema.json`. Raster names are `page-0001.png`, etc. PNG is an inert inventoried evidence format; query tools never render or execute it. Pack identity changes while source PDF and edition identity stay fixed. Transcribed records remain semantically unclassified until separately reviewed.

`compile-reviewed-page-section SOURCE_PACK ANNOTATIONS.json NEW_PACK` accepts annotations 0.6.0 over exact page text, without requiring an automated outline candidate. It supports the existing reviewed semantics, multi-page spans, typed relationships, and explicit unsupported regions. Every span is revalidated against the source package. Derived structure packs retain upstream transcription and raster evidence when their source is a visual transcription.

`coverage-ledger SOURCE_PACK NEW_LEDGER.json --semantic-pack REVIEWED_PACK` verifies the reviewed pack's exact source-package pin and each contributing span, then records semantic links and the union of linked bytes per page. Unlinked bytes stay visible. Linked bytes are not an obligation-recall metric and do not establish completeness or approval.

The MIL-STD-1661 local recovery contains 18 visually inspected, agent-reviewed page transcriptions (35,364 UTF-8 bytes) and a separate 41-record reviewed structure with 28 requirement-candidate records and 89 relationships. It retains the source's duplicated `5.11.13` as two distinct occurrences, its cross-page exclusions and description list, source applicability, negative directives, explicit exceptions, and the example form's header/value associations. Some handwritten sample-form initials remain explicitly uncertain. The ledger links 16,100 bytes to selected semantic records; 56 remaining source regions are explicitly outside that semantic scope.

The tracked real suites `mil-std-1661-transcription.json` and `mil-std-1661-semantics.json` qualify 18 page reads and 23 reviewed-context cases. The latter compares complete statements (subject, action, modality, polarity, exact text, and span indices) and the exact typed qualifier list, including evidence spans. All 41 pass against the installed packages with sockets denied. These are same-agent review assertions, not an independently adjudicated reference set. Corpus-wide obligation recall and independent semantic/visual qualification remain open.


Transcription schema 0.2.0 adds a required per-page `disposition`: `transcribed_text` requires nonempty text; `reviewed_blank` requires exactly empty text. Both require a reviewed raster and page notes bound by the review digest. Blank pages remain in the physical-page report and coverage ledger with `extraction_status: reviewed_blank`, zero text bytes, and no fabricated retrieval record. `pages_without_text` includes these reviewed blanks; use the page status to distinguish them from unresolved missing text. An entirely blank component cannot become a queryable pack because it has no text record. Legacy 0.1.0 inputs retain their nonempty-text requirement.

The current recovery splits 4.2.4 into five separately qualified directives and keeps the complete parent clause as required context. The logical-ID slash suffixes and `.derived-` clause-reference suffixes are authored identities, not source numbering. The latter preserve the existing dot-descendant scope convention. Scoped enumeration returns exactly five classified directives. Other compound clauses remain bounded candidates; this does not establish atomic completeness for the document. The updated real-suite contract rejects legacy partial semantic assertions so they cannot silently pass as full semantic qualification.
