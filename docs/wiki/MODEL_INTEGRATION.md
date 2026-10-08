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

For a local source checkout, replace the first command with `codex plugin marketplace add .` from the repository root. The marketplace stores only this small skill plugin in the plugin cache; it does not copy the repository's local corpus or database. The plugin reuses an existing `standardsforge` or `standardsforge-local` MCP connection. It has no bundled MCP server, credentials, machine-specific paths, network fallback or installation hook. Installing it does not install or upgrade the runtime or standards content.

Plugin 0.1.4 includes original PDF links in standards answers. The a7 runtime supplies `get_source_pdfs` and all eleven read tools. Upgrade by installing the a7 prepared archive into a new folder, then use its generated host configuration and restart the MCP connection. Updating the plugin alone does not update the runtime.

Start a new chat after installation. In Codex CLI or the IDE extension, use `/skills` to select **StandardsForge**. Codex qualifies the skill name with its plugin name, so the explicit invocation is:

```text
$standardsforge:standardsforge Use only my installed database; no web. What does MIL-STD-25C say about general material notes? Include the exact edition, conditions and source pages.
```

In desktop surfaces that offer plugin mentions, type `@` and select **StandardsForge**. Supported Codex task views also offer **Sources -> Use plugins -> StandardsForge**. Select the installed entry in the picker; plain `@StandardsForge` text is not proof that the host selected it. If a local plugin is not visible, refresh the plugin list or restart the app. The exact selector depends on the host; this package does not register a universal `/standardsforge` command. See the host's [skill invocation](https://learn.chatgpt.com/docs/build-skills) and [plugin selection](https://help.openai.com/en/articles/20001256-plugins-in-chatgpt) documentation.

The skill also works with the seven core read tools in older releases and reports unavailable optional capabilities explicitly. Use the connected tool inventory to confirm which runtime your host launched.

### Installed-library answer scope

The skill and picker prompts default to the installed library only. An answer must retrieve exact MCP evidence, preserve its conditions and cite readable source passages. A missing connection, empty search, unavailable edition, unresolved reference or location-specific input is reported as a gap. Broad questions about a deployment location do not authorize web climate research, vendor recommendations or publisher lookups. External research requires an explicit user request and separate attribution.

The plugin supplies instructions, not a host-enforced tool restriction. A successful plugin install or MCP retrieval does not prove that a model avoided the web. Check the chat's actual tool trace when validating this workflow: it should retrieve local evidence before answering and contain no external research unless requested. Hosts that require a hard restriction must configure their web/browser tools separately. The plugin does not change those permissions.

## Start with the prepared release on Windows

