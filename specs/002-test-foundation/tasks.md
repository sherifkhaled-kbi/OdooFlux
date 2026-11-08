---
description: "Task list for Test Foundation (P1)"
---

# Tasks: Test Foundation (P1)

**Input**: Design documents from `/specs/002-test-foundation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md; P0 (001) complete

**Tests**: This feature *is* tests. Harness self-tests come first.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…)`

---

## Phase 1: Setup

- [X] T001 Create the package skeleton `tests/_support/__init__.py`, plus `__init__.py` in `tests/unit`, `tests/integration`, `tests/contract`, `tests/runtime`, and `tests/benchmarks` (`tests/regression` already exists from P0). Remove the planning `.gitkeep` files in directories that now have content. Done when: `python -m unittest discover -s tests` still passes the P0 tests. (REQ-TST-001) [FC-0.1: done; `tests/_support/` added, `.gitkeep` removed]
- [X] T002 [P] Create `tests/golden_fixtures/.gitattributes` with `* -text` and `tests/golden_fixtures/INDEX.json` (empty list) per [data-model.md](data-model.md). Done when: the file exists and `git check-attr text` reports `unset` for fixture files. (REQ-TST-003) [FC-0.1: done]

---

## Phase 2: Foundational (harness)

- [X] T003 [P] Write `tests/unit/test_harness_digest.py` (TST-002-001): `tree_digest` is order-independent and detects a 1-byte change. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-TST-001; TST-002-001) [FC-0.1: done; `tests/unit/test_harness_digest.py`]
- [X] T004 [P] Write `tests/unit/test_harness_normalize.py` (TST-002-002): normalisation replaces paths and timestamps and sorts issues; the same report from two temp dirs normalises identically. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-TST-004; TST-002-002) [FC-0.1: done; `tests/unit/test_harness_normalize.py`]
- [X] T005 [P] Write `tests/unit/test_harness_optin.py` (TST-002-003): decorators skip when the flag is unset and run when it is `1`. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-TST-006; TST-002-003) [FC-0.1: done; `tests/unit/test_harness_optin.py`]
- [X] T006 Implement `tests/_support/digest.py`, `normalize.py`, `optin.py`, `fixtures.py` (`copy_fixture(id, tmp) -> Path`, `load_index()`), and `cli.py` (`run_legacy_cli(args, cwd) -> CompletedRun(exit, stdout, stderr)` with `--no-color` enforced and a 120 s timeout). Done when: TST-002-001…003 pass. (REQ-TST-001; REQ-TST-004; REQ-TST-006) [FC-0.1: done; `cli.py` runs the root launcher, `p0.py` added for P0 helpers]
- [X] T007 Migrate the P0 tests in `tests/regression/test_p0_*.py` to `tests/_support`; delete `tests/regression/helpers.py`. Done when: all P0 tests pass unchanged in assertion count. (REQ-TST-001; REQ-TST-005) [FC-0.1: done; four P0 test files import `tests/_support/p0.py`; `tests/regression/helpers.py` deleted]

**Checkpoint**: Harness ready.

---

## Phase 3: User Story 1 - One command runs the offline suite (P1) 🎯 MVP

- [X] T008 [US1] Write `tests/README.md`: how to run, suite layout, ID conventions (`TST-…`, finding IDs in docstrings), fixture layout, how to add a regression test, and the opt-in flags. Done when: every directory in `tests/` is described. (REQ-TST-001) [FC-0.1: done]
- [X] T009 [US1] Add `tests/integration/test_offline_guard.py` (TST-002-004): patches `socket.socket.connect` to raise during the default suite's integration tests. Done when: the CLI analyze run on every fixture passes under the guard. (REQ-TST-001; REQ-TST-006; TST-002-004) [FC-0.1: done; guard test runs analyze on every INDEX entry]

---

## Phase 4: User Story 3 - Golden fixtures per source version (P2)

(US3 precedes US2 in execution because characterisation needs fixtures.)

