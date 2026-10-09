# Reviewed references and answer qualification

The runtime and contracts described here were published in [0.1.0a7](RELEASE_0.1.0a7.md). The reviewed packs, `reference-bindings.json` and answer-review artifacts in the dated local evidence below remain local and unpublished; the a7 prepared library does not include them, so its launcher returns `reference_bindings_not_configured` for `follow_references` (see [known limitations](RELEASE_0.1.0a7.md#known-limitations)). The a8 prepared archive bundles a separate, later agent-reviewed binding set; see [agent review 2026-10](AGENT_REVIEW_2026-10.md).

## Exact cross-standard navigation

The tenth read operation, `follow_references` (one of eleven in a7, alongside `get_source_pdfs`), reads an explicitly configured, SHA-256-pinned local binding artifact. Each reviewed occurrence binds the source package, edition, record, quote and UTF-8 reference span to an exact target package, edition, record and quote, or records an unresolved target. The artifact records the reviewer and the edition-selection rationale. Its schema is [reference-bindings](../contracts/reference-bindings.schema.json).

```powershell
standardsforge --reference-bindings reviewed-links.json --reference-bindings-sha256 <sha256> follow-references <source-package-sha256> <source-record-id> --principal local-user
standardsforge-mcp --principal local-user --reference-bindings reviewed-links.json --reference-bindings-sha256 <sha256>
```

Paths and pins are trusted startup configuration, never MCP tool arguments. Both endpoints are independently authorized and source-verified; the complete result is reauthorized before return. A revoked or missing target fails the request without returning partial target metadata. Byte budgets cover the complete result and never truncate evidence. No URL acquisition, automatic latest-edition choice, recursive traversal, or grant import occurs.

A reviewer-selected navigation edition is not a source-mandated or contract-approved edition. Each endpoint retains its own governing context. Zero configured bindings does not establish zero source references, and one-hop navigation does not establish complete cross-standard dependency closure.

## Review the actual answers

The answer workflow separates a content-bound suite, a submission of exact answer text and citations, and an explicit adjudication. Each question has source-pinned evidence and a complete criterion list. The reviewer judges the whole answer as well as each criterion, including conditions, exceptions and unsupported claims. The runner validates artifact bindings, current source access, exact citations, complete case coverage, and metric arithmetic; it does not invent semantic verdicts.

```powershell
standardsforge --db <db> --store <objects> export-answer-review suite.json submission.json review.html --principal local-user
# A reviewer opens review.html, reviews every answer and exports answer-adjudication.json.
standardsforge --db <db> --store <objects> qualify-answers suite.json submission.json answer-adjudication.json --principal local-user --output answer-quality-run.json
```

The local form starts entirely unreviewed and sends no data. Enter a reviewer identity, record corrections or accept each answer and its criteria, then export the completed review. Form choices are not saved until export. The source excerpts and identity details are preserved beside the proposed answers. Imported text is escaped, and scripts and styles are locally hash-bound.

The answer author or suite author cannot claim to be a separate reviewer under the same identity. Distinct identity strings are still provenance claims, not authenticated identity or proof of a blinded holdout. The run retains the raw suite, answers, judgments, evidence, metrics and runtime digest. A supported full-answer judgment, passing criteria and all required citations are necessary for a passing case. Missing judgments, unassessed criteria, stale submissions and changed source access cannot produce a passing result.

## Local evidence from 2026-10-08 (historical record)

Generated evidence is under `build/review-closure-2026-10-08/`. It is not a published release. The statements below record that pre-a7 local snapshot.

| Selected source | New reviewed records | Classified obligations | Pages with reviewed spans |
|---|---:|---:|---:|
| MIL-STD-25C | 10 | 1 | 3 |
| MIL-STD-196G composition | 13 | 4 | 5 |
| MIL-STD-882E composition | 4 | 0 | 2 |
| MIL-STD-31000C | 4 | 1 | 2 |
| Total | 31 | 6 | 12 |

All 31 exact-record regressions passed against newly installed local reviewed packs. These selected scopes link 11,815 source bytes and preserve 864,561 other bytes as unlinked across the four source packages. The review includes material-symbol footnotes, precedence exceptions, the two-page 196G scope, separate nomenclature directives, the 882E no-task condition and TDP tailoring. It is agent review of extracted text, not independent PDF visual validation or document-wide semantic completeness.

Direct annotations now select their explicit source-PDF SHA-256 within a multi-component parent package. Physical pages remain component-local; the parent package and edition remain pinned. Other components remain unreviewed. A synthetic two-component regression verifies selection when both PDFs have physical page 1, and rejection of missing or mismatched components.

`reference-bindings.json` has two reviewed navigation targets: 1661's electronic-equipment exclusion to the installed 196G scope, and 25C's drawing-category reference to the installed 31000C scope. Both are explicitly reviewer-selected editions. The cited ASME Y14.100 and DoDI 5000-series occurrences remain unresolved. All four returned packets were replayed against the local store.

`answer-suite-v2.json`, `answer-submission-v2.json` and `answer-review-v2.html` contain **12 questions and 31 criteria**. The user subsequently requested agent self-review; `answer-self-adjudication.json` records explicit rationales for every criterion and whole answer. `answer-self-review-run.json` replays all evidence under current authorization: 12/12 answers and 31/31 criteria passed. `answer-self-review.html` displays the results. The author and reviewer are the same agent, with `independence_claim: self_review`; no human or separate-reviewer claim is made. The earlier v1 packet was superseded before handoff to add the explicit SRP-route evidence to question 6. The v2 questions and answer bytes are frozen by digest. They are agent-authored, source-informed cases, not a blinded holdout, a live model comparison or a corpus-wide accuracy estimate.

Corpus-wide semantic review across the 438 base packages, comprehensive cross-standard mappings, and broad independent answer-quality qualification remain open. The selected agent self-review does not close those broader qualifications. No commit, publication, or new native CI result is claimed.

Final local validation: 224 tests ran, 222 passed and two platform-specific checks were skipped on Windows. Closed schema validation passed, including the five real reference/answer artifacts. The core wheel was built twice with identical bytes, installed outside the checkout and passed its smoke checks. SHA-256: `a2b37e437517f2964b1c4c5342683d70857e6bc03d3cf3877b8010a28910af24`. Every runtime Python module in that wheel matches the current source bytes. This local test wheel still has version 0.1.0a6 and must not replace the different published a6 artifact.
