# Framework Completion Plan

Status: PROPOSAL, pending owner decisions OD-1 to OD-8 (section 9). Written 2026-11-07. Planning only: no code, no spec edit, no task marker changed, nothing committed.

Owner direction: finish the OdooFlux Framework first. Expand the Odoo Knowledge Base (KB) afterwards, independently. This is a sequencing decision. It does not relax framework correctness, safety, or any independent-review requirement that still applies.

Companion: [KNOWLEDGE_BASE_BACKLOG.md](KNOWLEDGE_BASE_BACKLOG.md).

## 1. Classification

| Class | Meaning | Examples (existing) |
|---|---|---|
| A. Framework core, required now | Machinery that must work regardless of how many rules exist | orchestrator, parsers/adapters, rule engine and `bind_rule`, planner, validation layers, AI gateway, reports, packaging, recovery |
| B. Minimal validation corpus, required now | Smallest authoritative data that proves the framework | one migration path, its rules, fixtures, positive/negative tests, unsupported/missing-evidence handling |
| C. KB expansion, deferred | Breadth of Odoo knowledge | other transitions, further rules and renames, 234 removed-module successors, golden corpus of 42 cases, research peer review |

Rule for future triage: a task is class A/B if removing it would make a framework behaviour untestable. It is class C if it only raises coverage.

### Evidence base for this plan (checked today)
- Open tasks: 002 = 28 of 28, 006 = 4 (T025, T035, T044, T059), 007 = 50 of 50, 008 = 1 (T029), 009 = 26 of 26, 010 = 24 of 24. Features 001, 003, 004 and 005 are complete.
- **Finding F-1: Feature 002 (Test Foundation) was never executed.** All 28 tasks are unmarked. `tests/_support/`, `tests/golden_fixtures/INDEX.json` and `tests/regression/INDEX.md` do not exist. Later features built their own tests (1037 pass), so the phase was skipped in practice, not blocked. It needs a reconciliation task (FC-0.1), not a rebuild.
- **Finding F-2: Wiring gaps.** The dependency scanner and the planner's per-run `target` parameter have no production caller. They are exercised only by tests. `build_plan` in [plan.py](../../src/odooflux/core/orchestrator/plan.py) takes no rule run parameters.
- **Finding F-3: Packaging gap.** `[tool.setuptools.package-data]` ships only `knowledge/*.json`. The 200 evidence records, `compatibility/*` (including 4.87 MB of view index) and `schemas/` would be missing from a built wheel. No wheel has been built or tested.
- **Finding F-4: KB dependencies leaked into framework phases.** See section 2.

## 2. Where framework completion currently depends on KB coverage

| Where | Dependency | Genuine framework need? |
|---|---|---|
| 006 SC-002, SC-003 | every step 14-15 to 18-19 `RESEARCHED`/`RULES_TESTED`; byte-match for all pairs | No. Coverage target. Keep, but scoped to the validation corpus for the framework gate |
| 006 T025 | peer review of research for all five steps | Partly. Records cited by minimal-corpus rules need review. The rest is KB |
| 006 T035, T044 | golden expected trees for 17.0 to 18/19 and 14/15/16 to later | Partly. One path needs independently reviewed expected trees. The rest is KB |
| 006 T059 | quickstart on `17.0/kbi_demo` after T035/T044 | Yes, but only for the minimal path |
| 008 T029 | mark `RUNTIME_VALIDATED` for targets with passing runtime fixtures; blocked behind T025 | The generator capability is framework. Marking all targets is KB |
| 007 prerequisites (PHASE_06) | "P3 and P5 exit criteria met" | Over-stated. 007 needs the rule metadata contract (`ai_eligible`, `review_required`), which exists. It does not need full P5 coverage |
| 010 T006/SC-005 | path supported only if every step `RULES_TESTED` and target `RUNTIME_VALIDATED` | Keep as is. It is a safety rule. With a minimal corpus it simply yields a short supported list |
| 010 T003/T005 RTM completeness | every REQ needs a passing test or record | Needs a `DEFERRED_KB` status, otherwise deferral breaks the release gate |
| 002 T010-T016 | seven fixture modules for versions 12-18 | Mostly KB. Framework needs one or two fixtures |

## 3. Framework completion definition (owner criteria, made testable)

