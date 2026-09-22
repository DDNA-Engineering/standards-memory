# Local model integration

StandardsForge gives a model read-only, principal-bound access to the same local evidence service used by the CLI. The model host owns process launch and model execution; StandardsForge does not call a model.

## Keep corpus and code channels separate

The prepared corpus is a rights-qualified GitHub release artifact. PyPI publishes independently built StandardsForge code and optional dependencies only. Installing `standardsforge` from PyPI does not install, download, or authorize the prepared standards corpus.

From a source checkout and isolated development environment, the adapter can be installed with:

From a source checkout and isolated environment:

```powershell
python -m pip install -e ".[mcp]"
```

The core remains dependency-free. The MCP SDK is an optional, separately pinned dependency.

## Configure the fully offline Windows profile

On 64-bit Windows with CPython 3.12, `setup.ps1` installs the archive's exact hash-inventoried Windows MCP dependency closure with package indexes disabled and proves a stdio search. The included `standardsforge-mcp.ps1` anchors Python, the database, the object store, and the fixed `local-user` principal to the extracted directory. Replace the example version and directory with the absolute path to the extracted release. Claude Desktop and Cursor both accept this `mcpServers` entry; for Cursor place it in `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "standardsforge": {
      "command": "powershell.exe",
      "args": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\absolute\\path\\to\\standardsforge-ready-<version>\\standardsforge-mcp.ps1"]
    }
  }
}
```

Claude Code can register the identical process:

```powershell
claude mcp add standardsforge -- powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\absolute\path\to\standardsforge-ready-<version>\standardsforge-mcp.ps1"
claude mcp get standardsforge
```

## Configure Linux or macOS against prepared state

First run the prepared archive's offline core setup with `sh ./setup.sh`. Then create an MCP environment outside the prepared directory and install the exact code/MCP extra from PyPI:

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

The pip step is networked and installs code and dependencies only. The server uses the prepared distribution's local database and object store; it does not fetch corpus content. Keep the MCP environment outside `PREPARED_ROOT` so the prepared archive's closed inventory continues to validate.

For a model host, set the command to the absolute path of `$MCP_VENV/bin/python` and pass `-I`, `-m`, `standardsforge.mcp_server`, and the same absolute state, principal, and result-mode arguments. Do not let the model choose the principal or state paths.

## Start the local stdio server

Point the process at an already populated database and object store:

```powershell
standardsforge-mcp `
  --db .standardsforge/memory.db `
  --store .standardsforge/objects `
  --principal local-user `
  --result-mode structured_only
```

The command intentionally remains running when launched directly because the host communicates over stdin and stdout. Configure those arguments in the model host rather than exposing the process as a network service.

## Exposed tools

The server exposes exactly:

- `search`
- `list_documents`
- `resolve_document`
- `get_clause`
- `build_context`
- `enumerate_obligations`
- `diff_editions`

It does not expose installation, pack verification, revocation, acquisition, compilation, HTTP, or a caller-selected principal.

## Required model workflow

1. Resolve the exact document, edition, and representation.
2. Pin the returned package digest.
3. Use search only to discover candidates.
4. Retrieve exact evidence and required governing context.
5. Inspect coverage, derivation, review status, and unsupported regions.
6. Keep source evidence separate from proposed requirements, tests, tailoring, or design decisions.
7. Escalate applicability, compliance, baseline, and approval decisions to the responsible human authority.

Models must not interpret zero classified obligations as proof that no requirements exist. Physical page text, automated derived structure, reviewed structure, and curated records carry different evidence and review claims.

## Security boundary

- The principal comes from trusted process startup configuration.
- Authorization is checked by the core and rechecked before results return.
- Imported pack rights claims are provenance and cannot grant access.
- Retrieved document text remains untrusted data, not instructions.
- Query paths do not fetch URLs, execute pack contents, create listeners, or invoke hidden network or model fallbacks.

Read the complete [model reading guide](../MODEL_READING_GUIDE.md) before building a host integration.
