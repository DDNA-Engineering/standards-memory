# Agent self-review batch 2026-10: six bounded MIL-STD scopes

This is a local, unpublished, **agent self-review** batch prepared for integration into the next prepared release (0.1.0a8). The reviewing agent (Claude Code) authored and checked the annotations, the regression suites and the reference bindings (`independence_claim: self_review`). It is not human review, independent adjudication, corpus-wide coverage, an applicability decision, a compliance decision or approval.

## What was reviewed

Every source is the exact a7 page-text package from the published `standardsforge-ready-0.1.0a7.zip` (SHA-256 `8555fcafa683c60186575193c7cc504331ca6d49c5d64b76bda431b83b1bda9b`), corpus `dla-active-mil-std-current-page-text`, acquisition manifest `d02fc379a0bd9c6268b8f05cec558be9eda452f845300376910fa018ffcb7aea`, compiler 0.3.0. Each review selects one source component PDF of the package; other components (for example notices) are not reviewed.

| Slug | Document (DLA ident) | Source package | Reviewed scope | Pages with reviewed spans |
|---|---|---|---|---|
| `mil-std-882e-system-safety-requirements` | MIL-STD-882E(1) NOT 1 (36027) | `0e3b5644…74bfa1` | 1.1; 4.1–4.2.3.3; 4.3; 4.3.1 a–d; 4.3.2; 4.3.3 a–e with Table I and Table III rows; 4.3.4 and a–e; 4.3.7 | 8, 16, 18, 19, 20, 21 |
| `mil-std-461h-general-requirements` | MIL-STD-461H (35789) | `1475e7e0…efa89c` | 1.1; 1.3; 4.1–4.2.7; 4.3 paragraph; two Appendix A discussion excerpts (A.4.1, A.4.2.6) | 15, 21, 22, 186, 191 |
| `mil-std-464d-e3-general-and-emi` | MIL-STD-464D NOT 1 (35794) | `d49276c2…7a41e` | 1.1; 1.2; 4.1; 5.1; 5.2 paragraph; 5.6; 5.7; 5.7.1–5.7.3 | 10, 19, 20, 31, 32 |
| `mil-std-704f-general-requirements` | MIL-STD-704F(1) NOT 4 (35901) | `bb7f4efe…7ab4f` | 1.1; definitions 3.29, 3.30; 4.1–4.4 | 7, 12, 13, 14 |
| `mil-std-1474e-noise-general-requirements` | MIL-STD-1474E NOT 2 (36905) | `b1222ef5…7e22c` | 1.1–1.3; 4.1–4.2.2.2 | 7, 13, 14, 15 |
| `mil-std-1472h-acoustic-noise-design` | MIL-STD-1472H NOT 1 (36903) | `6d4092d7…6f90` | 1.1; 1.3; 5.5.4–5.5.4.4.3.4.2 | 18, 182 |

Measured from the compiled packs and the coverage ledgers written by the builder:

| Slug | Records | Obligation records | Typed qualifiers | Relationships | Unsupported regions | Linked bytes | Package text bytes | Unlinked bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 882E | 66 | 23 | 30 | 91 | 16 | 12,835 | 511,663 | 498,828 |
| 461H | 38 | 24 | 25 | 54 | 20 | 7,615 | 1,399,815 | 1,392,200 |
| 464D | 34 | 22 | 25 | 41 | 21 | 5,071 | 1,131,965 | 1,126,894 |
| 704F | 45 | 28 | 24 | 48 | 13 | 6,016 | 448,655 | 442,639 |
| 1474E | 29 | 16 | 20 | 35 | 13 | 5,533 | 360,725 | 355,192 |
| 1472H | 20 | 10 | 15 | 24 | 10 | 3,760 | 3,436,198 | 3,432,438 |
| **Total** | **232** | **123** | **139** | **293** | **93** | **40,830** | **7,289,021** | **7,248,191** |

