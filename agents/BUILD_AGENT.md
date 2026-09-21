# Build agent workflow

Select one task from `backlog/tasks.json`. State its requirement IDs, expected files, and tests. Preserve contracts unless schemas, examples, requirements, and affected tests are updated together.

For every implementation slice:

1. Keep query operations read-only and network-free by default.
2. Treat imported rights as claims and operator policy as authority.
3. Return typed errors or explicit incomplete states for missing capabilities.
4. Test the positive path and task-specific negative cases.
5. Report exact commands and observed results; do not relabel planned checks as passed.

Do not commit, publish, ingest restricted sources, or mutate a host baseline without explicit authorization.
