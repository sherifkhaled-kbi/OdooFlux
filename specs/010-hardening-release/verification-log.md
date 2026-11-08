# Verification log: feature 010 (hardening and release readiness)

Written 2026-11-07 by an implementation agent. It records evidence and red runs; it records no approval.

## Red runs (tests written before the implementation)

| Task | Red run | Result |
|---|---|---|
| T001 | `python -m unittest tests.benchmarks.test_corpus_gen` before `corpus_gen.py` | ImportError (errors=1) |
| T014 | `test_hotpath_equivalence` before each optimisation | 4 errors/failures, then 2, then 4 (token helper, file_kind cache, Names cache, shared Document, node cache, parse memo, lazy spans, JS memo) |
| T003, T004, T005 | tests run with `rtm_tools.py` moved aside (the first draft of `rtm_tools.py` existed before the tests; it was set aside to record the red run, then restored) | ImportError (errors=2) |
| T006, T007 | `test_support_statement` before `support_statement.py` | ImportError |
| T009, T010 | `test_parallel_determinism`, `test_incremental` before `parallel.py`, `incremental.py` | ImportError (errors=2) |
| T012, T013 (CLI) | `test_cli_performance_options` before `--jobs`/`--incremental` | errors=4 (argparse exits) |
| T011 | `test_run_benchmarks` before `run_benchmarks.py` | ImportError |
| T015, T016, T017 | `test_audit_log`, `test_secret_scan`, `test_api_key_removed` before the modules | ImportError x3 |

Defects found by the tests and fixed (each with the test that found it): worker stub without `backup_dir` (TST-010-004),
index never stored after a blocked worker (TST-010-005), the AI scenario needed the `evidence_excerpt` grant
(TST-010-008), `stage_edits` wrapped by an existing test with three positional arguments (the staging audit moved to
`audit_staged`, called after `stage_edits`).

## Evidence

- RTM gate: `python tests/unit/release/rtm_tools.py` reports 0 failures. Real-data warnings, if any, are printed by the tool.
- Benchmark (300 x 30, seed 1, median of 5, reference machine): serial 13.3 s, parallel 3.8 s (12 workers), incremental
  2.5 s with 0 files parsed; report digests identical across the three modes. Results: `tests/benchmarks/results/`.
- Secret scan: canary secrets in the environment and the credential file, external provider with a recorded transport;
  0 matches in state, run log, audit log, AI cache, reports (JSON, SARIF, HTML), module copies, console and log output.

## Not run in this log

Quickstart scenario 4 (failure injection) and the release-gate tests (T020 to T022) are not implemented. T024 is open.

## T020 / T021 failure injection (TST-010-010)

Red first: `test_failure_injection` ran with 3 errors; one was a test expectation (resume after a lost checkpoint is
refused by design, contracts/recovery.md), two were defect F-INJ-1 (a failing restore after a promotion fault raised out
of `promote_module` instead of blocking the module). Fix: `_restore` in `src/odooflux/core/jobs/promote.py` skips files
already equal to the backup, catches OSError per file, logs `restore_failed`, and the module is BLOCKED with a rollback
hint. Green: 13 injection tests plus regression `F-INJ-1`; `test_promote_failure`, `test_rollback`, `test_resume` pass.
Repair attempts used: 1. Open issues: none.

## T024 quickstart record (2026-11-07, orchestrator, targeted runs)

1. `tests.unit.release.test_rtm_completeness`: 14 tests OK; `python3 tests/unit/release/rtm_tools.py` on the real RTM: RESULT PASS (six REQs carry partial DEFERRED_KB rows).
2. `ODOOFLUX_BENCHMARKS=1 python3 tests/benchmarks/run_benchmarks.py --modes serial,parallel,incremental`: RESULT PASS; serial, parallel and incremental report digests identical; incremental parsed 0 files (median 2.5 s). Results: `tests/benchmarks/results/2026-11-07-c9914e6.json`. Budgets `approved_by` is PENDING_HUMAN_REVIEW.
3. `tests.integration.hardening.test_secret_scan`: 9 tests OK, 0 canary matches.
4. `tests.integration.hardening.test_failure_injection`: 13 tests OK.
5. `odooflux support-statement --check`: SUPPORT_STATEMENT.md up to date (0 supported, 17.0 to 18.0 experimental and PROVISIONAL).
Not covered: maintainer sign-off (T023) and any human review.