"Linked bytes" is the union of semantic-record spans per page (`coverage-ledger --semantic-pack` semantics) over the whole multi-component source package. It is source accounting, not obligation recall. Obligation records count `statement_role: obligation` records; compound clauses were decomposed into derived child records (`.derived-` clause references and `/` logical-ID suffixes are authored identities, not printed numbering), so these are not counts of atomic requirements in the documents. Recommendations (`should`) and permissions (`may`, `shall be permitted`, `may not be required`) were kept out of the obligation role.

### Review method

- Only exact bytes of the verified page-text layer are bound. Each node's spans are layout fragments (runs of text separated by three or more spaces or a line break) joined with one LF, as the compiler requires. Text-layer artifacts such as `s hall`, `syste m` or `m ay` are preserved verbatim; nothing was rewritten. Headings are normalized labels and are not quote-bound.
- Every requirement candidate has a subject/action/modality/polarity statement bound to span indices; conditions, exceptions, applicability limits, acceptance criteria and tailoring instructions are typed qualifiers bound to exact spans. Where the text layer splits the printed modal verb (9 statements: 461H 4.2.2 DC capacitance; 704F 4.3 supply and 4.4 handbook methods; 882E 4.3.3.a and 4.3.7 acceptance definitions; 1472H 5.5.4.2, 5.5.4.3 GFE, 5.5.4.4.1 and 5.5.4.4.2), modality is recorded as `other` with an explicit unresolved issue, because the contract requires the modal token verbatim. Three obligations without any modal verb in the source (`is required`, `It is the responsibility`) are also `other`.
- Required `governed_by` links return the parent clause, section and scope/application records with every requirement, so exceptions stated in a parent (for example 461H 4.2.2 "(Navy only)", 704F 4.2.1 "not covered by this standard", 1474E 4.2.2 "shall not apply to the exteriors of military combat equipment", 882E 4.3.3.d tailoring) are part of the returned evidence.
- Tables: 882E Table I (severity) and Table III (risk assessment matrix) rows are linearized with the caption and header lines in text-layer order; column association is by left-to-right order and is recorded as an unresolved issue. Table III row F has a single "Eliminated" value whose column extent is not asserted. Table II (probability levels) interleaves two description columns in the text layer and is an explicit `unparsed_table` region. 882E Figure 1 and 1474E Figure 1 are not interpreted.
- 882E 4.3.4.a–e (design order of precedence) carry explicit `sequence_after` ordering.
- All other text on reviewed pages is declared as `outside_selected_scope` or running header/footer regions.

## Reviewed reference bindings

`reviews/agent-review-2026-10/reference-bindings.json` (SHA-256 `051f756fec1c4a2542fc67275b084aeb687eda396265330314d41f377ef776d3`) has 23 bindings from 17 source records: 12 resolved, 11 unresolved. Every resolved target is a reviewed record in this supplement; every edition basis is `reviewer_selected_navigation_edition`, because none of the citations names a revision.

| Source occurrence | Target |
|---|---|
| 461H A.4.1 discussion: "MIL-STD-464" (2 occurrences) | 464D 1.1 Purpose |
| 461H A.4.2.6 discussion: "MIL-STD-704" | 704F 1.1 Scope |
| 461H A.4.2.6 discussion: "MIL-STD-464" | 464D 1.1 Purpose |
| 464D 5.7 interface control requirements: "MIL-STD-461" | 461H 1.1 Purpose |
| 464D 5.7 verification: "MIL-STD-461" | 461H 4.3 Verification requirements |
| 464D 5.7.1 safety-critical and non-safety-critical PEDs: "MIL-STD-461" (2) | 461H 1.1 Purpose |
| 1474E 4.1: "design order of precedence in MIL-STD-882" | 882E 4.3.4 |
| 1472H 5.5.4.2: "MIL-STD-1474" | 1474E 1.1 Scope |
| 1472H 5.5.4.3: "MIL-STD-1474" | 1474E 4.1.1 Total system noise |
| 1472H 5.5.4.4.1: "MIL-STD-1474" | 1474E 4.2.1 Protection from hazardous noise |

