# Research: AI Assistance (P6)

No Odoo-specific compatibility claim is made in this feature: AI never originates rules (FR-013). Evidence used in prompts is taken from the knowledge base built in P3.

| Decision | Rationale | Alternatives considered |
|---|---|---|
| Region-level replacement (ADR-012) | Smallest context, simple validation, no whole-file drift | Whole-file rewrite (legacy; caused truncation F-AI-2 and stale context F-AI-1); unified diffs from model (fragile line anchoring) |
| stdlib `urllib` transport by default | Principle I; legacy already used it | Mandatory SDKs (adds core deps) |
| Structured JSON response with schema check | Deterministic parsing, explicit rejection codes | Free-text extraction (legacy brace search) |
| Cache key includes prompt template version and evidence IDs | Invalidate when prompts or evidence change | Content-hash only (stale after rule changes) |
| Budgets enforced pre-send using estimates, reconciled post-response | Prevents overspend; honest reporting of estimate vs actual | Post-hoc accounting only |
| Consent flag separate from enable flag (D-08) | Explicit data-sharing decision | Single flag (consent implied) |
| Bounded retries on 429/5xx/timeouts only | Avoid cost loops | Unbounded or retry on all errors |
| Model/pricing as configuration | Model names and prices change; Principle VI forbids asserting them | Hardcoded model ID (legacy `CLAUDE_MODEL`) |

## Lessons from the current implementation

From [../../docs/reviews/ODOO_MODULE_UPGRADER_AUDIT.md](../../docs/reviews/ODOO_MODULE_UPGRADER_AUDIT.md): F-AI-1 (stale line numbers), F-AI-2 (single bundle, truncation unchecked), F-AI-4 (all issues marked fixed), F-AI-5 (filename key collision), F-AI-6 (hardcoded model, key on CLI, debug file in module), F-AI-7 (no protected-identifier check). Each maps to a task in [tasks.md](tasks.md).

## Open items

- D-08 approval (data policy). D-10 approval (CLI deprecation window).
- Provider-specific prompt-caching features are used only when the adapter reports support; no assumption about any provider's current behaviour is made here.
