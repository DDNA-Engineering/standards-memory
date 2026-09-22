# Local model integration

StandardsForge gives a model read-only, principal-bound access to the same local evidence service used by the CLI. The model host owns process launch and model execution; StandardsForge does not call a model.

## Install the adapter

From a source checkout and isolated environment:

```powershell
python -m pip install -e ".[mcp]"
```

The core remains dependency-free. The MCP SDK is an optional, separately pinned dependency. The prepared release already carries its hash-inventoried dependency closure and proves a stdio search during setup, so prepared-release users do not run this install command.

## Configure the prepared release

The prepared release provides `standardsforge-mcp.ps1`, which anchors Python, the database, the object store, and the fixed `local-user` principal to the extracted directory. Replace the example with its absolute path. Claude Desktop and Cursor both accept this `mcpServers` entry; for Cursor place it in `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "standardsforge": {
      "command": "powershell.exe",
      "args": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\absolute\\path\\to\\standardsforge-ready-0.1.0a1\\standardsforge-mcp.ps1"]
    }
  }
}
```

Claude Code can register the identical process:

```powershell
claude mcp add standardsforge -- powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\absolute\path\to\standardsforge-ready-0.1.0a1\standardsforge-mcp.ps1"
claude mcp get standardsforge
```

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
