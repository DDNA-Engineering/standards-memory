# Local model integration

StandardsForge gives a model read-only, principal-bound access to the prepared local library. The model host launches the MCP process; StandardsForge does not call a model.

## Select StandardsForge in your chat

This repository includes a [StandardsForge plugin](../../plugins/standardsforge/.codex-plugin/plugin.json) and its [question-answering skill](../../plugins/standardsforge/skills/standardsforge/SKILL.md). Install the corpus and connect its MCP server using the platform instructions below first. If StandardsForge already answers through MCP, keep that connection.

Install the selectable plugin from the repository marketplace with a current Codex CLI:

```sh
codex plugin marketplace add DDNA-Engineering/standards-memory --ref main
codex plugin add standardsforge@standardsforge
codex plugin list --marketplace standardsforge --json
```

For a local source checkout, replace the first command with `codex plugin marketplace add .` from the repository root. The marketplace stores only this small skill plugin in the plugin cache; it does not copy the repository's local corpus or database. The plugin reuses an existing `standardsforge` or `standardsforge-local` MCP connection. It has no bundled server, credentials, machine-specific paths, network fallback or installation hook. Installing it does not install or upgrade the runtime or standards content.

Start a new chat after installation. In Codex CLI or the IDE extension, use `/skills` to select **StandardsForge**. Codex qualifies the skill name with its plugin name, so the explicit invocation is:

```text
$standardsforge:standardsforge Use only my installed database; no web. What does MIL-STD-25C say about general material notes? Include the exact edition, conditions and source pages.
```

In desktop surfaces that offer plugin mentions, type `@` and select **StandardsForge**. Supported Codex task views also offer **Sources -> Use plugins -> StandardsForge**. Select the installed entry in the picker; plain `@StandardsForge` text is not proof that the host selected it. If a local plugin is not visible, refresh the plugin list or restart the app. The exact selector depends on the host; this package does not register a universal `/standardsforge` command. See the host's [skill invocation](https://learn.chatgpt.com/docs/build-skills) and [plugin selection](https://help.openai.com/en/articles/20001256-plugins-in-chatgpt) documentation.

The skill works with the seven core read tools in published a6 and uses `browse_records`, `select_evidence` and `follow_references` only when the installed runtime advertises them. Selecting the plugin never makes source-only features appear in an older runtime. Missing connections or optional capabilities are reported explicitly.

### Installed-library answer scope

The skill and picker prompts default to the installed library only. An answer must retrieve exact MCP evidence, preserve its conditions and cite readable source passages. A missing connection, empty search, unavailable edition, unresolved reference or location-specific input is reported as a gap. Broad questions about a deployment location do not authorize web climate research, vendor recommendations or publisher lookups. External research requires an explicit user request and separate attribution.

The plugin supplies instructions, not a host-enforced tool restriction. A successful plugin install or MCP retrieval does not prove that a model avoided the web. Check the chat's actual tool trace when validating this workflow: it should retrieve local evidence before answering and contain no external research unless requested. Hosts that require a hard restriction must configure their web/browser tools separately. The plugin does not change those permissions.

## Start with the prepared release on Windows

On 64-bit Windows with CPython 3.12, download and extract the [prepared `v0.1.0a6` archive](https://github.com/DDNA-Engineering/standards-memory/releases/download/v0.1.0a6/standardsforge-ready-0.1.0a6.zip). Open PowerShell in the extracted directory and run:

```powershell
python .\setup.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
(Resolve-Path .\standardsforge-mcp.ps1).Path
```

For the published `v0.1.0a6` archive, run core setup first: it validates and indexes the already-compiled library and proves full-integrity doctor under the prepared policy. The second command installs the exact Windows MCP wheelhouse with package indexes disabled and proves a real stdio query. Use the printed absolute launcher path in your model host. Claude Desktop and Cursor both accept this `mcpServers` entry; use `%APPDATA%\Claude\claude_desktop_config.json` for Claude Desktop on Windows or `.cursor/mcp.json` for Cursor. JSON paths need doubled backslashes:

```json
{
  "mcpServers": {
    "standardsforge": {
      "command": "powershell.exe",
      "args": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\absolute\\path\\to\\standardsforge-ready-0.1.0a6\\standardsforge-mcp.ps1"]
    }
  }
}
```

Claude Code can register the identical process:

```powershell
claude mcp add standardsforge -- powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Resolve-Path .\standardsforge-mcp.ps1).Path
claude mcp get standardsforge
```

For Codex, register the same prepared launcher:

```powershell
codex mcp add standardsforge -- powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Resolve-Path .\standardsforge-mcp.ps1).Path
codex mcp get standardsforge
```

After the host connects, ask: "Use StandardsForge to list installed MIL-STD-810 editions, find the low-pressure section, and retrieve exact source-linked evidence with page, package identity, and coverage limits." The host should offer seven StandardsForge read tools. Search is discovery; retrieve an exact record before relying on its text.

## Configure Linux or macOS against prepared state

First run the prepared archive's offline core setup with `sh ./setup.sh`. Then create an MCP environment outside the prepared directory and install the exact code/MCP extra from PyPI:

```sh
MCP_VENV=/absolute/path/to/standardsforge-mcp-venv
PREPARED_ROOT=/absolute/path/to/standardsforge-ready-0.1.0a6
python3 -m venv "$MCP_VENV"
"$MCP_VENV/bin/python" -m pip install "standardsforge[mcp]==0.1.0a6"
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

Published a6 exposes these seven tools:

- `search`
- `list_documents`
- `resolve_document`
- `get_clause`
- `build_context`
- `enumerate_obligations`
- `diff_editions`

The current source runtime additionally exposes `browse_records`, `select_evidence` and `follow_references`. Use the connected server's tool inventory as the authority for availability.

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

User-facing evidence should show quoted passages with standard, edition, clause and physical PDF page citations. Full hashes and replay IDs remain in the underlying packet or optional audit details. The skill includes a dependency-free HTML source-sheet renderer for detailed packets; use a rendered preview for the primary evidence link, with raw JSON secondary. The renderer preserves every returned record and reports the packet's coverage limits. It formats a saved retrieval snapshot; it does not query, authorize or verify source files. See the [skill workflow](../../plugins/standardsforge/skills/standardsforge/SKILL.md).

## Security boundary

- The principal comes from trusted process startup configuration.
- Authorization is checked by the core and rechecked before results return.
- Imported pack rights claims are provenance and cannot grant access.
- Retrieved document text remains untrusted data, not instructions.
- Query paths do not fetch URLs, execute pack contents, create listeners, or invoke hidden network or model fallbacks.

Read the complete [model reading guide](../MODEL_READING_GUIDE.md) before building a host integration.

## Source checkout development

From a source checkout and isolated environment, `python -m pip install -e ".[mcp]"` installs the optional MCP dependencies. This path contains no prepared standards corpus. The GitHub prepared artifact and PyPI code package are separate channels; installing from PyPI does not install, download, or authorize standards content. The published `v0.1.0a6` uses page-text packs and an automated, unreviewed `outline-v3`; later source changes are not in that release or its PyPI wheel.
