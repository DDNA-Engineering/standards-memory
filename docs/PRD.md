# StandardsForge product baseline

Document `SM-PRD-001`, version `0.1.0-design`, is a proposed baseline derived from the supplied PRD. Product and release ownership remain unassigned.

The product compiles authorized technical documents into immutable, source-linked packs and returns the smallest sufficient evidence for a task while keeping exact edition, governing conditions, unresolved inputs, and completeness visible. Correct engineering-information work is the outcome; fast search or fluent prose alone is not success.

The standalone core owns source identities, exact citations, package validation, deterministic local retrieval, coverage accounting, and portable exports. Host systems own project baselines, applicability, decisions, and approvals. Public accessibility, processing permission, model permission, and redistribution permission are separate decisions.

The distribution model has two explicit artifacts. The source-only repository carries the compiler, contracts, and synthetic examples. The prepared end-user release carries verified precompiled packs for the recorded public DLA baseline and performs only local validation and indexing on first run; users do not reacquire or recompile that baseline. Each user still owns local state and authorization. A hosted multi-tenant service is not a product target, and optional host integrations remain consumers of the same local core.

Supported jobs are authorized installed-document inventory, exact identifier lookup, record evidence retrieval, lexical discovery, scoped exhaustive traversal, edition comparison, evidence packet assembly, official-source verification, deterministic PDF and corpus compilation, unreviewed outline derivation, reviewed structural compilation, and guided local model use. The implemented baseline includes strict pack validation, policy-bound installation, seven deterministic read operations, a principal-bound stdio MCP adapter, detailed/compact/concise responses, request-local integrity verification, bounded authorization-safe caches, compressed pack transport, and explicit representation selection. Inventory and near-match candidates remain authorization-filtered and exact or prefix-based, without fuzzy, network, or model fallback. Structural required edges must agree with retrieval dependencies; page and derived evidence are bound to exact UTF-8 sidecar offsets; and mixed public/restricted component sets remain explicitly incomplete.

The text layer of real PDFs is compiled into page records, a separate deterministic pass emits unreviewed outline candidates and explicit unsupported regions, and one explicitly reviewed section is compiled into structural nodes and relationships. No document-wide runtime claim is made for visual fidelity, OCR, reviewed semantic clause segmentation, table-cell or figure-visual interpretation, obligation classification, HTTP serving, catalog synchronization, certification, or controlled workloads. Hosted-service and tenant-isolation requirements from the supplied PRD are out of scope for this local distribution model. Numerical quality targets in the supplied PRD remain unmeasured release targets.

## Invariants

1. Preserve original source bytes, original and normalized identifiers, edition composition, conditions, exceptions, and unsupported regions.
2. Keep source facts, derived records, deterministic checks, and human approval separate.
3. Do not treat catalog currentness as a project baseline or candidate relevance as applicability.
4. Do not satisfy exhaustive retrieval with top-k search.
5. Do not omit required evidence to fit a budget while marking the packet complete.
6. Do not grant access from pack-supplied rights claims.
7. Do not make query paths fetch, import, activate, publish, or execute content.

The machine-readable acceptance subset for the implemented slice is in `docs/requirements/requirements.json`.
