# Query guide

The `0.1.0a7` and later releases expose eleven read operations through the CLI and the stdio MCP adapter. [Knowledge access and compression](../KNOWLEDGE_ACCESS.md) and [reviewed references](../REVIEW_AND_REFERENCE_QUALIFICATION.md) describe the four operations added after a6. Administration, acquisition, compilation, installation, revocation, and handoff export remain separate.

## Operations

| CLI command | MCP tool | Use it for |
|---|---|---|
| `search` | `search` | Discover authorized records through lexical search and source-linked snippets. |
| `list-documents` | `list_documents` | Inventory authorized installed packages, optionally by normalized identifier prefix. |
| `resolve` | `resolve_document` | Resolve an exact document, edition, and optional representation to a package pin. |
| `get-clause` | `get_clause` | Retrieve one exact record plus its required governing context. |
| `build-context` | `build_context` | Assemble several records without duplicating shared evidence. |
| `enumerate-obligations` | `enumerate_obligations` | Traverse explicitly classified obligations in a selected scope. |
| `diff-editions` | `diff_editions` | Compare exact record identities and report review-required alignment candidates separately. |
| `browse-records` | `browse_records` | Navigate all, root, child, parent, adjacent, incoming, and outgoing records, including unclassified pages and automated outline nodes. |
| `select-evidence` | `select_evidence` | Retrieve one exact record with required context in the smallest measured lossless profile. |
| `follow-references` | `follow_references` | Follow explicitly reviewed, digest-pinned cross-standard bindings from one exact record. Requires host-configured `--reference-bindings`. |
| `source-pdfs` | `get_source_pdfs` | Locate verified preserved original PDFs for an exact package on the local host. |

The examples below use the prepared core's PowerShell form, `python .\run.py`, and principal `local-user`. On Linux or macOS, replace that launcher with `sh ./standardsforge.sh`. Both launchers anchor state to the extracted distribution and validate its manifest-bound receipt and owned runtime before use. Rerun setup for a full closed-bundle revalidation.

## Discover

When the exact installed identifier is unknown, inventory the caller's authorized packages first:

```powershell
python .\run.py list-documents `
  --identifier-prefix 'MIL-STD-810' `
  --principal local-user `
  --limit 50
```

The result includes exact edition and representation identities, immutable package digests, record counts, declared coverage, and a signed continuation when another page exists. Prefix matching is normalized and literal, not fuzzy or wildcard search. The inventory is authorization-filtered and publisher currentness does not select a project baseline.

```powershell
python .\run.py search "steady axial load" `
  --principal local-user `
  --query-mode exact_phrase `
  --limit 10
```

Lexical modes are explicit:

- `all_terms` requires every parsed lexical chunk and is the default;
- `exact_phrase` requires adjacent chunks in order;
- `any_terms` accepts at least one chunk;
- `natural_language` removes fixed question scaffolding, uses Porter stemming over headings and text, tries strict AND, and attempts one disclosed OR fallback only if strict matching is empty;
- `concept_language` adds a small, versioned local discovery vocabulary, ranks distinct concept matches before repeated occurrences, and returns the exact expansion groups and policy version. Alternatives are discovery aids, not equivalences.

Raw queries, parsed term count, and term size are bounded before local execution. Quotes, `OR`, wildcards, and parentheses are treated as input rather than raw FTS syntax. Natural-language responses disclose effective and ignored terms, tokenizer, ranker, attempted strategies, and the selected strategy. Scores are computed from each visible row rather than global corpus statistics. Search returns ranked candidates; it is not exhaustive retrieval or an applicability decision. Use `list-documents` and `resolve` for exact identifiers rather than relying on lexical matches.

## Resolve and pin

```powershell
$resolved = python .\run.py resolve 'MIL-STD-810H(1)' `
  --representation derived_structure `
  --principal local-user | ConvertFrom-Json

$pin = $resolved.result.package_digest
```

Use `$pin` for subsequent reads. Page text, automated derived structure, reviewed structure, and curated records can coexist for one technical edition, so select a representation when resolution reports ambiguity.

## Retrieve exact evidence

Use the record and clause selectors returned by `search`:

```powershell
python .\run.py get-clause $pin '<clause-reference>' `
  --record-id '<record-id>' `
  --principal local-user `
  --response-profile concise_evidence_v1
