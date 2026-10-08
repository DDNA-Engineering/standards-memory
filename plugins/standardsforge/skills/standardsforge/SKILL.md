---
name: standardsforge
description: Answer defense engineering standards questions using the installed StandardsForge MCP library, with exact editions, source citations, conditions and review limits. Use for finding provisions, explaining scoped requirements, browsing standards or comparing installed editions; it does not certify compliance.
---

# StandardsForge

Use the operator-configured StandardsForge MCP tools to answer the user's question from installed source evidence. Common connection names are `standardsforge` and `standardsforge-local`; discover the available tools and use their declared arguments. The host fixes the database, principal, tokenizer and reviewed-reference configuration.

If no StandardsForge tools are available, report the missing connection and direct the user to the repository's [model integration guide](https://github.com/DDNA-Engineering/standards-memory/blob/main/docs/wiki/MODEL_INTEGRATION.md). Do not silently substitute web searches or remembered standard text, download a corpus, change host configuration, or install dependencies while answering a standards question.

## Retrieve evidence

1. Use `list_documents` when the installed identifier or representation is unknown, and `resolve_document` to establish the exact identifier, edition and representation. Retain the returned package digest. If edition ambiguity affects the answer, expose the choices rather than silently selecting the newest edition or a project baseline.
2. Use `search` to discover records. `natural_language` suits prose questions; use `concept_language` only when the installed tool advertises it, and treat expansions as discovery hints. Retrieve selected evidence with `get_clause` or assemble multiple records with `build_context`. Search snippets alone are insufficient support.
3. Preserve the returned governing conditions, exceptions, notes, dependencies and source citations. Follow pagination when the requested scope requires it. Use `enumerate_obligations` only within the package's declared classification coverage; zero classified obligations does not establish zero requirements.
4. Where advertised, use `browse_records` for structural navigation, `select_evidence` for measured complete evidence, and `follow_references` for explicitly reviewed cross-standard bindings. If a requested optional tool, tokenizer or binding is unavailable, state that limit. Do not claim measured token savings from ordinary compact output or infer a target edition from a reference's name.
5. Use `diff_editions` for an explicit comparison of installed editions, preserving each side's package identity and governing context.

## Answer the question

Lead with the answer supported by the retrieved text. Cite the exact standard and edition, clause or record, physical source page and replayable package/record identity supplied by the tools. Preserve qualifications that change the meaning of a provision. Separate source statements from your engineering interpretation and identify missing or unresolved evidence.

Keep representation and coverage visible where they affect confidence: page text is extracted evidence; derived outlines are automated and unreviewed; reviewed structure is reviewed only within its declared scope. Source verification, semantic review and human approval are separate. A reviewer-selected reference edition supports navigation, not contractual applicability. Do not infer project applicability, baseline approval, complete requirements coverage or compliance from retrieval success.
