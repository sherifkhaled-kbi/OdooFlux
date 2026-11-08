# Verification (006)

## T058: matrix and SC-002 (2026-11-07)

- `PYTHONPATH=src python3 -m odooflux knowledge matrix` regenerated `docs/planning/VERSION_COMPATIBILITY_MATRIX.md`; `matrix --check` reports it up to date. Not committed (no commit authorised in this session).
- SC-002 requires steps 14-15 to 18-19 to reach `RESEARCHED` and `RULES_TESTED`. In the generated matrix every step 14→15 through 18→19 is `RESEARCH_SEEDED` in Research and `NOT_ASSESSED` in Rules. **No step meets SC-002.** Exceptions, all six steps:
  1. `RESEARCHED` not reached: T025 (human peer review) is open; `evidence-verification.md` records 26 of 40 claims verified and 14 cut back. Categories with `NOT_ASSESSED` cells (15→16 XML, Manifest/deps; 16→17 and 17→18 QWeb; 18→19 JS/OWL, QWeb) have no evidence or explicit gap yet.
  2. `RULES_TESTED` not reached: the matrix Rules column is read from `categories.rules.status` in each `compatibility/<step>.research.json` and is `NOT_ASSESSED` there; the research records have not been updated to reflect the rules now implemented. Golden expected trees (T035, T044) are also `PENDING_INDEPENDENT_REVIEW`, and `RULES_TESTED` requires golden migrations.
- Gap list with reasons and proposed tasks: `coverage-gaps.md`.

## PROVISIONAL: quickstart against the 17.0 to 18.0 validation path (2026-11-07)

**PROVISIONAL.** Everything in this section depends on the provisional corpus (`tests/golden_fixtures/17.0/kbi_demo`,
expected tree produced by the current engine, not independently reviewed). It is not certification and not approved
migration truth. T035, T044, T059 and T025 stay unchecked. Technical lines T035-prov and T059-prov record this run.
Certification: PENDING_HUMAN_REVIEW (FHR-A-002, FHR-A-003).

| Quickstart step | Result |
|---|---|
| `python -m odooflux knowledge validate` | `records=200 rules=91 errors=0 warnings=0` |
| `unittest tests.unit.rules.test_rule_coverage` | 6 tests OK |
| `unittest discover -s tests/unit/rules` | 504 tests OK |
| `unittest tests.integration.test_golden_migrations` | 3 tests OK, includes the provisional case `17.0/kbi_demo->18.0` (report and tree byte match) |
| `unittest tests.integration.test_provisional_corpus` | 9 tests OK: byte match, input digest, idempotence, detect-only edits none (SC-005), `--to-version 99.0` rejected with exit 2, 16.0 to 18.0 plan shape (`16.0->17.0`, `17.0->18.0`), marker and authority guard |
| `python -m odooflux knowledge matrix --check` | matrix up to date |
| Manual smoke on a copy of the 17.0 module, target 18.0 (analyze, no writes), after WS-E wiring | exit 1, module status `FAILED` (open critical legacy finding `Tree Tag Renamed`), 17 findings: legacy rules plus `17-18.*` knowledge rules with evidence IDs, `maturity` and `review_required` (name_get, `_name_search`, `user_has_groups`, `mail.shortcode` (python and csv), `numbercall`, `kanban-box`, `group_operator`, `tree` in `view_mode`, RPC service in JS) |
| Same, target 19.0 | adds `18-19.xml.kanban-box-removed`; the `_sql_constraints` and `@api.returns` rules (`18-19.python.sql-constraints-unsupported`, `18-19.python.api-returns-removed`) fire on a module that contains those constructs (`tests/integration/test_knowledge_rules_pipeline.py::test_sql_constraints_and_api_returns_report_for_17_to_19`; `api.returns` is reported once, by the overlapping legacy row `Deprecated Decorator`/`Returns Semantics (review)`) |
| `unittest tests.integration.test_knowledge_rules_pipeline` | 8 tests OK (CLI on a fixture copy; DETECT_ONLY constructs byte-identical under `--fix`; dedup; largest golden module under 10 s) |

Expectations from the quickstart that were **not met at first** and status now:

1. (Met by WS-E, T085-T091.) The knowledge-base rules are now applied by the `migrate` pipeline per plan step, so the
   smoke run lists `17-18.*` (and `18-19.*` for 19.0) findings with evidence IDs, `maturity` and `review_required`;
   a DETECT_ONLY finding is `NEEDS_REVIEW` and never edited. The provisional expected output was regenerated with
   `PYTHONPATH=src python3 tools/update_expectations.py --force`: findings 5 to 17, module status `STATIC_VALIDATED`
   to `NEEDS_REVIEW`, and two knowledge FIX_ENABLED edits added (`group_operator` to `aggregator`, `tree` to `list` in a
   Python `view_mode`). **PROVISIONAL, not approved, needs human review** (WSE-002).
2. The fixture still contains no `_sql_constraints` or `@api.returns` construct (those rules are in the 18-19 step), so
   those two findings are shown by the added test module, not by the fixture.
3. Analyzing the fixture directory in place also scans its own `expected/` tree (the 006 layout nests it). Run smoke
   checks on a copy without `expected/`, as the golden harness does.
4. SC-002 and SC-003 full scope are untouched (KB-006-SC002, KB-006-SC003).