```

The detailed profile remains the compatibility default. Compact and concise profiles reduce repeated structure without dropping exact evidence, citations, coverage, authorization, or expansion references. If a byte budget cannot hold required context, the operation fails instead of silently omitting evidence.

In the published prepared library (unchanged content baseline since `v0.1.0a6`), a retrieved MIL-STD-810H `outline-v3` record can have a verified physical-page citation while its derivation remains `automated_unreviewed` and `coverage.complete_for_requested_scope` remains `false`. These are independent fields: exact quote verification is not review, and a selected passage is not complete document interpretation. See the [a7 release evidence](../RELEASE_0.1.0a7.md) and [a6 qualification record](../RELEASE_0.1.0a6.md) for the qualified representations and their limits.

## Build context

```powershell
python .\run.py build-context $pin '<clause-reference-1>' '<clause-reference-2>' `
  --principal local-user `
  --response-profile concise_evidence_v1
```

`build-context` takes one or more positional clause references; it has no `--record-id` selector. Required dependencies are collected transitively and shared evidence is returned once.

## Enumerate obligations

Enumeration traverses only records explicitly classified as obligations in the selected pack and scope. Zero results do not prove that the source contains no requirements; page-text and automated-outline packs intentionally do not invent document-wide obligation classifications.

For the prepared corpus (page text, `outline-v3`, and the bounded 1661 recovery packs; unchanged from `v0.1.0a6` through `v0.1.0a7`), page records and the unreviewed outline are navigation evidence, not an exhaustive clause/obligation graph. Do not use a lexical search or a physical-page prefix as a substitute for an explicitly classified scope when making completeness claims.

Use returned continuations exactly as issued. Continuations are bound to the principal, query, package, policy, and snapshot state.

## Browse structure

```powershell
python .\run.py browse-records $pin --principal local-user --relation roots
python .\run.py browse-records $pin --principal local-user --relation children --record-id '<record-id>'
```

`all` and `roots` need no anchor; `children`, `parent`, `adjacent`, `outgoing`, and `incoming` require an exact `--record-id`. Optional `--kind` and `--scope-prefix` filters remain package-local; `--limit`, `--cursor`, and `--max-bytes` bound paging and response size. Navigation is not semantic completeness; replay returned evidence selectors for exact text.

## Select measured evidence

```powershell
python .\run.py select-evidence $pin '<record-id>' --principal local-user --max-bytes 20000
```

Without a configured tokenizer, selection uses exact canonical UTF-8 bytes. `--max-tokens` requires global `--tokenizer-artifact` and `--tokenizer-sha256` startup options; otherwise it fails with `tokenizer_unavailable`. Insufficient budgets never truncate evidence. See [knowledge access](../KNOWLEDGE_ACCESS.md#select-measured-evidence).

## Follow reviewed references

```powershell
standardsforge --reference-bindings reviewed-links.json --reference-bindings-sha256 <sha256> `
  follow-references $pin '<record-id>' --principal local-user
```

Binding paths and pins are trusted startup configuration placed before the subcommand, never tool arguments. Without them the operation returns `reference_bindings_not_configured`. The prepared a7 distribution ships no binding artifact and its MCP launcher configures none; see [known limitations](../RELEASE_0.1.0a7.md#known-limitations). A reviewer-selected edition is navigation, not a source-mandated or project baseline edition.

## Locate original PDFs

```powershell
python .\run.py source-pdfs $pin --principal local-user
```

Returns digest-verified absolute local paths for every preserved PDF component of the authorized package, including notices and changes. A text-only package returns `no_pdf_sources`. Paths are on the host running StandardsForge; nothing is fetched, rendered, or copied.

## Compare editions

Exact record IDs are the only authoritative cross-package identity. Unmatched records with a unique kind and clause reference may appear as review-required candidates, but candidates cannot change authoritative statuses or dependency impacts. Required-dependency paths are traversed separately on the before and after packages.

## Export a source-first handoff

`export-handoff` is an administrative write, not a query operation:

```powershell
standardsforge export-handoff <package-digest> `
  --record-id <record-id> `
  --principal local-user `
  --candidate <candidate.json> `
  --output <output-directory>
```

The generated no-script reader keeps the exact evidence packet separate from the caller-authored candidate. It does not approve a requirement, tailoring decision, baseline, test plan, applicability conclusion, or compliance result.

See the [contracts](../../contracts/README.md) for machine shapes and the [model reading guide](../MODEL_READING_GUIDE.md) for model-facing interpretation rules.
