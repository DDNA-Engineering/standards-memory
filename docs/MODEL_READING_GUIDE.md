# Model guide for reading MIL-STDs

StandardsForge returns source-linked evidence. It does not decide whether a document applies to a project or whether a design complies. A model using the tools should follow this sequence.

The published `v0.1.0a7` prepared archive contains 441 packages, including the automated MIL-STD-810H `outline-v3` and the separately qualified 1661 recovery packs; its content baseline is unchanged from a6. The a7 runtime exposes eleven read tools, including structural navigation, measured evidence selection, reviewed-reference navigation and original PDF delivery; see [knowledge access](KNOWLEDGE_ACCESS.md). Corpus-wide `outline-v4` packages remain unpublished. A verified citation establishes an exact source match, not a reviewed interpretation or complete requirements graph.

## Connect a prepared Windows distribution

On 64-bit Windows with CPython 3.12, double-click `setup.cmd` (or run `setup.ps1`) once from the extracted distribution. The setup verifies the archive manifest, installs the bundled core and exact hash-locked MCP dependency wheelhouse without network access, installs every bundled pack, and performs a real MCP stdio smoke test. It then writes `.standardsforge/mcp-config.json` and `.standardsforge/codex-mcp.toml` with absolute paths that launch `.venv\Scripts\python.exe -I run_mcp.py`; merge the generated entry into the model host so startup does not depend on the host's working directory.

