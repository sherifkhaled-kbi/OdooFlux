---
description: "Task list for P9 — Hardening and Release Readiness"
---

# Tasks: Hardening and Release Readiness

**Input**: Design documents from `/specs/010-hardening-release/`
**Prerequisites**: P5, P6, P7, P8 complete; P2 baseline benchmark and reference machine recorded
**Tests**: Required (Principle V). Write tests first; they must fail before implementation.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…) — Done when: …`

## Phase 1: Setup

- [X] T001 Implement the deterministic corpus generator `tests/benchmarks/corpus_gen.py` (seeded, 300 modules × 30 files from golden templates) (REQ-PRF-001) — Done when: two runs with the same seed produce byte-identical corpora (checked by digest).
  - Status: verified: `tests/benchmarks/test_corpus_gen.py` (digest equal for equal seeds, 300x30 shape).
- [X] T002 [P] Record `tests/benchmarks/budgets.json` from the P2 baseline with headroom rationale and approver (REQ-PRF-001, REQ-PRF-004) — Done when: every metric/mode has a value, a baseline reference, and an approver.
  - Status: verified: `tests/benchmarks/budgets.json`, `baseline.json`, `REFERENCE_MACHINE.md`; technical part IMPLEMENTED/VERIFIED. Certification: approver PENDING_HUMAN_REVIEW (WSG-02); the original Done-when (approver recorded) is NOT satisfied (ADR-019 item 3).

## Phase 2: Foundational

- [X] T003 [P] Unit test: RTM completeness check fails on any REQ without a passing mapped test or verification record, in `tests/unit/release/test_rtm_completeness.py` (REQ-TST-005, REQ-TST-002; TST-010-001) — Done when: a synthetic unmapped REQ makes it fail; the real RTM passes at release.
  - Status: verified: `tests/unit/release/test_rtm_completeness.py`.
- [X] T004 [P] Unit test: every resolved `F-…` finding has a citing regression test, in `tests/unit/release/test_regression_citations.py` (REQ-TST-005; TST-010-002) — Done when: missing citations are reported by ID.
  - Status: verified: `tests/unit/release/test_regression_citations.py` (added `tests/regression/test_walk_findings.py` to cite F-WALK-1).
- [X] T005 Implement the RTM parser and checker in `tests/unit/release/rtm_tools.py`, reading `docs/planning/REQUIREMENTS_TRACEABILITY_MATRIX.md` and `specs/*/tasks.md` tags (REQ-TST-005) — Done when: TST-010-001/002 pass.
  - Status: verified: `tests/unit/release/rtm_tools.py` with DEFERRED_KB status (A-8).

## Phase 3: User Story 1 — Release gate (P1) 🎯 MVP

- [X] T006 [P] [US1] Unit test: support statement marks paths supported only when all steps are `RULES_TESTED` and the target is `RUNTIME_VALIDATED`, in `tests/unit/release/test_support_statement.py` (REQ-VER-003, REQ-EVD-006; TST-010-003) — Done when: fixtures for each status combination give the expected output.
  - Status: verified: `tests/unit/release/test_support_statement.py`.
- [X] T007 [US1] Implement the `support-statement` command in `src/odooflux/cli/support_statement.py` generating `docs/planning/SUPPORT_STATEMENT.md` from matrix data (REQ-VER-003, REQ-EVD-006) — Done when: TST-010-003 passes.
  - Status: verified: `odooflux support-statement`; generated `docs/planning/SUPPORT_STATEMENT.md` lists no supported path.
- [X] T008 [US1] Create `docs/planning/RELEASE_CHECKLIST.md` with items linked to RTM, benchmark, secret-scan, failure-injection, and support-statement evidence (REQ-TST-005) — Done when: every item has an evidence link placeholder and an owner.
  - Status: not started (release checklist document not written yet).

## Phase 4: User Story 2 — Performance at scale (P1)

- [X] T009 [P] [US2] Integration test: parallel report digest equals serial digest on the corpus subset, in `tests/integration/hardening/test_parallel_determinism.py` (REQ-PRF-003; TST-010-004) — Done when: digests are equal for `--jobs 1` and `--jobs 4`.
  - Status: verified: `test_parallel_determinism.py` (digests equal, failed and killed worker block only their module).
- [X] T010 [P] [US2] Integration test: incremental re-run parses 0 files and is invalidated by rule-set or tool-version change, in `tests/integration/hardening/test_incremental.py` (REQ-PRF-002; TST-010-005) — Done when: parse counter is 0 unchanged, and >0 after a digest change.
  - Status: verified: `test_incremental.py` (0 files parsed unchanged; invalidated by content, rule-set, tool-version).
- [X] T011 [P] [US2] Benchmark: serial/parallel/incremental medians and peak RSS vs budgets in `tests/benchmarks/run_benchmarks.py` (REQ-PRF-001, REQ-PRF-004; TST-010-006) — Done when: results JSON is written and the run fails when a budget or the 20 % regression rule is violated.
  - Status: verified: `tests/benchmarks/run_benchmarks.py`; logic tests always, 300-module run PASS on the reference machine (`results/`).
- [X] T012 [US2] Implement the process-pool executor with deterministic merge in `src/odooflux/core/orchestrator/parallel.py` (REQ-PRF-003) — Done when: TST-010-004 passes.
  - Status: verified: `core/orchestrator/parallel.py` (analysis and dry run; fix mode stays serial).
- [X] T013 [US2] Implement the incremental index in `src/odooflux/core/orchestrator/incremental.py` (REQ-PRF-002) — Done when: TST-010-005 passes.
  - Status: verified: `core/orchestrator/incremental.py` (`--incremental`, analysis and dry run).
- [X] T014 [US2] Optimise hot paths found by profiling until TST-010-006 meets budgets; record profile summaries in `tests/benchmarks/results/` (REQ-PRF-001, REQ-PRF-004) — Done when: TST-010-006 passes on the reference machine.
  - Status: verified: profile summary in `tests/benchmarks/results/profile-summary-2026-11-07.md`; budgets met. Still about 6x the P2 figure on the P2 corpus (see summary). Certification: budget acceptance PENDING_HUMAN_REVIEW (WSG-02).

## Phase 5: User Story 3 — Auditability and secrets (P2)

- [X] T015 [P] [US3] Integration test: audit log has one entry per action type and a valid hash chain, in `tests/integration/hardening/test_audit_log.py` (REQ-SEC-005; TST-010-007) — Done when: all actions from contracts/audit-log.md that occur in the scenario are present; tampering is detected.
  - Status: verified: `test_audit_log.py`.
- [X] T016 [P] [US3] Integration test: canary-secret scan over all artefacts (reports, logs, cache, audit, run log, debug) in `tests/integration/hardening/test_secret_scan.py` (REQ-AI-008, REQ-SEC-005; TST-010-008) — Done when: 0 matches.
  - Status: verified: `test_secret_scan.py` (the canary reached the adapter, 0 matches in every artefact).
- [X] T017 [P] [US3] Unit test: `--api-key` is rejected after the D-10 window with exit 2 and no echo, in `tests/unit/cli/test_api_key_removed.py` (REQ-AI-008; TST-010-009) — Done when: stdout/stderr do not contain the value.
  - Status: verified: `tests/unit/cli/test_api_key_removed.py` (version mechanism; current release is inside the window).
- [X] T018 [US3] Implement `src/odooflux/core/recovery/audit_log.py` and emit entries from orchestrator, jobs, recovery, AI, and runtime adapters (REQ-SEC-005) — Done when: TST-010-007 passes.
  - Status: verified: `core/recovery/audit_log.py`; entries from orchestrator, jobs, recovery, AI and the runtime adapter.
- [X] T019 [US3] Extend `src/odooflux/utils/redaction.py` and remove `--api-key` per D-10 (REQ-AI-008) — Done when: TST-010-008/009 pass.
  - Status: verified: `utils/redaction.py`, `cli/deprecations.py`. Removal activates at 0.3.0; D-10 window is an owner decision (register item WSG-03).

## Phase 6: User Story 4 — Reliability under failure (P2)

- [X] T020 [P] [US4] Failure-injection suite covering write, promote, backup, backup-verify, checkpoint, rollback, resume, and runtime teardown in `tests/integration/hardening/test_failure_injection.py` (REQ-SAF-005, REQ-SAF-008, REQ-SAF-009; TST-010-010) — Done when: every injection point leaves originals byte-identical or restorable via rollback, and the module status is `BLOCKED` where specified.
  - Status: done. 13 subTests/tests in `tests/integration/hardening/test_failure_injection.py` cover write, promote (k=1..3, fsync, replace), backup, backup-verify, checkpoint (rollback and resume), kill before promotion (resume and rollback), failing resume, rollback fault, and runtime prepare/teardown (stub Docker runner). Red first: 3 errors (1 test expectation, 2 from F-INJ-1); green after the fix.
- [X] T021 [US4] Fix defects found by TST-010-010 in their owning components, each with a regression test (REQ-SAF-005, REQ-TST-005) — Done when: TST-010-010 passes and each fix has a citing regression test.
  - Status: done. F-INJ-1 fixed in `core/jobs/promote.py::_restore` (regression test `tests/regression/test_failure_injection_findings.py`). No open issues.

## Phase 7: Polish & Cross-Cutting

- [X] T022 [P] Re-run the P2 synthetic-version (no-core-edit) test and the P8 cross-renderer test as release gates in `tests/integration/hardening/test_release_gates.py` (REQ-ARC-003, REQ-REP-001; TST-010-011) — Done when: both pass on the release candidate.
  - Status: not started.
- [ ] T023 Fill `docs/planning/RELEASE_CHECKLIST.md` evidence links and obtain maintainer sign-off (REQ-TST-005) — Done when: every item is `done` with evidence and signer.
  - Certification: PENDING_HUMAN_REVIEW (register fragment `docs/reviews/fragments/ws-g-human-review.md`, item WSG-01). No agent signs. T023 stays unchecked until a human maintainer records sign-off in the review register.
- [X] T024 Run [quickstart.md](quickstart.md) and record results in the phase verification log (REQ-PRF-001, REQ-SEC-005) — Done when: all five scenarios recorded.
  - Status: verified; all five scenarios recorded in verification-log.md (orchestrator).

## Dependencies & Execution Order

- Setup → Foundational → US1 (gate) → US2–US4 in parallel → Polish (T023 last).
- T014 depends on T011. T021 depends on T020.

### Parallel Example: User Story 2

```bash
Task: "T009 parallel determinism test"
Task: "T010 incremental test"
Task: "T011 benchmark harness"
```

## Implementation Strategy

Build the release gate (US1) first so that gaps surface early, then measure and optimise (US2), then harden (US3, US4). P9 adds no features; gaps become new specs.

## Phase: Packaging (FC A-10)

- [X] T025 Wheel asset list and `package-data` fix: every runtime asset the loaders read (knowledge JSON, compatibility, evidence, view_index, schemas, official_sources, reporting model schema) ships in the wheel — Done when: `tests/integration/packaging/test_wheel_assets.py` compares loader-read files with the built wheel. Depends: none.
- [X] T026 Wheel build test offline (`pip wheel . --no-deps --no-build-isolation`) — Done when: test builds the wheel in a temp dir, skips with a precise reason if setuptools/wheel are unavailable. Depends: T025.
- [X] T027 Install test (opt-in, `ODOOFLUX_PACKAGING_INSTALL=1`): fresh venv, install the wheel, run `odooflux --help`, `odooflux knowledge validate` and an analysis of a fixture from outside the repo — Done when: run once and output recorded in `docs/reviews/fragments/ws-b-human-review.md` evidence. Depends: T026.
