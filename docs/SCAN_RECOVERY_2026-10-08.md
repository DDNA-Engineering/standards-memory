# MIL-STD-1661 scan recovery and reviewed evidence

The missing-text gap is closed for this source through separate, source-bound recovery packages. All 18 physical pages were rendered and inspected, transcribed, compiled, installed, and queried. The old page package and corpus snapshot remain immutable. This is an unpublished local recovery supplement, not a replacement of the earlier prepared archive.

Status note (2026-10-09): both recovery packs were subsequently included in the unified [a6 prepared release](RELEASE_0.1.0a6.md) and retained unchanged in [a7](RELEASE_0.1.0a7.md). The rest of this document is the historical record of the local supplement and its own byte identities.

## Root cause and recovery

The original PDF is a scan. PDFium finds only the publisher download footer in its native text layer. The pinned pypdf layout parser fails on an inline RunLengthDecode image on page 2 (`EI stream not found`). The older compiler's one-record/17-missing-page result therefore understated the problem: the standard's body text had not been recovered on any of the 18 pages.

A separate administrative transcription workflow preserves the exact source PDF and prior package pin, inventories the rendered PNGs and corrected text, and binds methods and per-page notes to an explicit agent review. Tesseract 5.3.4 supplied draft text; every page was compared visually and corrected. Table and form fields were linearized explicitly. Handwritten sample initials that could not be read confidently remain marked. Rendering ran in a Windows Job Object; OCR ran with process limits in WSL. Neither renderer nor OCR is called by query tools.

The original parser failure remains an explicit failure in the old compiler-0.4 corpus checkpoint. No exception was reclassified as successful native text extraction. Recovered text is identified as reviewed visual transcription in returned derivation metadata.

## Delivered evidence

| Artifact | Result |
|---|---|
| Transcription package | `45db3b3e308f6c9f382ad2214464816053fa1e451ee3754236d61a73d9ece435` |
| Reviewed semantic package | `4c5e1c46a0584d97bd0c9fc6cbd6735a58ea12251bd0b3a3d53ae7ca1402add0` |
| Recovered page text | 18 pages, 35,364 UTF-8 bytes |
| Selected reviewed structure | 41 records, including 28 requirement-candidate records |
| Reviewed relationships | 89 declarations, including governing context and explicit external references |
| Byte linkage | 16,100 bytes linked to semantic records; 56 source regions explicitly outside the selected semantic scope |
| Real regressions | 41/41 passing; all 127 explicitly expected record occurrences returned |
| Regression suite | 196-test suite passing, including two platform skips |
| Contract checks | 47 schema documents and 56 requirements; recovered artifacts and all 41 semantic records validated |

The semantic evidence preserves the exclusions spanning physical pages 4–5, the applicability-qualified description list spanning pages 12–13, the source's two distinct occurrences labeled `5.11.13`, conditional MARK/MOD changes, the EX exception, and form/table header-value associations. Every semantic source span is checked against the exact transcription package. Transcription provenance and PNG evidence are also retained inside the standalone semantic pack.

Real gates check the source/edition, quote hashes, required context, completeness boundaries, and complete statements (subject, action, modality, polarity, exact text, and span indices). Typed qualifiers must match exactly, including their kind and evidence spans. Negative tests cover altered text review, changed images, missing/duplicate pages, wrong source identity, stale semantic spans, omitted or added qualifiers, changed qualifier types, altered actors/actions, stale statement/qualifier spans, and reversed polarity. Both real suites passed again using a fresh wheel install outside checkout imports with socket creation denied. The runtime source hash matched the original retained runs.

The core wheel built twice byte-identically and passed the isolated install smoke. SHA-256: `a2dc44fca311bfbdf779a70587e6aa74e0319930f305c77ddcef6ec47830b517`.

## Local supplement

`build/gap-closure/standardsforge-mil-std-1661-recovery-v2.zip` is a 19,281,875-byte, closed-inventory supplement containing the rebuilt wheel, both packs, exact local-user policies, baseline source package, annotations, coverage, and raw first/installed qualification results.

SHA-256: `01406cd8ccc5aa26d057bc3b4247ccc5e124074e070b0c62845806d082cde313`.

Its README gives offline install and qualification commands. The earlier `candidate/standardsforge-ready-0.1.0a6.zip` does not contain these follow-up changes and is not the current recovery artifact. No Git commit, hosted CI run, GitHub/PyPI publication, or signed release attestation was performed.

## Remaining boundary

This closes the concrete MIL-STD-1661 scan recovery and implements direct semantic review, exact coverage linkage, and real semantic regression gates. It does not close semantic interpretation of the full 35,235-page corpus. The reference assertions were authored by the same reviewing agent; independent adjudication, corpus-wide obligation recall, and human approval remain unestablished. Selected clauses can contain multiple directives, so 28 requirement-candidate records must not be reported as the document's total number of atomic requirements.


## Follow-up gap closure

The former false-pass probes now fail: changing a statement actor/action or swapping a condition and exception is rejected by the semantic gate. Partial legacy semantic expectations cannot pass the revised contract.

Clause 4.2.4 was compared again with the retained page-8 raster. Its full text remains a governing-context record, while five children separately express experimental assignment, avoidance of permanent assignment during evaluation, prohibition of the service number, EX identification during evaluation, and MARK identification after evaluation. Required links preserve the whole clause and original scope/exclusions. Each child passed an actual detailed retrieval; scoped enumeration returned exactly five classified directives. Derived identity suffixes do not purport to be printed source numbering. Other compound clauses still need separate decomposition before document-wide atomic completeness can be claimed.

Transcription 0.2.0 permits explicit `reviewed_blank` pages with exactly empty text, retained PNG/review notes, and complete physical-page coverage. Such pages have no fabricated text record and remain distinct from unresolved missing text in the coverage ledger. The fixture was compiled twice identically, installed, and queried; invented text, missing dispositions, undeclared empty text, and stale review were rejected. An entirely blank component cannot form a queryable pack. Legacy 0.1.0 inputs remain supported; the actual 1661 transcription identity is unchanged.

The v2 supplement built twice byte-identically and its full ZIP inventory was read back. Both real suites passed through its fresh offline wheel installation outside checkout imports with socket creation denied; runtime hashes matched the retained runs. Eight synthetic benchmark cases also passed. Evidence is retained under `build/gap-closure/recovery-v2/`. Earlier recovery artifacts remain historical and are not overwritten. No commit, publication, hosted CI, or independent corpus-wide adjudication was performed.
