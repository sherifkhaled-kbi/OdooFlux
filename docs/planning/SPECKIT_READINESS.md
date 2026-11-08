# Spec Kit Implementation Readiness

Status date: 2026-11-06. Spec Kit 1.3.1 (Claude integration, `sh` scripts, sequential feature
numbering, no git branches). Constitution **2.0.0**, maintainer approval pending (D-01).
`.specify/feature.json` points to `specs/001-safety-stabilization` (the first phase).

Readiness values:
- **READY**: can start now, once the planning package is approved.
- **READY_WITH_DEPENDENCIES**: fully specified; starts when the listed phases have exit evidence
  and the listed decisions are approved.
- **BLOCKED**: cannot start even after its dependencies, until the listed item is resolved.
- **INCOMPLETE**: planning artefacts are missing.

Workflow steps per feature: Specify, Clarify (session 2026-11-06 recorded in each `spec.md`;
maintainer-level questions deferred to `D-NN`), Plan, Tasks, Analyze (see
[SPECKIT_ANALYSIS_REPORT.md](SPECKIT_ANALYSIS_REPORT.md)). **Implement was not run for any
feature.**

## Dashboard

| Phase | Feature directory | Spec | Clarify | Plan | Tasks | Analyze | Official research | Dependencies | Readiness | Blocking issues |
|---|---|---|---|---|---|---|---|---|---|---|
| P0 | [specs/001-safety-stabilization](../../specs/001-safety-stabilization/) | Complete | Done | Complete (1 justified deviation) | 46 tasks, 30 tests | Pass | Sufficient: version facts cite EV-101/102/103/109/110 | None | **READY** | Approval of this planning package |
| P1 | [specs/002-test-foundation](../../specs/002-test-foundation/) | Complete | Done | Complete | 28 tasks, 11 tests | Pass | Not required | P0 | READY_WITH_DEPENDENCIES | — |
| P2 | [specs/003-core-architecture](../../specs/003-core-architecture/) | Complete | Done | Complete | 62 tasks, 40 tests (+2 P0 tests re-run) | Pass | Not required (data-driven versions) | P1; D-01, D-09 | READY_WITH_DEPENDENCIES | D-01 (constitution 2.0.0) and D-09 (pyproject) need approval |
| P3 | [specs/004-official-source-intelligence](../../specs/004-official-source-intelligence/) | Complete | Done | Complete | 26 tasks, 11 tests | Pass | Seeded: 55 EV records; gaps G-R-01…23 are tasks of this phase or later | P2 (code); P1 (data entry) | READY_WITH_DEPENDENCIES | — |
| P4 | [specs/005-structured-transformations](../../specs/005-structured-transformations/) | Complete | Done | Complete | 32 tasks, 15 tests | Pass | G-R-20 (modifier semantics) open; gates only the attrs fixer | P2; D-02 | READY_WITH_DEPENDENCIES | D-02 for the JS adapter part (fallback documented) |
| P5 | [specs/006-version-compatibility-rules](../../specs/006-version-compatibility-rules/) | Complete | Done | Complete | 59 tasks (16 research), 35 tests | Pass | Partial: 22 legacy rules need research; research tasks precede rules | P3, P4; D-04, D-05 | READY_WITH_DEPENDENCIES | Rules in unresearched areas stay DETECT_ONLY until research tasks close |
| P6 | [specs/007-ai-assistance](../../specs/007-ai-assistance/) | Complete | Done | Complete | 34 tasks, 17 tests | Pass | Not Odoo-specific | P3, P5; D-08, D-10 | READY_WITH_DEPENDENCIES | D-08 (AI data policy) needs approval |
| P7 | [specs/008-runtime-behavioral-validation](../../specs/008-runtime-behavioral-validation/) | Complete | Done | Complete | 29 tasks, 13 tests | Pass | Partial: G-R-13, G-R-21…23 are research tasks inside this phase | P2 (soft: P3 data); D-03, D-02 (RNG) | READY_WITH_DEPENDENCIES | D-03 (Docker) needs approval; runtime images for ≤17.0 unresolved (G-R-21) |
| P8 | [specs/009-reporting-ux](../../specs/009-reporting-ux/) | Complete | Done | Complete | 26 tasks, 13 tests | Pass | Not required | P2, P7 (soft: P6); D-06, D-07, D-10 | READY_WITH_DEPENDENCIES | — |
| P9 | [specs/010-hardening-release](../../specs/010-hardening-release/) | Complete | Done | Complete | 24 tasks, 11 tests | Pass | Not required | P5, P6, P7, P8 | READY_WITH_DEPENDENCIES | — |

No phase is BLOCKED or INCOMPLETE. Only P0 is READY.

## Notes that limit readiness

- **Version support claims.** No migration path can be advertised as supported until its steps
  reach `RULES_TESTED` and the target reaches `RUNTIME_VALIDATED`. Today every transition is at
  most `RESEARCH_SEEDED` ([VERSION_COMPATIBILITY_MATRIX.md](VERSION_COMPATIBILITY_MATRIX.md)).
- **Optional adapters.** P4 (JS), P7 (runtime, RNG), P6 (providers), and P8 (rich) can complete
  their stdlib parts if a decision is rejected. Each `tasks.md` documents the fallback.
- **Odoo 20.** Not inspected (G-R-19). It is added through the procedure in
  [MIGRATION_RULE_ENGINE.md](MIGRATION_RULE_ENGINE.md#adding-a-new-odoo-version) once released.

## Final readiness verification

| Check | Result |
|---|---|
| Spec Kit initialised correctly (1.3.1, templates, scripts, skills present) | Yes |
| Constitution prepared (2.0.0, Sync Impact Report) | Yes; approval pending (D-01) |
| Every feature has the required artefacts | Yes (10/10) |
| Planning workflow completed (specify → clarify → plan → tasks → analyze) | Yes, for all 10 features |
| Cross-artefact analysis performed | Yes ([SPECKIT_ANALYSIS_REPORT.md](SPECKIT_ANALYSIS_REPORT.md)) |
| Blocking gaps documented | Yes ([PLANNING_GAPS_AND_ASSUMPTIONS.md](PLANNING_GAPS_AND_ASSUMPTIONS.md)) |
| Roadmap matches Spec Kit features | Yes ([README.md](README.md#phase--spec-kit-feature-mapping)) |
| Handoffs reference the correct spec and task files | Yes (10/10) |
| Proposed project structure exists | Yes (`src/odooflux/`, `tests/`; 50 `.gitkeep`) |
| No functional application code implemented | Yes (application file hashes unchanged) |

**Overall:** planning is complete, and P0 is ready to implement once you approve the package.
Later phases are fully specified but wait on their dependencies and the pending decisions above.
