# Model guide for reading MIL-STDs

StandardsForge returns source-linked evidence. It does not decide whether a document applies to a project or whether a design complies. A model using the tools should follow this sequence.

The published `v0.1.0a5` prepared archive exposes page-text packs and an automated, unreviewed MIL-STD-810H `outline-v1` pack. Later source-only outline and reviewer improvements are not in that archive or its PyPI wheel. A verified citation establishes an exact source match, not a reviewed interpretation or complete requirements graph.

## Connect a prepared Windows distribution

On 64-bit Windows with CPython 3.12, run `setup.ps1` once from the extracted distribution. The setup verifies the archive manifest, installs the bundled core and exact hash-locked MCP dependency wheelhouse without network access, installs every bundled pack, and performs a real MCP stdio smoke test. Then configure the model host with an absolute launcher path so startup does not depend on the host's working directory.

Claude Desktop and Cursor use the same `mcpServers` shape (Cursor stores it in `.cursor/mcp.json`):

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

Run `sh ./setup.sh` once in the extracted distribution to install the bundled core and corpus offline. POSIX MCP is a separate, explicit networked code channel: create an environment outside the prepared directory, then install `standardsforge[mcp]==0.1.0a5` from PyPI. PyPI does not contain or fetch the prepared corpus.

Start the installed module with absolute paths to the distribution-local state:

```sh
MCP_VENV=/absolute/path/to/standardsforge-mcp-venv
PREPARED_ROOT=/absolute/path/to/standardsforge-ready-0.1.0a5
python3 -m venv "$MCP_VENV"
"$MCP_VENV/bin/python" -m pip install "standardsforge[mcp]==0.1.0a5"
"$MCP_VENV/bin/python" -I -m standardsforge.mcp_server \
  --db "$PREPARED_ROOT/.standardsforge/memory.db" \
  --store "$PREPARED_ROOT/.standardsforge/objects" \
  --principal local-user \
  --result-mode structured_only
```

Keep the MCP environment outside the closed prepared directory. The network is needed for the PyPI code/dependency install, not for corpus setup or query. Model-host configuration must preserve the absolute database, object-store, and principal arguments above.

## Required tool sequence

1. If the exact installed identifier is unknown, call `list_documents`; treat its authorized inventory and declared coverage as discovery, not applicability or baseline approval.
2. Resolve the exact document identifier, edition, and representation. Keep the returned package digest as the immutable pin for the rest of the task.
3. Use `search` only to discover candidate records. Prefer `natural_language` for a prose question and inspect its disclosed effective terms and selected strict or relaxed strategy. Each hit carries its identifier, edition ID, and package digest, but search rank is not applicability, normative status, or complete coverage. Use document inventory and exact resolution for identifiers.
4. Replay a selected result's evidence selector through `get_clause`, or use `build_context` for multiple selected records. Base answers on exact retrieved text and returned required context, not the search snippet.
5. Read coverage, derivation status, relationships, citations, and limitations before answering. Preserve unresolved dependencies and unsupported regions.
6. Use `enumerate_obligations` only for packs that explicitly classify obligations. Zero returned rows does not mean zero requirements when classification or source interpretation is incomplete.

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
- Cite the exact package, clause or record identity, physical source location, and exact text supporting an answer. State incomplete or unknown coverage instead of filling gaps from general knowledge.

## Answer boundary

A defensible model answer identifies the exact edition and package pin, quotes or faithfully paraphrases retrieved evidence, includes governing context, names unresolved inputs, and separates source requirements from applicability or compliance judgment. If the evidence packet is incomplete for the question, the correct result is a bounded answer or abstention—not a silent inference.
