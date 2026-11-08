# Reconciliation (FC-0.1, amendment A-11)

Date: 2026-11-07. Basis: ADR-019 and `docs/planning/FRAMEWORK_COMPLETION_PLAN.md` sections 4, 5 and 7. Feature 002 is
reconciled, not re-executed. Dispositions: `done` (implemented here), `done-by-other` (another feature proves it),
`adapted` (done with a documented deviation), `reconciled-open` (not done, owner decision), `DEFERRED_KB` (backlog ID).
`[X]` in `tasks.md` means the Done-when is met for the reconciled scope.

| Task | Disposition | Evidence |
|---|---|---|
| T001 | done | `tests/_support/__init__.py`; `__init__.py` in every suite directory; `.gitkeep` removed from directories with content; P0 suite 59 tests OK |
| T002 | done | `tests/golden_fixtures/.gitattributes` (`* -text`); `git check-attr text` reports `unset`; `tests/golden_fixtures/INDEX.json` |
| T003 | done | `tests/unit/test_harness_digest.py` (red before `digest.py` existed) |
| T004 | done | `tests/unit/test_harness_normalize.py` (red first) |
| T005 | done | `tests/unit/test_harness_optin.py` (red first) |
| T006 | done | `tests/_support/{digest,normalize,optin,fixtures,cli}.py`; `cli.run_legacy_cli` runs the root launcher with `--no-color` and a 120 s timeout |
| T007 | done | `tests/_support/p0.py` replaces `tests/regression/helpers.py` (deleted); the four `test_p0_*.py` files import it; assertions untouched |
| T008 | done | `tests/README.md` describes every directory, opt-in flags, fixture layout, IDs, how to add a regression test |
| T009 | done | `tests/integration/test_offline_guard.py` |
| T010 | reconciled-open | Fixture stays at `tests/golden_fixtures/p0_kbi_demo_v14/` (40+ references). Registered in INDEX.json with `layout: flat`, authority `BASELINE`. Move needs an owner decision |
| T011 | DEFERRED_KB | KB-002-FIX (v12) |
| T012 | DEFERRED_KB | KB-002-FIX (v13) |
| T013 | DEFERRED_KB | KB-002-FIX (v15) |
| T014 | DEFERRED_KB | KB-002-FIX (v16) |
| T015 | DEFERRED_KB | KB-002-T015. Note: the PROVISIONAL `17.0/kbi_demo` fixture already contains the OWL `rpc` service construct (EV-120); the owner can close the item if that suffices |
| T016 | DEFERRED_KB | KB-002-FIX (v18) |
| T017 | done (adapted scope) | `tests/integration/test_fixture_validity.py`; passes for both INDEX entries (v14 baseline, 17.0 provisional). The "7 fixtures" count is reduced by A-11 |
| T018 | adapted | `tools/update_expectations.py` writes the 006 golden layout (`expected/<t>/tree`, `report.json`) instead of the 002 layout; refuses on a dirty `tests/golden_fixtures` unless `--force`; two consecutive runs print "no changes" |
| T019 | done (provisional) | `17.0/kbi_demo/expected/18.0/` generated; PROVISIONAL markers; not approved |
| T020 | done-by-other + adapted | `tests/integration/test_golden_migrations.py` (006 T006) compares report and tree byte for byte for every golden case; `tests/integration/test_provisional_corpus.py` adds the provisional-specific cases. Exit codes and analyze-mode reports are not compared here; analyze mode is covered by `test_analyze_state_only.py`, `test_cli_contract.py` |
| T021 | done-by-other | `test_golden_migrations.py::test_mismatched_sample_is_reported`; `test_provisional_corpus.py::test_tree_differences_helper_still_detects_change` |
| T022 | done | `tests/integration/test_zz_input_immutability.py` compares `input_digest` in INDEX.json with the fixtures |
| T023 | done | `tests/regression/INDEX.md` (18 findings). Finding IDs F-SAFE-3, F-REP-1, F-MAN-1, F-REP-3 were added to the docstrings of existing P0 tests so every row cites its ID |
| T024 | done | `tests/regression/test_regression_index.py` |
| T025 | done | `tests/runtime/test_runtime_placeholder_gate.py`; skipped by default; runs with `ODOOFLUX_RUNTIME_TESTS=1` |
| T026 | adapted | `tests/unit/test_rule_coverage_report.py` reads the tables from `src/odooflux/rules/shared/legacy_rules.py` (moved out of `odooflux.py` by the P2 cut-over); writes `tests/rule_coverage.txt`; report only. No `rule:` tags exist in docstrings yet, so every cell is `-` |
| T027 | done | `verification.md` |
| T028 | reconciled-open | Quickstart run recorded in `verification.md` for the reconciled scope; SC-002 (seven fixtures) is not met; the quickstart names `tests.integration.test_characterisation`, which does not exist (see T020) |

Counts: 28 tasks; 20 `[X]`; 8 open (T010, T011-T016, T028).

Owner decisions needed: (1) accept A-11 scope reduction for T017/T019/T020; (2) T010 move or permanent exception;
(3) whether the `17.0/kbi_demo` fixture closes KB-002-T015; (4) quickstart wording for T028.
