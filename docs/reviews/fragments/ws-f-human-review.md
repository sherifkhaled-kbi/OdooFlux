# Register fragment: workstream F (dry-run diff, provisional label, runtime run records)

Status of every item: PENDING_HUMAN_REVIEW. Nothing here records an approval. IDs are provisional (`WSF-nnn`);
the orchestrator assigns the final `FHR-nnn` on consolidation. Technical parts are IMPLEMENTED and VERIFIED
(ADR-019); the certification parts below stay open. No rule, evidence record or maturity was added or changed.

## WSF-001 Runtime run records and the RUNTIME_VALIDATED mark (T029-data)

- **Task / requirement:** 008 T029 (original stays unchecked; T029-gen is the technical part), REQ-VAL-004, REQ-EVD-006, plan A-6.
- **Component:** `src/odooflux/knowledge/runtime_runs.py`, `knowledge/schemas/runtime_runs.schema.json`, `knowledge/compatibility/runtime_runs.json` (shipped with `runs: []`), `knowledge/matrix.py` (two new columns), `docs/planning/VERSION_COMPATIBILITY_MATRIX.md`.
- **What to review:** (1) The record schema (id, step, versions, fixture ids, image digest, source image digest, date, tool version, result, behavioural) and the rule that a step is marked only when its latest valid record passes. (2) Which golden migration and step a record may cover. The opt-in runtime suite passed once on 2026-11-07 (9 tests, odoo:18.0 and 19.0, postgres:16) but exercises synthetic framework fixtures, so no record was written. (3) Whether `RUN_FAILED` and the `Behavioural verified` column wording are acceptable matrix vocabulary.
- **Why:** a `RUNTIME_VALIDATED` mark is a support claim. Only a person can decide that a recorded run supports it, and the run must really have executed.
- **Evidence / tests:** `tests/unit/knowledge/test_matrix_runtime_runs.py` (record absent, passing, failing, later failure, malformed, unparseable, step mismatch, no source image, hand-edited cell refused), `tests/integration/knowledge/test_matrix_committed.py`, opt-in `tests/runtime/*` (see 008 quickstart verification log).
- **Risk:** MEDIUM. A hand-written record would be trusted by the generator; the schema checks shape and consistency, not truth of the run.
- **Reviewer qualifications:** maintainer of the runtime layer with access to Docker and the Odoo images.
- **Certification impact:** blocks any statement that a transition is runtime validated; framework completion is unaffected.

## WSF-002 Provisional label rule and regenerated provisional report

- **Task / requirement:** ADR-019.4, 009 US3 follow-up, FHR-A-002, FHR-A-003.
- **Component:** `src/odooflux/core/orchestrator/provisional.py`, `--provisional-corpus` in `cli/main.py`, `cli/migrate.py`, `tests/golden_fixtures/17.0/kbi_demo/expected/18.0/report.json`.
- **What to review:** (1) The label wording and the trigger: the flag, or a `PROVISIONAL.md` in the module directory or any parent. A provisional corpus copied elsewhere loses the marker and needs the flag. (2) The regenerated expected report: only `provisional: {active: true, labels: [...]}` was added (written by `tools/update_expectations.py --force`); it stays PROVISIONAL and unreviewed.
- **Why:** reports and SARIF must not let provisional results look like approved migration truth.
- **Evidence / tests:** `tests/integration/reporting/test_provisional_cli.py` (JSON, SARIF, HTML, terminal; flag, marker, ordinary run), `tests/integration/test_provisional_corpus.py`.
- **Risk:** LOW. A run on an unmarked copy without the flag would carry no label.
- **Reviewer qualifications:** maintainer who owns the report model and support statements.
- **Certification impact:** none for framework completion.

## WSF-003 Dry-run computes edits in memory (WSD-05 follow-up)

- **Task / requirement:** 009 T019/T026 follow-up, REQ-REP-004, FR-001 (dry run writes nothing), SC-005 unchanged.
- **Component:** `RunOptions.computes_edits` in `src/odooflux/core/orchestrator/run.py`; `cli/report_outputs.py` note now only for analyze.
- **What to review:** that a dry run now runs the transforming rule step (in memory only) and reports `planned_files`; fix and write behaviour, backups and promotion are unchanged and still gated on `writes`. Confirm no consumer treated an empty dry-run `edits` list as meaningful.
- **Why:** this changes what a dry run does internally, although it writes nothing.
- **Evidence / tests:** `tests/integration/reporting/test_dry_run_diff.py` (non-empty, module untouched, patch equals write-mode patch, applies with `patch -p1` to a pristine copy, analyze still empty), `tests/regression/test_p0_safety_readonly.py`.
- **Risk:** LOW.
- **Reviewer qualifications:** maintainer familiar with the orchestrator and the P0 safety guarantees.
- **Certification impact:** none.
