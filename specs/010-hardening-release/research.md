# Research: Hardening and Release Readiness (P9)

No new Odoo-specific claims. The support statement derives from knowledge-base data (P3/P5) and runtime results (P7).

| Decision | Rationale | Alternatives |
|---|---|---|
| Deterministic synthetic corpus | Reproducible, no customer data | Real customer repositories (privacy, non-reproducible) |
| Budgets from the P2 baseline × documented headroom | No invented numbers; regression detection | Fixed guesses |
| Process pool with deterministic merge (sorted by module then path) | stdlib `concurrent.futures`; deterministic output | Threads (GIL-bound parsing), async (no benefit for CPU work) |
| Incremental index keyed by content + rule-set + tool version | Correct invalidation when rules change | mtime-based (unreliable across checkouts) |
| Hash-chained JSONL audit log | Tamper evidence with stdlib | Syslog/external service (deployment dependency) |
| Canary-secret scan over all artefacts | Direct evidence for REQ-AI-008 | Code review only |
| RTM completeness check as a test | Gate enforced in CI | Manual review |