- [ ] T010 [P] [US3] Move `tests/golden_fixtures/p0_kbi_demo_v14/` into `v14_kbi_demo/input/kbi_demo/` and register it in `INDEX.json` (evidence EV-101/103/110; findings from Appendix A). Done when: P0 tests reference the new path and pass. (REQ-TST-003) [FC-0.1: NOT DONE, RECONCILED: the fixture stays at `p0_kbi_demo_v14/` and is registered in INDEX.json with `layout: flat`; moving it touches 40+ references and the P0 suite. Needs owner decision]
- [ ] T011 [P] [US3] Author `tests/golden_fixtures/v12_kbi_legacy/` with the constructs from [research.md R-03](research.md) for 12.0, plus a README listing EV IDs. Done when: TST-002-005 passes for it. (REQ-TST-003) [DEFERRED_KB: KB-002-FIX]
- [ ] T012 [P] [US3] Author `v13_kbi_sudo/` per R-03. Done when: TST-002-005 passes for it. (REQ-TST-003) [DEFERRED_KB: KB-002-FIX]
- [ ] T013 [P] [US3] Author `v15_kbi_assets/` per R-03. Done when: TST-002-005 passes for it. (REQ-TST-003) [DEFERRED_KB: KB-002-FIX]
- [ ] T014 [P] [US3] Author `v16_kbi_views/` per R-03. Done when: TST-002-005 passes for it. (REQ-TST-003) [DEFERRED_KB: KB-002-FIX]
- [ ] T015 [P] [US3] Author `v17_kbi_owl/` per R-03 (includes a JS file using the `rpc` service, EV-120). Done when: TST-002-005 passes for it. (REQ-TST-003) [DEFERRED_KB: KB-002-T015; note: PROVISIONAL `17.0/kbi_demo` already carries the OWL `rpc` construct (EV-120), owner to confirm the backlog item can close]
- [ ] T016 [P] [US3] Author `v18_kbi_orm/` per R-03 (target 19 only). Done when: TST-002-005 passes for it. (REQ-TST-003) [DEFERRED_KB: KB-002-FIX]
- [X] T017 [US3] Write `tests/integration/test_fixture_validity.py` (TST-002-005): every INDEX entry has the required layout; manifest version prefix = source; every input `.py` passes `ast.parse` under the running interpreter; every `.xml` is well-formed; targets are greater than the source. Done when: it passes for all 7 fixtures (SC-002). (REQ-TST-003; TST-002-005) [FC-0.1: done; Done-when read per A-11 as every INDEX entry (2); fixtures for v12/v13/v15/v16/v18 are DEFERRED_KB]

---

## Phase 5: User Story 2 - Characterisation suite (P1)

- [X] T018 [US2] Implement `tools/update_expectations.py`: for each fixture and target, run the legacy CLI in analyze mode (`--report`) and fix mode on a temp copy; write normalised `expected_report.<t>.json`, `expected/<t>/`, and `expected_exit.json`. Refuse when `git status --porcelain tests/golden_fixtures` is non-empty unless `--force`. Print changed files. Done when: two consecutive runs produce no diff (determinism). (REQ-TST-004) [FC-0.1: done as `tools/update_expectations.py` writing the 006 golden layout (`expected/<t>/{tree,report.json}`); two consecutive runs print "no changes". Expected output is PROVISIONAL]
- [X] T019 [US2] Generate the expectations for all fixtures with T018 and commit them as data. Done when: `expected*` exists for every INDEX target. (REQ-TST-004) [FC-0.1: done for the INDEX targets (`17.0/kbi_demo` to 18.0). PROVISIONAL, not approved]
- [X] T020 [US2] Write `tests/integration/test_characterisation.py` (TST-002-006): one subTest per fixture × target × mode comparing the normalised report, exit code, and fixed-tree digest with the expectations. Show a unified diff on mismatch. Done when: all cases pass (SC-003). (REQ-TST-004; TST-002-006) [FC-0.1: done-by-other-feature `tests/integration/test_golden_migrations.py` (006 T006) plus `tests/integration/test_provisional_corpus.py`; fix mode only, analyze mode covered by `test_analyze_state_only.py` and `test_cli_contract.py`]
- [X] T021 [US2] Write `tests/integration/test_characterisation_sensitivity.py` (TST-002-007): mutating one expected issue message makes the comparison helper report a mismatch. Done when: it passes (guards against vacuous comparisons). (REQ-TST-004; TST-002-007) [FC-0.1: done-by-other-feature `test_golden_migrations.py::test_mismatched_sample_is_reported`]
- [X] T022 [US2] Write `tests/integration/test_input_immutability.py` (TST-002-008): the fixture `input/` digest is unchanged after the full suite (runs last, by name ordering `test_zz_…`). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-TST-003; REQ-SAF-001; TST-002-008) [FC-0.1: done as `tests/integration/test_zz_input_immutability.py` using `input_digest` in INDEX.json]