| # | Criterion | Gate test or evidence |
|---|---|---|
| C1 | Supported workflow runs end-to-end from an installed wheel | FC-E2E: install wheel into a clean venv, migrate the validation path, promote, rollback, resume |
| C2 | Parsers and transform engines correct | existing 004/005 suites, idempotence corpus |
| C3 | Rules load and run from version-specific data | loader coverage test (006 SC-001) plus F-2 wiring tests |
| C4 | AI providers configurable and safely integrated | 007 suites; no-fallback, kill switch, authorization, secret-absence |
| C5 | Validation layers execute correctly | 008 suites; Docker tests opt-in but executed once for the gate and recorded |
| C6 | Unsupported cases reported explicitly | tests that an unknown version, missing evidence, unavailable index and DETECT_ONLY rule each produce an explicit report entry, never a silent pass |
| C7 | Packaging contains all runtime assets | FC-PKG: wheel content test comparing the wheel with the files the loader reads |
| C8 | Automated tests pass | full suite, 0 failures |
| C9 | Representative end-to-end migration verified | the validation path, with independently reviewed expected output |

KB coverage is not a criterion. `knowledge validate` and `matrix --check` stay as integrity gates, because they guard what already exists.

## 4. Minimal validation corpus (class B)

Proposed single path: **17.0 to 18.0** (recommendation, see OD-2).
- Rules for 17-18 already exist and are tested (`17-18.*`, including detect-only rules and `kanban-box` handling).
- Target 18.0 has an official `odoo/docker` image, which avoids feature 008's gap G-R-21 (no images for 17.0 and below) for the target-side install check. A source-side image for behavioural comparison may still need a build from pinned source. This is a known limit and must be reported, not hidden.
- Multi-step orchestration is already covered by synthetic-version tests. FC-E2E adds one 16.0 to 18.0 run asserting a two-step plan and report, without byte-exact expectations.

Contents:
1. Fixture `tests/golden_fixtures/17.0/kbi_demo` (the path T059 already names).
2. Expected tree `expected/18.0` plus rule report, **independently reviewed** (T035-min).
3. Negative cases: a DETECT_ONLY rule yields no edit (SC-005), a missing run parameter yields an INFO gap, an unavailable view index yields INFO, an unknown target is rejected.
4. Peer review (T025-min) of only the evidence records cited by the 17-18 rules that the fixture exercises.

No new migration rules are added unless a framework test cannot be written without one. Any such rule needs an owner-approved line in this plan.

## 5. Proposed specification amendments

Each is a proposal. Approved text is not removed. Original wording stays visible, marked superseded, with the original task ID kept.

| ID | Target | Amendment | Reason |
|---|---|---|---|
| A-1 | 006 tasks T035, T044 | Split into `T035-min` (17.0 to 18.0 only; required for framework gate) and residual items moved to KB backlog KB-006-T035r / KB-006-T044r. Independent review still required for `T035-min` | F-4 |
| A-2 | 006 task T025 | Split into `T025-min` (records cited by the minimal corpus) and residual KB-006-T025r | F-4 |
| A-3 | 006 task T059 | Done-when limited to the minimal path. Full quickstart set stays as KB-006-T059r | F-4 |
| A-4 | 006 SC-002, SC-003 | Add "Framework gate scope: the validation path. Full scope tracked in KB backlog". Statement of the full target stays | F-4 |
| A-5 | 006 new Phase 11 | Add T079-T084: wire planner `target` and rule run parameters (FR-017); wire dependency scanner into the pipeline; resolve REQ-MAN-002 opt-out (OD-4); add integration test for each | F-2 |
| A-6 | 008 task T029 | Split: `T029-gen` (generator marks `RUNTIME_VALIDATED` only from a recorded passing run) required; `T029-data` limited to the validation path; residual KB-008-T029r. Dependence on T025 replaced by dependence on `T025-min` | F-4 |
| A-7 | 007 plan/PHASE_06 prerequisites | Replace "P5 exit criteria met" with "rule metadata contract available (`ai_eligible`, `review_required`) and minimal corpus gate passed". D-08 remains binding | over-stated prerequisite |
| A-8 | 010 RTM checker (T003, T005) | Add status `DEFERRED_KB` with mandatory backlog ID. A REQ with no passing test and no backlog ID still fails | keeps the gate honest |
| A-9 | 010 support statement (T006, T007) | No change to the rule. Add a required section "Not yet supported (knowledge pending)" so deferred paths are listed explicitly | C6 |
| A-10 | 010 new tasks T025-T027 | Packaging: wheel asset list, wheel build and install test, `package-data` fix (F-3) | C7 |
| A-11 | 002 | Add `FC-0.1` reconciliation: map each of 28 tasks to done-by-other-feature / required / deferred. Keep v14 plus one 17.0 fixture as required; v12, v13, v15, v16, v18 fixtures go to KB | F-1 |
| A-12 | IMPLEMENTATION_ROADMAP.md | Add the framework-first ordering and the dependency graph in section 7 | consistency |

