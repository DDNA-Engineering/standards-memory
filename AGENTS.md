# Coding-agent instructions

This package is the build baseline for StandardsForge, a standalone open-source standards compiler and evidence engine. Integrations are consumers, not core dependencies.

Read `START_HERE.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, the relevant ADRs, and the selected record in `backlog/tasks.json` before implementation. Preserve exact sources, edition/package identities, conditions, and exceptions. Keep source evidence, derivations, automated checks, and human approval separate.

Query tools are read-only. They must never fetch arbitrary URLs, execute pack contents, grant permissions from imported rights claims, or use hidden network/model fallbacks. Authorization comes from trusted local policy integration, and every returned packet is reauthorized.

Implement one bounded vertical slice at a time with its negative cases. Do not claim runtime behavior that has not been observed. Do not commit or publish without explicit user direction.
