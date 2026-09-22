# Query guide

StandardsForge exposes six read operations. Administration, acquisition, compilation, installation, revocation, and handoff export remain separate.

## Operations

| Command | Use it for |
|---|---|
| `search` | Discover authorized records through lexical search and source-linked snippets. |
| `resolve` | Resolve an exact document, edition, and optional representation to a package pin. |
| `get-clause` | Retrieve one exact record plus its required governing context. |
| `build-context` | Assemble several records without duplicating shared evidence. |
| `enumerate-obligations` | Traverse explicitly classified obligations in a selected scope. |
| `diff-editions` | Compare exact record identities and report review-required alignment candidates separately. |

All examples below assume a prepared distribution PowerShell opened in its extracted root and the principal `local-user`.

## Discover

```powershell
.\standardsforge.ps1 search "steady axial load" `
  --principal local-user `
  --query-mode exact_phrase `
  --limit 10
```

Lexical modes are explicit:

- `all_terms` requires every parsed lexical chunk and is the default;
- `exact_phrase` requires adjacent chunks in order;
- `any_terms` accepts at least one chunk.

Quotes, `OR`, wildcards, and parentheses are treated as input rather than raw FTS syntax. Search returns ranked candidates; it is not exhaustive retrieval or an applicability decision.

## Resolve and pin

```powershell
$resolved = .\standardsforge.ps1 resolve 'MIL-STD-810H(1)' `
  --representation derived_structure `
  --principal local-user | ConvertFrom-Json

$pin = $resolved.result.package_digest
```

Use `$pin` for subsequent reads. Page text, automated derived structure, reviewed structure, and curated records can coexist for one technical edition, so select a representation when resolution reports ambiguity.

## Retrieve exact evidence

Use the record and clause selectors returned by `search`:

```powershell
.\standardsforge.ps1 get-clause $pin '<clause-reference>' `
  --record-id '<record-id>' `
  --principal local-user `
  --response-profile concise_evidence_v1
```

The detailed profile remains the compatibility default. Compact and concise profiles reduce repeated structure without dropping exact evidence, citations, coverage, authorization, or expansion references. If a byte budget cannot hold required context, the operation fails instead of silently omitting evidence.

## Build context

```powershell
.\standardsforge.ps1 build-context $pin `
  --record-id '<record-id-1>' `
  --record-id '<record-id-2>' `
  --principal local-user
```

Required dependencies are collected transitively and shared evidence is returned once.

## Enumerate obligations

Enumeration traverses only records explicitly classified as obligations in the selected pack and scope. Zero results do not prove that the source contains no requirements; page-text and automated-outline packs intentionally do not invent document-wide obligation classifications.

Use returned continuations exactly as issued. Continuations are bound to the principal, query, package, policy, and snapshot state.

## Compare editions

Exact record IDs are the only authoritative cross-package identity. Unmatched records with a unique kind and clause reference may appear as review-required candidates, but candidates cannot change authoritative statuses or dependency impacts. Required-dependency paths are traversed separately on the before and after packages.

## Export a source-first handoff

`export-handoff` is an administrative write, not a seventh query:

```powershell
standardsforge export-handoff <package-digest> `
  --record-id <record-id> `
  --principal local-user `
  --candidate <candidate.json> `
  --output <output-directory>
```

The generated no-script reader keeps the exact evidence packet separate from the caller-authored candidate. It does not approve a requirement, tailoring decision, baseline, test plan, applicability conclusion, or compliance result.

See the [contracts](../../contracts/README.md) for machine shapes and the [model reading guide](../MODEL_READING_GUIDE.md) for model-facing interpretation rules.