Contract changes: none are needed for the engine. A-8 changes a release-gate input and needs owner approval. No amendment weakens SC-005, L3 mandatory integrity, D-08 authorization, or the evidence-only rule.

## 6. Dependency graph

```
                                  [DONE] 001 → 003 → 004 → 005 → 006 rules (T045-T078)
                                              │
        ┌─────────────────────────────────────┼───────────────────────────────┐
        ▼                                     ▼                               ▼
  FC-0.1 002 reconcile                 006-P11 wiring (A-5)             FC-PKG packaging (A-10)
  (fixtures v14 + 17.0)                T079-T084                         wheel assets + install test
        │                                     │                               │
        ▼                                     ▼                               │
  T035-min golden 17→18  ◄── human review     │                               │
  T025-min peer review   ◄── human review     │                               │
        │                                     │                               │
        └───────────────┬─────────────────────┘                               │
                        ▼                                                     │
              T059-min quickstart                                             │
                        │                                                     │
    ┌───────────────────┼─────────────────────┐                               │
    ▼                   ▼                     ▼                               │
 007 AI (T001-T050)  008 T029-gen/-data   009 Reporting (T001-T026)           │
 independent of KB   needs T025-min        independent of KB                  │
    │                   │                     │                               │
    └───────────────────┴──────────┬──────────┘                               │
                                   ▼                                          │
                         010 Hardening (T001-T024 + A-8, A-9)  ◄──────────────┘
                                   ▼
                         FC-E2E gate: wheel → validation path → report
                                   ▼
                         FRAMEWORK COMPLETE ──► KB backlog (parallel, any order)
```

Parallelism: after FC-0.1 and wiring, 007 and 009 can run in parallel with each other and with the human reviews. 008 T029 and the e2e gate wait only for T025-min and T035-min.

## 7. Phase closure matrix

| Phase | Mandatory framework tasks | Minimal validation | Deferred to KB | Depends on | Acceptance criteria | Completion gate |
|---|---|---|---|---|---|---|
| P1 / 002 | FC-0.1; T001-T009 as reconciled; T017, T022-T024, T027, T028 as reconciled | v14 fixture, one 17.0 fixture, `INDEX.json` | T011-T016 (v12, v13, v15, v16, v18 fixtures) | none | every task is `[X]`, mapped to the feature that did it, or moved to KB with an ID | reconciliation table committed to the feature folder; suite green |
| P5 / 006 | A-5 wiring T079-T084; T025-min; T035-min; T059-min | the 17.0 to 18.0 path (section 4) | T025r, T035r, T044r, T059r, SC-002/003 full scope | 004, 005 | wiring tests show `target` reaches the rules through the planner; the scanner runs in the pipeline; expected tree reviewed and matches byte for byte | independent reviewer sign-off recorded; quickstart outputs in `verification.md` |
| P7 / 008 | T029-gen | one runtime run for 18.0 recorded (Docker opt-in, executed once) | T029-data for other targets | T025-min | generator marks `RUNTIME_VALIDATED` only from a passing recorded run; unrun targets stay unmarked | matrix `--check` passes; run record linked |
| P6 / 007 | T001-T050 (all, including D-08 scope) | fake-provider suites offline; live adapter tests opt-in, run once if keys exist, otherwise recorded as not run | benchmark corpus breadth (T032 may use the minimal corpus) | rule metadata contract, 006-P11 for `target` plumbing | TST-007-* pass; zero provider calls with AI off; no fallback; no keys or prompts in logs | spec's quickstart scenarios 1-5 plus D-08 scenarios recorded |
| P8 / 009 | T001-T026 | golden report models generated from the validation path plus status fixtures | none | 003, 008 status model | JSON, SARIF, terminal, HTML, diff agree on counts; exports validate; no external resources | cross-renderer test and quickstart recorded; T025 mockup review by a human |
| P9 / 010 | T001-T024 plus A-8, A-9, T025-T027 (packaging) | corpus generator uses the minimal templates | breadth of support statement | 006-P11, 007, 008, 009 | RTM check passes with `DEFERRED_KB`; budgets met; failure-injection suite clean; secret scan clean; support statement lists the validation path as the only supported one | maintainer sign-off (T023) and FC-E2E |