The optional `standardsforge-mcp.ps1` wrapper remains available for existing Windows host conventions. Claude Desktop and Cursor use the same `mcpServers` shape (Cursor stores it in `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "standardsforge": {
      "command": "powershell.exe",
      "args": [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "C:\\absolute\\path\\to\\standardsforge-ready-<version>\\standardsforge-mcp.ps1"
      ]
    }
  }
}
```

Claude Code can register that launcher directly:

```powershell
claude mcp add standardsforge -- powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\absolute\path\to\standardsforge-ready-<version>\standardsforge-mcp.ps1"
```

The launcher fixes the principal to `local-user` and anchors the database and pack store to the extracted distribution. Do not add command-line state or principal overrides in a host configuration.

## Connect a prepared Linux or macOS distribution

With CPython 3.11+ and `venv`, run this once in the extracted distribution:

```sh
sh ./setup.sh --mcp-online
```

The bundled core wheel and corpus install offline. Only this explicit option downloads the MCP dependencies, into the distribution-owned `.venv`; PyPI does not contain or fetch the prepared corpus. Setup makes a real stdio query, then writes `.standardsforge/mcp-config.json` and `.standardsforge/codex-mcp.toml` with absolute paths that launch `.venv/bin/python -I run_mcp.py`. Merge the generated entry into the model host. The launcher fixes the principal and distribution-local state and rejects overrides. `sh ./setup.sh` without the option remains offline and terminal-only. See the [prepared library guide](wiki/PREPARED_LIBRARY.md) and [model integration](wiki/MODEL_INTEGRATION.md#connect-your-model-host).

The prepared launcher configures no reviewed reference bindings or tokenizer: `follow_references` returns `reference_bindings_not_configured` and token-budgeted `select_evidence` returns `tokenizer_unavailable`. See [known limitations](RELEASE_0.1.0a7.md#known-limitations).

## Required tool sequence

1. If the exact installed identifier is unknown, call `list_documents`; treat its authorized inventory and declared coverage as discovery, not applicability or baseline approval.
2. Resolve the exact document identifier, edition, and representation with `resolve_document`. Keep the returned package digest as the immutable pin for the rest of the task.
3. Use `search` only to discover candidate records. Prefer `natural_language` for a prose question and inspect its disclosed effective terms and selected strict or relaxed strategy; use `concept_language` when wording differs and treat its disclosed alternatives as discovery hints. Each hit carries its identifier, edition ID, and package digest, but search rank is not applicability, normative status, or complete coverage. Use `browse_records` for roots, children, parents, adjacent records and incoming or outgoing links, including unclassified records.
4. Replay a selected result's evidence selector through `get_clause`, use `build_context` for multiple selected records, or use `select_evidence` for one record's smallest measured lossless packet. Base answers on exact retrieved text and returned required context, not the search snippet.
5. Read coverage, derivation status, relationships, citations, and limitations before answering. Preserve unresolved dependencies and unsupported regions.
6. Use `enumerate_obligations` only for packs that explicitly classify obligations. Zero returned rows does not mean zero requirements when classification or source interpretation is incomplete.
7. Use `follow_references` only when the host configured a reviewed binding artifact, and `diff_editions` only for an explicit comparison of installed editions.
8. Call `get_source_pdfs` for each distinct cited package and link the returned verified local PDFs; report `no_pdf_sources` or a verification failure instead of guessing a path.

## Representation meaning

| Representation | Safe interpretation |
| --- | --- |
| `page_text` | Physical-page text extracted from verified source bytes. It is not a semantic clause, table, figure, or obligation model. |
| `derived_structure` | Automated, unreviewed navigation candidates with exact source spans. It must not be promoted to confirmed requirements or approval. |
| `reviewed_structure` | Reviewed structure only inside the pack's declared reviewed scope. It does not imply document-wide review. |
| `curated_records` | Curated records with the pack's declared provenance and coverage; do not assume coverage beyond those declarations. |

## MIL-STD reading rules

- Keep the exact revision, change, notice, and component composition visible. Do not merge text from different editions or package digests.
- Distinguish scope, applicable/referenced documents, definitions, general requirements, detailed requirements, tailoring guidance, and verification or test methods.
- Treat conditions, exceptions, notes, footnotes, table headers, units, tolerances, sequencing, and cross-references as potentially governing context.
- The word `shall` can indicate normative wording, but it does not establish that the clause applies to a particular project. Applicability comes from an approved external baseline, contract, tailoring record, or other authorized decision.
- A test method describes how evidence may be produced; it is not automatically a product requirement. Keep requirement and verification evidence separate.
- Do not infer table-cell or figure meaning when the returned representation declares captions or text only.
- Cite the standard, exact edition, clause when available, and physical PDF page in the answer. Keep full package and record identities in the underlying evidence or optional audit details. State incomplete or unknown coverage instead of filling gaps from general knowledge.

## Answer boundary

A selected StandardsForge question uses installed evidence only by default. Retrieve exact MCP packets before answering; do not supplement gaps with web research, remembered standard text or unsupported design suggestions. Missing location-specific inputs, editions and referenced documents remain explicit gaps. Only an explicit request for external research widens that scope, and external findings must be attributed separately. The skill communicates this workflow; host tool permissions remain a separate integration responsibility.

A defensible model answer names the exact edition, quotes or faithfully paraphrases retrieved evidence, includes governing context, names unresolved inputs, and separates source requirements from applicability or compliance judgment. Preserve the package pin for replay without displaying it as the primary citation. If the evidence packet is incomplete for the question, the correct result is a bounded answer or abstention—not a silent inference.

Use readable blockquotes and citations in the chat. A source attachment should open to passages, not JSON: the optional [skill reader](../plugins/standardsforge/skills/standardsforge/scripts/render_evidence.py) renders detailed retrieved packets as static HTML, with full audit data in closed disclosures. Keep material coverage and review limits visible. Offer original PDF pages only when the host has a confirmed source/page link or authorized preserved file; never invent a path or URL. Do not silently repair extraction errors inside a quote. This host-side presentation does not change MCP transport, source bytes or authorization.

For external references, use `follow_references` only when the host configured a reviewed binding artifact. Inspect each binding's edition basis: a reviewer-selected navigation edition does not establish the issue required by a source or contract. Read both returned evidence packets; zero bindings and one-hop traversal do not imply complete dependency closure.
