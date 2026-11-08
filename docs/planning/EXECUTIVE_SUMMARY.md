# Executive Summary

**OdooFlux** migrates custom Odoo addons to newer Odoo versions. This planning package turns
the current single-file tool into an implementation-ready, ten-phase project under GitHub
Spec Kit. **No functional code was written.** Existing application files are byte-identical to
before planning.

## Where the tool stands today

The current `odooflux.py` (1,801 lines, regex-based, targets 18/19) is a useful scanner but an
unsafe fixer. In a reproduction on a small v14 module, `--fix` produced:
- Python that does not compile;
- XML that is not well-formed;
- a report that claimed 22 fixes.

Analyze mode and `--dry-run` both write a file into the module. Backups land inside the addons
path, where Odoo sees them as duplicate modules. Several version claims in the rules are wrong
when checked against official Odoo source. A v19 migration would also silently drop
`_sql_constraints`, which 19.0 no longer applies.

Details: [CURRENT_ARCHITECTURE_AUDIT.md](CURRENT_ARCHITECTURE_AUDIT.md). It covers 52 earlier
findings (48 confirmed in the current code) and 19 new findings.

## What the target system is

- **Multi-version engine.** A request such as 14→19 is planned as consecutive steps
  (14→15 … 18→19). Versions are data, with no hardcoded maximum, so Odoo 20 is added through a
  documented procedure.
- **Evidence-only rules.** Every rule cites official Odoo documentation or source at a pinned
  commit SHA. Unverified claims may only be reported, never auto-fixed.
- **Safe edits.** Edits are targeted and traceable to a rule. The tool works on a copy,
  validates, then promotes with backups outside the addons path, a run log, rollback, and resume.
- **Layered validation.** Syntax → static → dependencies → runtime install in disposable
  containers → behavioural tests. The six result statuses are capped by the layers that actually
  ran (`VERIFIED_SUCCESS` … `BLOCKED`).
- **Optional, provider-neutral AI.** Off by default. Bounded to function-level regions, with
  token budgets and caching. Its output passes the same validation, plus protected-identifier
  checks.
- **One report model.** It is rendered to terminal, offline HTML, JSON, SARIF, and diff.

Design: [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md),
[ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) (16 ADRs),
[architecture/CONTRACTS.md](architecture/CONTRACTS.md).

## Official research done

Official `odoo/odoo` and `odoo/documentation` repositories were checked at pinned SHAs for
12.0–19.0, plus `odoo/docker`. That produced **55 evidence records** and **23 documented
research gaps**. The evidence corrects several assumptions:
- `@api.returns` is removed only in 19.0.
- `@api.one`/`@api.multi` were removed in 13.0.
- `odoo.exceptions.Warning` was removed in 17.0.
- The `rpc` service was replaced in 18.0.

Every version transition is at most `RESEARCH_SEEDED`. None is claimed as supported.

See [research/OFFICIAL_EVIDENCE_REGISTER.md](research/OFFICIAL_EVIDENCE_REGISTER.md) and
[VERSION_COMPATIBILITY_MATRIX.md](VERSION_COMPATIBILITY_MATRIX.md).

## Plan

| Phase | Title | Readiness |
|---|---|---|
| P0 | Safety Stabilization | **READY** |
| P1 | Test Foundation | Ready after P0 |
| P2 | Core Architecture | Ready after P1 + D-01, D-09 |
| P3 | Official Source Intelligence | Ready after P2 |
| P4 | Structured Transformations | Ready after P2 + D-02 |
| P5 | Version Compatibility Rules | Ready after P3, P4 + D-04, D-05 |
| P6 | AI Assistance | Ready after P3, P5 + D-08 |
| P7 | Runtime and Behavioral Validation | Ready after P2 + D-03 (parallel to P3–P6) |
| P8 | Reporting and UX | Ready after P2, P7 |
| P9 | Hardening and Release | Ready after P5–P8 |

The plan has 92 requirements, 366 tasks, and 196 test IDs. Traceability is complete:
[REQUIREMENTS_TRACEABILITY_MATRIX.md](REQUIREMENTS_TRACEABILITY_MATRIX.md).

## Decisions needed from the maintainer

| ID | Decision | Default in the plan |
|---|---|---|
| D-01 | Approve constitution 2.0.0 (stdlib core + optional adapters, replacing "single file only") | Approve |
| D-02 | JS parser adapter and RNG validation | tree-sitter; lxml |
| D-03 | Runtime validation technology | Docker containers |
| D-04 | Lowest source version for the first release | 14.0 |
| D-05 | Enterprise source access | None (Enterprise out of scope) |
| D-06 / D-07 | HTML report tech / rich terminal | Static stdlib HTML / optional rich |
| D-08 | AI data policy and default provider | Accepted (ADR-017): external-first provider type; AI off until enabled; explicit per-provider data authorization; DeepSeek and Z.ai added; new items need spec amendment |
| D-09 | Introduce `pyproject.toml` in P2 | Yes, with optional extras |
| D-10 | Legacy CLI deprecations at cut-over | e.g. remove `--api-key` |

Full list: [PLANNING_GAPS_AND_ASSUMPTIONS.md](PLANNING_GAPS_AND_ASSUMPTIONS.md).

## Top risks

These are the main risks in [RISK_REGISTER.md](RISK_REGISTER.md) (21 risks):
1. Silent business-logic changes.
2. Incomplete official documentation for older versions (12–15).
3. Runtime validation limits, including no official images for ≤17.0 at `odoo/docker` master.
4. Incorrect AI patches.
5. Scope and complexity growth.

## Next step

Approve the planning package, then implement **P0**:
[phase-handoffs/PHASE_00_SAFETY.md](phase-handoffs/PHASE_00_SAFETY.md) with
`specs/001-safety-stabilization` (already selected in `.specify/feature.json`).