Unresolved (no target selected): MIL-STD-188-125-1 and MIL-STD-1399-300-1 and MIL-STD-2169 (page text exists in the a7 corpus, as 188-125-1A, 1399-300-1 and 2169D, but no reviewed scope), MIL-STD-461 Test Method CE106 (461H installed, CE106 outside every reviewed scope), MIL-STD-3023, SD-2, DOD-STD-1399-070-1, MIL-HDBK-704-1 through -8, DoDI 5000 series, MIL-HDBK-1473 and JSSG-2010 (not in the a7 MIL-STD page-text corpus).

All 23 bindings were followed with `follow_references` against a fresh local store by the builder (23 returned, 12 with target evidence), and the 1474E 4.1 binding was also followed through the CLI (`--reference-bindings … --reference-bindings-sha256 …`). One-hop navigation is not dependency closure.

## Real-document regression suites

One suite per pack under `benchmarks/real/<slug>.json`, 242 cases and 1,246 expected record occurrences in total (882E 59/306, 461H 42/200, 464D 40/210, 704F 47/258, 1474E 33/174, 1472H 21/98). Each suite has:

- a `get_clause` case for every record with a reviewed statement or qualifier, expecting the complete required-context closure computed from the declared relationships, exact citations (page, source PDF SHA-256, quote SHA-256) for every returned record, complete semantic assertions (statement and exact typed qualifier list) for every returned semantic record, the record's qualifier texts as critical facts, sibling records as forbidden records, and `complete_for_requested_scope: false`;
- a scoped `enumerate_obligations` case for every clause with two or more obligation descendants, with out-of-scope obligations forbidden;
- two `search` discovery cases.

Because every case pins the package digest, edition ID, source PDF and quote digests and exact qualifiers, a dropped or retyped condition/exception, a wrong edition or a source mismatch fails the gate. The expectations were derived from the reviewed annotations, not copied from query output, but they are same-agent assertions.

## Rebuild

From the repository root, with an extracted prepared corpus (a7 or a later release with the same pinned packages):

```sh
python scripts/build_reviewed_supplement.py --corpus PATH/TO/standardsforge-ready-0.1.0a7/corpus --output NEW_OUTPUT_DIRECTORY
```

`--corpus` accepts the corpus directory or its `corpus.json`; `--index` defaults to `reviews/agent-review-2026-10/index.json`; `--principal` defaults to `local-user`. The builder fails closed (exit 2, nothing activated) on a changed corpus identity or source archive (`supplement_source_changed`), a missing archive (`supplement_source_missing`), an annotation, suite or binding artifact that differs from its pin or no longer binds the compiled package (`supplement_review_stale`), non-identical repeated compilation (`supplement_not_reproducible`), a failing suite (`supplement_suite_failed`) or an existing output. Socket creation is denied while it runs. It writes:

```
packs/<slug>.zip                      deterministic pack archive (compiled twice, bytes compared)
policies/<slug>.json                  exact one-pack policy, principal local-user
qualification/<slug>-suite.json       copy of benchmarks/real/<slug>.json
qualification/<slug>-run.json         qualify-real run against the freshly installed pack
qualification/<slug>-coverage.json    source coverage ledger with semantic links (additional to the requested layout)
reference-bindings.json               copy of the pinned binding artifact
supplement.json                       slugs, pack IDs, digests, source pins, suite/run paths, binding SHA-256 and counts
```

The committed annotations are the reviewed input. If they change, regenerate the derived inputs in this order from the repository root, then rebuild:

```sh
python reviews/agent-review-2026-10/tools/gen_suites.py --corpus PATH/TO/corpus
python reviews/agent-review-2026-10/tools/gen_bindings.py --corpus PATH/TO/corpus
python reviews/agent-review-2026-10/tools/gen_index.py --corpus PATH/TO/corpus
```

