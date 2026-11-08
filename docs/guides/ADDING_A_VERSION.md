# Adding a version (data only)

A new Odoo major is added by data and fixtures. The engine and the CLI do not change (REQ-VER-005).

1. **Version record.** Add an entry to `versions` in `src/odooflux/knowledge/versions.json`:
   `id` (`M.0`), `python_min`, `python_max` (or `null`), `online_releases`, `support_status`.
2. **Transitions.** Add the transition from the previous version to the new one in `transitions`:
   `source`, `target`, and `research_status`. A transition missing from this list is treated as
   `NOT_ASSESSED`, which blocks the plan unless `--allow-unverified` is given.
3. **Fixtures.** Add the golden fixtures for the new step under `tests/golden_fixtures/`.
4. **Check.** Run `python -m unittest discover -s tests -p "test_*.py"`. The adding-version procedure
   test (TST-003-013) and the synthetic-version test (TST-003-009) must still pass.

Rules for a new step are a separate change (P5). Until then the legacy rules apply to every pair.
