# Quickstart: Hardening and Release Readiness (validation scenarios)

Planned commands (not implemented).

1. `python -m unittest tests.unit.release.test_rtm_completeness` → 0 unmapped REQs.
2. `ODOOFLUX_BENCHMARKS=1 python tests/benchmarks/run_benchmarks.py --modes serial,parallel,incremental` → results JSON. Budgets met. Parallel digest equals serial digest.
3. `python -m unittest tests.integration.hardening.test_secret_scan` → 0 canary matches.
4. `python -m unittest tests.integration.hardening.test_failure_injection` → all injection points pass.
5. `odooflux support-statement --out docs/planning/SUPPORT_STATEMENT.md` → only fully validated paths marked supported.