---

## Phase 6: User Story 4 - Regression index and opt-in suites (P3)

- [X] T023 [US4] Create `tests/regression/INDEX.md` listing the P0-resolved finding IDs (F-SAFE-1/2/3/4/5, F-PY-1/2/4/5/6, F-XML-1/2/4, F-REP-1, F-MAN-1, F-AI-6, F-VAL-1, F-REP-3) with their TST IDs from `specs/001-safety-stabilization/tasks.md`. Done when: every row has at least one test. (REQ-TST-005) [FC-0.1: done; finding IDs were added to four P0 test docstrings so every row cites its ID]
- [X] T024 [US4] Write `tests/regression/test_regression_index.py` (TST-002-009): parses INDEX.md and asserts every listed test exists and its docstring contains the finding ID. Done when: it passes (SC-004). (REQ-TST-005; TST-002-009) [FC-0.1: done]
- [X] T025 [P] [US4] Write `tests/runtime/test_runtime_placeholder_gate.py` (TST-002-010): decorated with `requires_runtime`; asserts `docker` is on PATH. Done when: it is skipped by default and runs with the flag. (REQ-TST-006; TST-002-010) [FC-0.1: done; runs with `ODOOFLUX_RUNTIME_TESTS=1`]
- [X] T026 [P] [US4] Write `tests/unit/test_rule_coverage_report.py` (TST-002-011): enumerates legacy rule categories from `odooflux.py` rule tables via `ast` (no import of the script), cross-references test docstrings for `rule:<category>` tags, and writes `tests/rule_coverage.txt`. Report-only (no failure). Done when: the report lists each category with positive/negative/idempotence presence. (REQ-TST-002; TST-002-011) [FC-0.1: done; tables read from `src/odooflux/rules/shared/legacy_rules.py` because the P2 cut-over moved them out of `odooflux.py`; report-only, no coverage tags exist yet]

---

## Phase 7: Polish

- [X] T027 Measure the default suite duration and record it in `specs/002-test-foundation/verification.md`. Done when: the duration is under 120 s, or the slowest tests are listed with a plan. (REQ-TST-001) [FC-0.1: done; see verification.md]
- [ ] T028 Run [quickstart.md](quickstart.md) and record outputs in `verification.md`. Done when: SC-001…SC-005 are each evidenced. (REQ-TST-001; REQ-TST-003; REQ-TST-004; REQ-TST-005; REQ-TST-006) [FC-0.1: IMPLEMENTED for the reconciled scope, left open: SC-002 (all seven fixtures) is not met, five fixtures are DEFERRED_KB; see verification.md]

---

## Reconciliation (FC-0.1, amendment A-11)

Each task is mapped in [reconciliation.md](reconciliation.md). `[X]` means the Done-when is met for the reconciled scope; open tasks carry DEFERRED_KB or RECONCILED notes.

## Deferred

- REQ-TST-002 enforcement (failing mode) → P5 (006).
- REQ-TST-003 fixtures for target versions beyond the legacy CLI's 18/19 → P5.

## Dependencies & Execution Order

Setup (T001–T002) → Harness (T003–T007) → US1 (T008–T009) → US3 fixtures (T010–T017) → US2
(T018–T022) → US4 (T023–T026) → Polish.

## Parallel Example

```bash
Task: "T011 v12 fixture"  Task: "T012 v13 fixture"  Task: "T013 v15 fixture"
Task: "T014 v16 fixture"  Task: "T015 v17 fixture"  Task: "T016 v18 fixture"
```

## Counts

28 tasks; 11 tests (TST-002-001 … TST-002-011).