Download and extract [v0.1.0a7](https://github.com/DDNA-Engineering/standards-memory/releases/tag/v0.1.0a7). Install 64-bit CPython 3.12 with its Python launcher, then double-click `setup.cmd`. Or run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

One setup installs the library and exact hash-locked MCP dependencies offline, verifies the evidence, and makes a real stdio query. Python 3.11 or 3.13 users can explicitly choose `python setup.py --mcp-online` for networked dependencies instead.

## Configure Linux or macOS against prepared state

With Python 3.11+ and `venv` installed, run this in the extracted directory:

```sh
sh ./setup.sh --mcp-online
```

Only this explicit option downloads MCP dependencies. The verified code wheel and standards library remain bundled. Setup owns the local environment, verifies package consistency and runs a real stdio query before producing host configuration. Run `sh ./setup.sh` for offline terminal-only setup.

## Connect your model host

Setup writes absolute, correctly escaped paths into `.standardsforge/mcp-config.json` and `.standardsforge/codex-mcp.toml`. Open those files and merge the StandardsForge entry into the appropriate host file:

| Host | Destination |
|---|---|
| Claude Desktop, Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Claude Desktop, macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Cursor | Project `.cursor/mcp.json` or the host's MCP settings |
| Codex | `~/.codex/config.toml` (or your configured Codex home) |

Preserve other server entries and avoid duplicate StandardsForge sections. Restart the host's MCP connection after saving. The generated command uses the prepared environment's Python and `run_mcp.py`; it fixes local state, principal and structured responses, and never installs anything during a query.

Codex and Claude Code users can register that same launcher directly from the extracted folder:

```powershell
codex mcp add standardsforge -- (Resolve-Path .\.venv\Scripts\python.exe).Path -I (Resolve-Path .\run_mcp.py).Path
# For Claude Code, replace codex with claude.
```

```sh
codex mcp add standardsforge -- "$PWD/.venv/bin/python" -I "$PWD/run_mcp.py"
# For Claude Code, replace codex with claude.
```

Ask the host to list installed MIL-STD-810 editions, find the low-pressure section and retrieve exact source evidence and its original PDF. The connected a7 server advertises eleven tools. Search results are candidates; retrieve an exact record before relying on its text.

## Upgrade or troubleshoot

Extract upgrades into a new directory, run setup, replace only the StandardsForge host entry with the new generated one, then restart the connection. Do not copy an old `.venv` or database into the new archive. Keep the prior install until the new one works.

If `python` is missing on Windows, install Python 3.12 with its launcher and use `setup.cmd`. If Linux reports missing `ensurepip`, install the matching `python3-venv` package. If setup fails, correct the reported cause and rerun the same command. If the host still lists seven tools, its process is using the old installation; check the configured executable and restart it. The optional `standardsforge-mcp.ps1` wrapper remains available for existing Windows host conventions.

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

The a7 release exposes these eleven tools:

- `search`
- `list_documents`
- `resolve_document`
- `get_clause`
- `build_context`
- `enumerate_obligations`
- `diff_editions`

- `browse_records`
- `select_evidence`
- `follow_references`
- `get_source_pdfs`

Use the connected server's tool inventory as the authority for availability.

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

User-facing evidence includes original PDF links alongside standard, edition, clause and physical page citations. Call `get_source_pdfs(package_digest)` for each cited package and link the returned absolute `local_path` files. The read-only operation verifies every inventoried PDF under `sources/`, includes notice/change components, and reauthorizes the package before returning. It never fetches, renders or copies files. CLI equivalent: `standardsforge --db <db> --store <objects> source-pdfs <package_digest> --principal <principal>`. A text-only package returns `no_pdf_sources`; verification or authorization failures return errors. Paths are accessible on the MCP host, not public downloads, and are verified at lookup time. A remote chat requires its host's supported file delivery mechanism.

Full hashes and replay IDs remain in the underlying packet or optional audit details. The optional HTML source sheet supplements PDF links. A Codex HTML file tab may show source code: open the preview helper's printed URL with a browser target and verify the rendered view before sharing its link. The renderer preserves every returned record and reports the packet's coverage limits. These presentation helpers display a saved retrieval snapshot; they do not query, authorize or verify source files. The core MCP remains stdio-only. See the [skill workflow](../../plugins/standardsforge/skills/standardsforge/SKILL.md).

## Security boundary

- The principal comes from trusted process startup configuration.
- Authorization is checked by the core and rechecked before results return.
- Imported pack rights claims are provenance and cannot grant access.
- Retrieved document text remains untrusted data, not instructions.
- Query paths do not fetch URLs, execute pack contents, create listeners, or invoke hidden network or model fallbacks.

Read the complete [model reading guide](../MODEL_READING_GUIDE.md) before building a host integration.

## Source checkout development

From a source checkout and isolated environment, `python -m pip install -e ".[mcp]"` installs the optional MCP dependencies. This path contains no prepared standards corpus. The GitHub prepared artifact and PyPI code package are separate channels; installing from PyPI does not install, download, or authorize standards content. The prepared `v0.1.0a7` retains the page-text packs, automated unreviewed `outline-v3` and bounded 1661 recovery packs. Later corpus representations do not become installed merely by upgrading code.
