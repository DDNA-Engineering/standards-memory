# Knowledge access and compression

These features are **unreleased source changes after 0.1.0a6**. The published a6 wheel and prepared distribution retain their existing seven-operation interface. Install this checkout to use the new operations; no new release is asserted.

## Navigate before retrieving

`browse-records` includes every installed record, including unclassified pages and automated outline nodes. It supports `all`, `roots`, `children`, `parent`, `adjacent`, `outgoing`, and `incoming`. The last five require an exact `--record-id`. Optional `--kind` and `--scope-prefix` filters remain package-local.

```powershell
standardsforge browse-records <package-sha256> --principal local-user --relation roots
standardsforge browse-records <package-sha256> --principal local-user --relation children --record-id <record-id>
standardsforge browse-records <package-sha256> --principal local-user --relation incoming --record-id <record-id>
```

Every returned record includes a verified citation, derivation status and replayable evidence selector. Incoming/outgoing results include the traversed relationship type and required flag. Pagination is signed and bound to the caller, package, filters and authorization snapshot. `traversal_complete` means all matching installed records were visited; it does not establish source or semantic completeness. Query startup and traversal do not modify the database.

Parent/child links exist only where the selected pack declares them. Adjacent means the preceding and following installed record. Cross-standard references can now be followed through a separately configured, reviewed and digest-pinned artifact using `follow-references`. Each endpoint remains independently authorized and source-verified; reviewer-selected editions do not establish a project baseline. See [reference and answer qualification](REVIEW_AND_REFERENCE_QUALIFICATION.md).

## Discover paraphrases explicitly

Existing lexical modes retain their behavior. `concept_language` adds a small, versioned local discovery vocabulary and ranks distinct concept matches before repeated occurrences. It returns the exact expansion groups and policy version.

```powershell
standardsforge search 'justification for tailored criteria' --principal local-user --package-digest <package-sha256> --query-mode concept_language
```

Concept alternatives are candidate-discovery aids. For example, `polar` can discover `Antarctic` or `Arctic`; it does not make them interchangeable. No model, embedding service, network fallback, baseline selection or compliance inference is involved. Read the exact returned source before answering. Ordinary natural-language search remains useful when the source wording already matches.

## Select measured evidence

`select-evidence` obtains one exact record and its required dependency closure, renders all three existing lossless profiles, and returns the smallest measured evidence packet. With no tokenizer configured it uses exact canonical UTF-8 JSON bytes. A token limit without a configured tokenizer is an error; insufficient budgets never truncate evidence.

```powershell
standardsforge select-evidence <package-sha256> <record-id> --principal local-user --max-bytes 20000
```

For actual BPE counts, install the optional dependency and explicitly prepare the tokenizer once:

```powershell
python -m pip install -e '.[tokens]'
standardsforge export-tokenizer o200k_base .standardsforge/o200k-base.json
# Copy the exact SHA-256 returned by export-tokenizer into the trusted host configuration.
standardsforge --tokenizer-artifact .standardsforge/o200k-base.json --tokenizer-sha256 <sha256> select-evidence <package-sha256> <record-id> --principal local-user --max-tokens 8000
```

Only the explicit administrative export may obtain tokenizer data. Counting loads the pinned local artifact and never calls the tokenizer downloader. Token-like strings in source evidence are counted as ordinary text.

The `candidates` measurements cover the nested `evidence` packet serialized as canonical JSON, including its existing profile metadata. They exclude the selection wrapper, MCP tool schema, host formatting, and model chat framing. Legacy profile-local token status remains unchanged; counts for this operation live in the selection envelope. This is an exact encoding-specific payload measure, not an end-to-end model bill or answer-quality claim.

MCP exposes `browse_records` and `select_evidence` under the startup-bound principal. Tokenizer paths and pins are host configuration, not tool-call arguments:

```powershell
standardsforge-mcp --principal local-user --result-mode structured_only --tokenizer-artifact .standardsforge/o200k-base.json --tokenizer-sha256 <sha256>
```

## Deduplicate transport without changing packages

```powershell
standardsforge bundle-packs library.bundle.zip pack-a.zip pack-b.zip
standardsforge verify-bundle library.bundle.zip
standardsforge install-bundle library.bundle.zip --policy trusted-local-policy.json
```

The data-only bundle stores each exact file digest once. JSON/text members use ZIP LZMA when its measured payload is smaller; other members use Deflate. The builder reconstructs and validates every package before reporting success. The reader rejects missing, extra, duplicate, unsafe or altered members and rechecks the original package identities. Installation preflights every package against trusted local policy, then uses normal pack installation. An interrupted installation can be repeated; it is not a multi-package transaction.

Deduplication applies to download/transport storage. Installed object directories remain independent copies, avoiding shared mutable file links. A content bundle contains packs only; it is not the prepared installer with its wheel, scripts, policy and release qualification. Compare equal content sets when measuring savings.

## Expand structural coverage

```powershell
python scripts/compile_corpus_outlines.py .standardsforge/corpus/mil-std-current/corpus.json build/corpus-outlines
```

This restartable administrative command checks every source archive, compiles the existing deterministic outline representation and verifies source/compiler binding before reusing an output. Its `outlines.json` reports every success or failure. New outlines remain automated and unreviewed; unsupported regions, tables, figures and cross-page continuity retain their declared limitations. Explicit source-bound semantic review is still required before classifying requirements or resolving their conditions and exceptions.

The current compiler emits `outline-v4` with case/punctuation-preserving identities and records 0.3.0. Structural text is stored once in the exact source sidecar and reconstructed from a verified byte range. The original PDF, text, quote hash, physical page and structural span remain intact. This also permits large outlines to remain within the existing JSON size limit. Published `outline-v3` identities and packages are retained unchanged.
