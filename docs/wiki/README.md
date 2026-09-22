# StandardsForge wiki

This wiki is the operating guide for StandardsForge. The root [README](../../README.md) stays focused on starting the prepared offline MIL-STD library; the pages here cover deeper use, integration, maintenance, trust, and release work.

## Choose a path

| Goal | Start here |
|---|---|
| Install the already-compressed offline library | [Prepared library](PREPARED_LIBRARY.md) |
| Search, pin editions, and retrieve evidence | [Query guide](QUERY_GUIDE.md) |
| Connect a local model through MCP | [Model integration](MODEL_INTEGRATION.md) |
| Refresh sources or rebuild packs | [Maintainer workflows](MAINTAINER_WORKFLOWS.md) |
| Understand evidence, authorization, and rights boundaries | [Architecture and trust](ARCHITECTURE_AND_TRUST.md) |
| Qualify a change or verify a release | [Validation and releases](VALIDATION_AND_RELEASES.md) |
| Contribute code or documentation | [Contributing](../../CONTRIBUTING.md) |
| Report a vulnerability | [Security policy](../../SECURITY.md) |

## Product references

- [Product baseline](../PRD.md)
- [Reference architecture](../ARCHITECTURE.md)
- [Decision index](../adr/README.md)
- [Model reading guide](../MODEL_READING_GUIDE.md)
- [Contracts](../../contracts/README.md)
- [Validation report](../../VALIDATION_REPORT.md)
- [Release evidence](../RELEASE_EVIDENCE.md)
- [Machine-readable backlog](../../backlog/tasks.json)

## Documentation rules

Wiki pages must distinguish:

- published release behavior from source-only or local development behavior;
- exact source evidence from derived structure and reviewed interpretation;
- public accessibility from processing, redistribution, and model-use permission;
- local validation from protected CI, publication, deployment, and user acceptance;
- a publisher-current snapshot from a project-approved engineering baseline.

Commands should name the expected working directory and operating context. Claims about counts, versions, dates, digests, or availability must point to a recorded artifact and be refreshed when that artifact changes.
