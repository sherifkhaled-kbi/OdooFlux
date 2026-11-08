# Verification (002)

Date: 2026-11-07. Scope: FC-0.1 reconciliation (see `reconciliation.md`).

## T027: duration

`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -t .` finished in about 18 s wall time (limit 120 s).
Slowest areas: `tests/regression` (about 3 s) and `tests/unit/rules` (about 5 s). No plan needed.

## T028: quickstart (reconciled scope)

| Step | Result |
|---|---|
| 1. Default offline suite | Runs without network (offline guard test) and without Docker. Opt-in tests are skipped with the flag named, for example `runtime (Docker) test; set ODOOFLUX_RUNTIME_TESTS=1 to run` |
| 2. Characterisation | Quickstart names `tests.integration.test_characterisation`; the equivalent is `tests.integration.test_golden_migrations` plus `tests.integration.test_provisional_corpus` (13 tests OK) |
| 3. Regenerate expectations | `PYTHONPATH=src python3 tools/update_expectations.py --force` prints `no changes` on a repeat run (determinism). Without `--force` it refuses while `tests/golden_fixtures` has uncommitted changes |
| 4. Opt-in suites | `ODOOFLUX_RUNTIME_TESTS=1 python -m unittest tests.runtime.test_runtime_placeholder_gate` ran 1 test OK (docker on PATH) |

Success criteria: SC-001 (one command, offline) evidenced; SC-002 (seven fixtures) NOT met, five are DEFERRED_KB
(KB-002-FIX, KB-002-T015); SC-003 evidenced for the one provisional target; SC-004 evidenced by
`test_regression_index.py`; SC-005 (opt-in skip with flag named) evidenced by `test_harness_optin.py`.

## Provisional notice

The only generated expectations are for `17.0/kbi_demo` to 18.0. They pin the current engine's output and are
PROVISIONAL (FHR-A-002). The expected report also pins the report model: when the report schema changes, regenerate with
`tools/update_expectations.py --force` and review the diff.