The tools compile each annotation in a temporary directory only to learn the reviewed package digest; suite expectations come from the annotations, not from query output. The annotation authoring aids are not committed.

The run artifacts bind `runtime_source_sha256` of `src/standardsforge`; a prepared build that checks run runtime equality with its wheel must rebuild the supplement from the same sources.

## Observed results (2026-10-09, Linux, Python 3.13, this branch)

| Slug | Package digest | Pack ZIP SHA-256 | Real suite |
|---|---|---|---|
| 882E | `e3f0f5879d47ba78558102a2d67948952345c6f00fbc3a1165092ede046f9e75` | `6c3d7ee5500972830756894f2674a0e1dfa4bb51286aab0b6a4b14f3fdbdaf65` | 59/59 |
| 461H | `8c6b1e291f1dbb667567281fbb055edf78d451de241fd9f5e93101f752c177fd` | `4ebbf91f5e41527d35110ecebc279bb98f8fe0812d71b749cdf8d5eee55adcda` | 42/42 |
| 464D | `410ec32ebe9b79e1ff57f43dec9075fb4e916172ba51d9f6a48b6be85989cb8c` | `4a04b4c6bff9ff118c7e98d9d82f405d813f6e9a7bdd45a67a7db5bf84f6dade` | 40/40 |
| 704F | `53b5328639ac4008654e2a65f49f9b204dce660e6b06c597196b974a401867e6` | `d10c21591a534ceecf19d31bec617f5dcadb70955a030cf11e8fd83ccb0a0b9e` | 47/47 |
| 1474E | `a352f44a109946ca369cebe3a710fb40be2cf4806072a54750f78b0e4c2d803a` | `dc992881243af66a23493cbcdd2d1060dc467b90723eb0a48506ff2afae6aaff` | 33/33 |
| 1472H | `dca7e56307bf00a6ba8209312fd888be649d4453a8fa9468ea3e9981d7ccd408` | `44ed9d1d4a0b06fb09b2b6d0812c57c22289766b380ecf1c3968d240b0d44c90` | 21/21 |

- Runtime source SHA-256 recorded in every run: `15889af74d922e45de90366c27984f8b528a2a7df642b6aaccdcab8b6869b560`.
- `supplement.json` SHA-256: `5c3c39ba0a41f9000c91d6b5ff988c7ece9b3d3be9448b29b1eb72e04ab8fc06`.
- Two complete builds from the rebased sources produced the same 32 files byte for byte, including all pack archives and run artifacts.
- The built packs were also installed through the CLI `install` command into another fresh store with their generated policies; all six `qualify-real` runs passed there.
- `python -m unittest discover -s tests` (after rebasing onto the integration branch): 367 tests ran, all passed, none skipped (Linux). `python scripts/validate_contracts.py` passed: 64 schema documents, 56 requirements, 30 validated contract instances including the six annotations, six new suites and the binding artifact.

## Limits

- **Agent self-review only.** The same agent selected the scopes, wrote the annotations, derived the suites from them and wrote the bindings. There was no human review, no separate reviewer and no independent adjudication; passing suites show consistency with the agent's own review, not correctness.
- **Text layer only.** PDF pages were not rendered or visually inspected. Reading order, table column association and split words come from the pypdf layout text layer; visual fidelity is not established.
- **Bounded scope.** About 0.56% of the six packages' extracted text bytes are linked to semantic records. All other clauses, pages, components (including notices), appendices, figures, Table II of 882E and the other 432 corpus packages remain unreviewed. This is not corpus-wide or document-wide semantic coverage, and obligation-record counts are not atomic-requirement recall.
- **Navigation, not dependency closure.** Bindings are one hop and reviewer-selected; zero bindings for a record does not mean zero references, and the selected editions are not source-mandated or project-approved.
- **No decisions.** Nothing here decides applicability, compliance, tailoring, baseline selection or approval. Imported rights claims are preserved and no processing, model-use or redistribution permission is granted.
- No commit was pushed, and no release, publication, hosted CI or attestation was performed for this batch.
