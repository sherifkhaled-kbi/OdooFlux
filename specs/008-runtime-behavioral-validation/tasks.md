---
description: "Task list for P7 — Runtime and Behavioral Validation"
---

# Tasks: Runtime and Behavioral Validation

**Input**: Design documents from `/specs/008-runtime-behavioral-validation/`
**Prerequisites**: P2 complete; D-03 decided (D-02 for RNG)
**Tests**: Required (Principle V). Write tests first; they must fail before implementation.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…) — Done when: …`

## Phase 1: Setup (research closure)

- [X] T001 Research G-R-13: document `odoo/docker` provenance, image names, tag/digest policy, and maintenance at a pinned SHA in `specs/008-runtime-behavioral-validation/research.md` (new EV-3xx rows) (REQ-VAL-004, REQ-EVD-004) — Done when: every claim used by T014 has an EV record with SHA/path/line, or is marked UNVERIFIED.
- [X] T002 [P] Research G-R-21: decide image source for versions ≤17.0 (repository history vs build from pinned `odoo/odoo` source) with evidence, in the same research.md (REQ-VAL-005, REQ-EVD-004) — Done when: a decision row with evidence exists, or the gap is retained with an explicit status cap documented.
- [X] T003 [P] Research G-R-22: extract install/upgrade error message patterns from official source per version into `src/odooflux/knowledge/compatibility/runtime_log_patterns.json` with EV references (REQ-VAL-004) — Done when: each pattern has `class`, `version_range`, `evidence` and schema validation passes.
- [X] T004 [P] Research G-R-23: document test-runner output format per supported target version with EV references in research.md (REQ-VAL-005, REQ-BIZ-002) — Done when: parser specification for per-test outcomes exists for every target version in scope.
- [X] T005 Create runtime fixtures in `tests/golden_fixtures/runtime/`: `install_ok`, `broken_view`, `install_loop`, `acl_missing_model`, `behavior_compare` (with one passing, one regressing, one always-failing test), `enterprise_dep` (REQ-VAL-004, REQ-BIZ-002) — Done when: each fixture has a README stating its expected status and error class.

## Phase 2: Foundational

- [X] T006 [P] Unit test: full decision-table sweep in `tests/unit/validation/test_status_decision.py` (REQ-VAL-006; TST-008-001) — Done when: every row of contracts/status-decision.md plus the combinatorial sweep is asserted; row 7 never matches valid inputs.
- [X] T007 [P] Unit test: unrun layers are never reported PASS, in `tests/unit/validation/test_layer_reporting.py` (REQ-VAL-006; TST-008-002) — Done when: UNAVAILABLE/SKIPPED carry reasons and never serialise as PASS.
- [X] T008 Implement `src/odooflux/validation/status.py` per contract (REQ-VAL-006) — Done when: TST-008-001 and TST-008-002 pass.
- [X] T009 Verify that `ValidationResult` in `src/odooflux/core/contracts/` exposes `coverage` and `reason` (contract v1, implemented by 003:T007 and tested by TST-003-004) and that the status decision consumes them; open a contract issue instead of editing if absent (REQ-VAL-006) — Done when: TST-003-004 passes and every runtime/behavioral validator sets `coverage` for layer 5 results.

## Phase 3: User Story 1 — Honest status (P1) 🎯 MVP

- [X] T010 [P] [US1] Integration test: static-only run yields `STATIC_VALIDATED` with L4/L5 listed in verification scope, in `tests/integration/validation/test_static_only.py` (REQ-VAL-006, REQ-BIZ-003; TST-008-003) — Done when: report `verification_scope.layers_unavailable` contains L4 and L5 with reasons.
- [X] T011 [US1] Wire status decision and verification scope into the orchestrator result in `src/odooflux/core/orchestrator/` (REQ-VAL-006, REQ-BIZ-003) — Done when: TST-008-003 passes.

## Phase 4: User Story 2 — Isolated install/upgrade (P1)

- [x] T012 [P] [US2] Unit test: Docker adapter command construction (read-only mount, `--network none`, cpu/memory/pids limits, labels, digest-pinned image) in `tests/unit/validation/test_docker_env.py` (REQ-SEC-001, REQ-SEC-002; TST-008-004) — Done when: generated argv matches expectations; no host path except module copy and scratch volume.
- [x] T013 [P] [US2] Unit test: log classifier on recorded log samples in `tests/unit/validation/test_log_classifier.py` (REQ-VAL-004, REQ-ACL-002; TST-008-005) — Done when: each class in FR-006 is recognised on at least one sample and unknown lines map to `unknown`.
- [x] T014 [US2] Implement `src/odooflux/validation/runtime/docker_env.py` (`RuntimeEnvironment`) with guaranteed teardown (REQ-VAL-004, REQ-SEC-001, REQ-SEC-002) — Done when: TST-008-004 passes.
- [x] T015 [US2] Implement `src/odooflux/validation/runtime/log_classifier.py` loading patterns from knowledge data (REQ-VAL-004, REQ-ACL-002) — Done when: TST-008-005 passes.
- [x] T016 [P] [US2] Runtime test: install fixtures produce the expected statuses in `tests/runtime/test_install.py` (REQ-VAL-004, REQ-ACL-002; TST-008-006) — Done when: with `ODOOFLUX_RUNTIME_TESTS=1`, `install_ok` → INSTALL_VERIFIED, `broken_view` → FAILED/view_validation, `acl_missing_model` → FAILED/access_rights; skipped otherwise.
- [x] T017 [P] [US2] Runtime/failure-injection test: loop fixture is killed at the time limit and no labelled resources remain, in `tests/runtime/test_limits.py` (REQ-SEC-002; TST-008-007) — Done when: status FAILED/timeout and resource listing by run label is empty.
- [x] T018 [P] [US2] Runtime test: upgrade path `-u` on an installed module in `tests/runtime/test_upgrade.py` (REQ-VAL-004; TST-008-008) — Done when: upgrade outcome recorded as L4 sub-result.
- [x] T019 [US2] Implement Enterprise-dependency and missing-image handling (SKIPPED/UNAVAILABLE with reasons) in `src/odooflux/validation/runtime/` (REQ-VAL-004, REQ-VAL-006) — Done when: `enterprise_dep` fixture → status ≤ STATIC_VALIDATED with reason `enterprise_dependency`.

## Phase 5: User Story 3 — Behavioural comparison (P2)

- [x] T020 [P] [US3] Unit test: test-outcome parsing and comparison classifications in `tests/unit/validation/test_behavior_compare.py` (REQ-BIZ-002, REQ-VAL-005; TST-008-009) — Done when: all six classifications are produced from recorded outputs.
- [x] T021 [US3] Implement `src/odooflux/validation/behavioral/compare.py` and `run_tests` in the Docker adapter (REQ-VAL-005, REQ-BIZ-002) — Done when: TST-008-009 passes.
- [x] T022 [P] [US3] Runtime test: behavioural fixture on source and target in `tests/runtime/test_behavior_compare.py` (REQ-BIZ-002, REQ-BIZ-003; TST-008-010) — Done when: exactly 1 regression, 1 fail_both, 1 pass_both; L5 = FAIL; no baseline → coverage partial and status ≤ INSTALL_VERIFIED.

## Phase 6: User Story 4 — Dependency integrity and RNG (P2)

- [X] T023 [P] [US4] Unit test: L3 broken-reference fixtures (missing module, model, field, XML ID, group, Python package) in `tests/unit/validation/test_dependency_integrity.py` (REQ-VAL-003, REQ-DEP-003; TST-008-011) — Done when: exactly one finding per broken reference kind.
- [X] T024 [P] [US4] Unit test: RNG validation FAIL with lxml, UNAVAILABLE without, in `tests/unit/validation/test_rng.py` (REQ-XML-004; TST-008-012) — Done when: both branches covered (lxml presence simulated).
- [X] T025 [US4] Implement `src/odooflux/validation/dependency/integrity.py` (REQ-VAL-003, REQ-DEP-003) — Done when: TST-008-011 passes.
- [X] T026 [US4] Implement `src/odooflux/validation/static/rng.py` using RNG files listed per version in knowledge data (EV-302) (REQ-XML-004) — Done when: TST-008-012 passes.

## Phase 7: Polish & Cross-Cutting

- [X] T027 [P] Static check: no `exec`/`importlib` of scanned paths anywhere in `src/odooflux` in `tests/unit/validation/test_no_customer_code_execution.py` (REQ-SEC-001; TST-008-013) — Done when: AST scan of the package finds no dynamic import/exec of workspace paths.
- [X] T028 Run [quickstart.md](quickstart.md) scenarios and record outcomes in the phase verification log (REQ-VAL-004, REQ-VAL-006) — Done when: all six scenarios recorded with expected results.
- [X] T029-gen Matrix generator marks a target `RUNTIME_VALIDATED` only from a recorded, valid, passing runtime run record (REQ-VAL-004, REQ-EVD-006; plan A-6, split of T029) — Done when: `src/odooflux/knowledge/runtime_runs.py`, `schemas/runtime_runs.schema.json`, `compatibility/runtime_runs.json` (shipped empty) and the generator columns exist; `knowledge validate` rejects malformed records; tests cover record present, absent, failing, malformed, later failure and no source image in `tests/unit/knowledge/test_matrix_runtime_runs.py`; `docs/planning/VERSION_COMPATIBILITY_MATRIX.md` regenerated and unchanged in status (no step marked).
  - Behavioural verification is reported only with a passing run, `behavioural` PASS and a source-side image digest; otherwise the cell stays unmarked.
- [ ] T029 Update the VERSION_COMPATIBILITY_MATRIX data so targets with passing runtime fixtures are marked `RUNTIME_VALIDATED` via the P3 generator (REQ-VAL-004, REQ-EVD-006) — Done when: matrix regenerated; only targets with passing TST-008-006 are marked.
  - Technical part: the generator is T029-gen above. The opt-in runtime suite was run once (see quickstart.md verification log, 2026-11-07, 9 tests OK) but NO run record was added: the runtime fixtures are synthetic framework fixtures, not a golden migration of a step, so a record for a step would overclaim.
  - Certification/Data: PENDING. Needs a person to decide which golden migration and step a record may cover, then a real recorded run (register fragment `docs/reviews/fragments/ws-f-human-review.md`, item WSF-001).

## Dependencies & Execution Order

- T001–T004 (research) before T014/T015/T021 and before enabling the runtime adapter by default.
- Foundational (T006–T009) blocks all stories. US1 (status) is the MVP and needs no Docker.
- US2 before US3 (behaviour uses the runtime adapter). US4 is independent of US2/US3.

### Parallel Example: User Story 2

```bash
Task: "T012 Docker adapter argv test in tests/unit/validation/test_docker_env.py"
Task: "T013 log classifier test in tests/unit/validation/test_log_classifier.py"
```

## Implementation Strategy

MVP: decision table + static-only status (US1). Then the isolated install (US2), behaviour (US3), and integrity/RNG (US4). Default enablement of runtime validation only after T001–T004 close or cap their gaps.
