# Risk Register

Scale:
- **Severity** (impact if it occurs): Critical / High / Medium / Low.
- **Likelihood**: High / Medium / Low.

Likelihood is a planning judgement, not a measured probability. Owners are roadmap phases
([IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)). Pending decisions `D-NN` are in
[PLANNING_GAPS_AND_ASSUMPTIONS.md](PLANNING_GAPS_AND_ASSUMPTIONS.md).

## Product and technical risks

| ID | Risk | Severity | Likelihood | Impact | Detection | Mitigation | Residual risk | Phase | Related |
|---|---|---|---|---|---|---|---|---|---|
| RSK-001 | Invalid transformations: fixers emit unparsable Python/XML/JS (current behaviour, F-PY-1/2, F-XML-1) | Critical | High (today) | Modules fail to load or install | Syntax validation gate; golden fixtures; idempotence tests | P0 gate + removal of unsafe fixers; span-based edits (ADR-003) | Low after P0/P4: only syntax-valid output is promoted | P0, P4 | REQ-SAF-002, REQ-SAF-010, REQ-TRF-003 |
| RSK-002 | Silent business-logic changes (e.g., `@api.one` removal, `sudo(False)`, `_sql_constraints` dropped in 19.0) | Critical | High | Wrong data, security bypass, lost constraints in production | `review_required` rules; behavioural layer; constraint inventory | Semantics-changing constructs are detect-only + review (Principle VIII); behavioural comparison (P7) | Medium: behaviour not covered by module tests remains unverified, and this is disclosed | P0, P5, P7 | REQ-PY-003, REQ-BIZ-001…003, NF-05 |
| RSK-003 | Missing compatibility rules lead to a "clean" report on incompatible code | High | High | False confidence; failures at install | Matrix coverage; runtime install layer; research records per step | Step research records; status capped when steps are not researched; runtime validation | Medium until all steps are `RULES_TESTED` | P3, P5, P7 | REQ-VER-003, REQ-VAL-004 |
| RSK-004 | Incomplete official documentation (no ORM changelog before 15.2; G-R-01) | High | High | Rules for 12→15 are hard to evidence | Evidence register gaps; matrix `NOT_ASSESSED` | Source-diff research at pinned SHAs; those steps stay detect-only until evidenced | Medium: some changes may be found only at runtime | P3, P5 | REQ-EVD-001, G-R-01 |
| RSK-005 | Incorrect AI-generated patches | High | Medium | Broken or semantically altered code | Validation layers; protected-identifier diff; re-scan | AI only for eligible findings; Edit-level output; same validators; never auto-promote review-required | Low–Medium: semantics errors that pass validation are possible and disclosed | P6 | REQ-AI-002, REQ-AI-003 |
| RSK-006 | Excessive token usage and cost | Medium | Medium | Cost overrun; slow runs | Per-request/file/module/job budgets; usage report | Region-level context, caching, model selection, hard budgets | Low | P6 | REQ-AI-004…007 |
| RSK-007 | Dependency incompatibility: removed or renamed core modules in `depends`, third-party Python packages | High | Medium | Install failure | Layer 3 dependency validation; runtime install | Per-version core module lists from evidence; findings for unknown dependencies | Medium for third-party/OCA modules not in core lists | P5, P7 | REQ-DEP-001, REQ-VAL-003 |
| RSK-008 | Security regressions in migrated modules (ACL/record-rule references, `auth`, `csrf`, `t-raw`) | High | Medium | Data exposure in customer systems | ACL scanning; runtime access checks; security-pattern rules | REQ-ACL-001/002; review-required security findings | Medium: business-level authorisation intent cannot be verified statically | P5, P7 | REQ-ACL-001, REQ-ACL-002 |
| RSK-009 | Customer data/code exposure (AI requests, logs, debug files written into modules) | Critical | Medium | Confidentiality breach | Secret scanning; audit log; tool-artefact check in modules | AI off by default + consent (D-08); minimal context; outputs only in state dir; redaction | Low | P0, P6, P9 | REQ-SEC-003, REQ-AI-008, REQ-SEC-005 |
| RSK-010 | Runtime test limitations: no Docker, unavailable images, Enterprise dependencies, external services | High | High | Cannot reach `INSTALL_VERIFIED` | Validator outcome `UNAVAILABLE` | Status capping (REQ-VAL-006); documented setup; optional intermediate validation | Medium: many users will get `STATIC_VALIDATED` at best, and the report says so | P7 | REQ-VAL-004, D-03 |
| RSK-011 | No Enterprise source access | Medium | High | Rules for Enterprise APIs impossible; Enterprise-dependent modules not runtime-validated | Dependency scan flags Enterprise modules | Out of scope by default (D-05); `BLOCKED`/`NEEDS_REVIEW` with explanation | Medium | P3, P5, P7 | D-05, G-R-02 |
| RSK-012 | Unsupported versions requested (pre-12.0, future 20.0 before research) | Medium | Medium | Wrong output if processed | Version graph `blocked_steps` | Refuse or downgrade explicitly (REQ-VER-003); data-only version addition | Low | P2, P3 | REQ-VER-003, REQ-VER-005 |
| RSK-013 | Performance bottlenecks on large repositories (hundreds of modules), runtime layer dominant | Medium | Medium | Slow CI; timeouts | Benchmarks (P2 baseline, P9 budgets) | Incremental hashing, process pool, batched runtime per target | Low–Medium | P2, P9 | REQ-PRF-001…004 |
| RSK-014 | Architectural complexity outgrows the team (many registries/adapters) | Medium | Medium | Slow delivery; inconsistent plugins | Contract tests; review of complexity tracking in plans | Stdlib core, few contracts, one Edit model; phases gated | Low–Medium | P2 | REQ-ARC-002, Principle IX |
| RSK-015 | Backward compatibility of the CLI and JSON report for existing users | Medium | Medium | Broken scripts/CI | Characterisation suite | Aliases for one release; documented differences; schema mapping (D-10) | Low | P2, P8 | REQ-ARC-004, REQ-TST-004 |
| RSK-016 | Scope creep (data migration, Enterprise, IDE integrations) | Medium | High | Phases never finish | Phase exit criteria; non-goals list | Explicit non-goals in [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md#non-goals-explicit); Principle X | Low | All | Principle X |

## Planning-specific risks

| ID | Risk | Severity | Likelihood | Impact | Detection | Mitigation | Residual risk | Phase | Related |
|---|---|---|---|---|---|---|---|---|---|
| RSK-017 | Evidence pinned to branch-tip SHAs drifts: later commits on stable branches change behaviour | Medium | Medium | Rules based on stale evidence | Refresh workflow re-checks locations at new SHAs | Pin per record; scheduled refresh (REQ-EVD-005); prefer release tags when available | Low | P3 | REQ-EVD-005 |
| RSK-018 | Odoo Online x.1–x.4 mapping to the next major is wrong for some change (e.g., backported to the previous major's stable branch) | Medium | Low | Rule applied at the wrong step | Verify each Online-release claim in the on-premise source at both majors | Every rule's step must be confirmed in source at the pinned SHAs (ADR-007) | Low | P3, P5 | ADR-007 |
| RSK-019 | Optional adapters unavailable in user environments (tree-sitter, lxml, Docker) | Medium | High | Lower result statuses; JS edits disabled | Adapter `available()` checks surfaced in reports | Graceful downgrade to `NEEDS_REVIEW`; installation docs | Medium: capability depends on environment | P4, P7 | ADR-002, D-02, D-03 |
| RSK-020 | Constitution 2.0.0 not approved | High | Low | P2+ design (package, adapters) conflicts with governance | D-01 status | Phases P0–P1 are valid under both 1.0.0 and 2.0.0; P2 is blocked until D-01 is approved | Low | P2 | D-01, ADR-002 |
| RSK-021 | Planning claims treated as verified behaviour | High | Medium | Rules built on `DOCUMENTED_NOT_TESTED` evidence assumed safe | Rule maturity gates; review | ADR-008: fixers need tests; evidence `VERIFIED` only after runtime | Low | P3, P5 | ADR-008 |