## 8. Blocker reassessment

| Blocker | Genuine framework dependency? | Resolution | Independent review still required? |
|---|---|---|---|
| 006 T025 | Partly | `T025-min` now; rest KB | Yes for `T025-min`. A human reviewer, not an agent |
| 006 T035 | Partly | `T035-min` for 17 to 18 | Yes. Expected output is not authoritative until reviewed |
| 006 T044 | No | Deferred in full (KB-006-T044r). 14/15/16 paths are not in the validation path | Remains pending in KB |
| 006 T059 | Yes, reduced | After `T035-min` | n/a |
| 008 T029 | Generator yes, data no | A-6 | Review link comes through `T025-min` |
| 007 prerequisites | No for coverage; yes for rule metadata and `target` plumbing | A-7, A-5 | n/a |
| Planner `target` wiring | Yes | A-5 | n/a |
| Dependency scanner integration | Yes | A-5; scanner must run in the pipeline and appear in the report | n/a |
| Wheel packaging | Yes | A-10 | n/a |
| Golden fixture requirements | Partly | one 17.0 fixture, reviewed | Yes for expected output |
| 002 unexecuted (F-1) | Yes | A-11 | n/a |

## 9. Owner decisions required

| ID | Decision | Recommendation |
|---|---|---|
| OD-1 | Approve the framework/KB split and amendments A-1 to A-12 | Approve |
| OD-2 | Validation path | 17.0 to 18.0 |
| OD-3 | Name the independent human reviewer for `T025-min` and `T035-min`. Agents cannot fill this role | Required before the e2e gate |
| OD-4 | REQ-MAN-002: is the manifest version prefix change opt-in (current detect-only design) or default-on with opt-out | Keep opt-in and amend REQ-MAN-002 wording |
| OD-5 | Package knowledge data in the wheel, including the 4.87 MB view index | Yes. Size is acceptable. Alternative is a separate data package |
| OD-6 | 002: reconcile instead of re-executing, and defer fixtures for 12, 13, 15, 16, 18 | Approve |
| OD-7 | Release 1 scope: only the validation path is "supported"; all else is listed as pending knowledge | Approve |
| OD-8 | Docker gate: run the 18.0 runtime check once for the gate, and accept that source-side behavioural comparison for 17.0 may need an image built from pinned source or be reported UNAVAILABLE | Approve the run. Accept UNAVAILABLE if the build is out of scope |

## 10. Execution strategy and model assignment

Shortest safe path (critical path): `FC-0.1` and `006-P11 wiring` and `FC-PKG` (parallel) → `T035-min` and `T025-min` (human) → `T059-min` → `008 T029` → `010` → `FC-E2E`. Features 007 and 009 run in parallel beside the human reviews, so the reviews are not on the critical path unless they are late.

| Work | Model | Why |
|---|---|---|
| 006-P11 wiring, FC-PKG, 007, 009, 010 implementation | Sonnet | multi-file implementation with TDD |
| 002 reconciliation table, backlog ID annotation, RTM `DEFERRED_KB` data entry, wheel content listing, fixture copy, quickstart recording | Haiku | bounded, mechanical |
| Design of how `target` and run parameters pass through `build_plan` and the scanner pipeline; the A-8 gate contract | Opus, one escalation each | cross-cutting contract decisions |

Scope controls:
- No new rules, evidence records or golden cases without a line approved in this document.
- Each phase ends at its completion gate. A phase does not wait for a KB item.
- KB work happens only through the backlog, after the framework gate, or in a separate session that does not touch framework files.
- Existing KB (200 records, 91 rules, matrix, view index, golden corpus review package) is kept unchanged.
- Rules stay DETECT_ONLY. D-A3 and D-A5 remain not approved. T025, T035, T044 are not marked approved by any agent.
- No commit or push without a separate request.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Reduced corpus hides framework defects that broader rules would show | Failure-injection suite (010 T020) and synthetic-version tests stay mandatory |
| Reviewer not named, e2e gate stalls | OD-3 first; 007 and 009 proceed meanwhile |
| Wheel size or missing assets | FC-PKG compares wheel contents with loader reads |
| 002 reconciliation reveals real gaps (for example no characterisation of the legacy CLI) | Each gap becomes a task or an explicit owner-approved deferral |
| Support statement looks thin | Intended. It states what is verified |
