# Register fragment: workstream E (knowledge rules in the migrate pipeline)

Status of every item: PENDING_HUMAN_REVIEW. Nothing here records an approval. IDs are provisional (`WSE-nnn`);
the orchestrator assigns the final `FHR-nnn` on consolidation. Technical parts are IMPLEMENTED and VERIFIED
(ADR-019); the certification parts below stay open. No rule, evidence record or maturity was added or changed:
the 91 rules keep DETECT_ONLY 78, FIX_ENABLED 10, DRAFT 3 (asserted by a test).

## WSE-001 Legacy tables and knowledge rules run side by side; overlap decisions

- **Task / requirement:** 006 T086, T089, T092 (certification part), FR-017, `legacy_disposition.json` (keep/correct/retire), SC-005.
- **Component:** `src/odooflux/rules/shared/legacy_overlap.py`, `src/odooflux/core/orchestrator/knowledge_rules.py` (`deduplicate`), legacy tables in `rules/shared/legacy_rules.py`.
- **What to review:** (1) Before this work `migrate` ran only the legacy tables; the 91 knowledge rules were bound by the loader but never executed. They now run per plan step. (2) The disposition table marks many legacy rows `retire` or `correct`, but the legacy rows were NOT retired or changed, because that would alter existing legacy and golden results. Where both report the same construct on the same file line, only the legacy finding is emitted (15 knowledge rules are mapped to their legacy categories; the mapping is checked against the disposition's `new_rule_ids`). (3) Where the disposition says the legacy row is wrong for some versions (for example `Attrs Attribute` and `Deprecated Decorator` apply to every target), the legacy finding still appears and the knowledge rule's version window is not applied to it. Decide whether to retire or correct those rows and, with them, whether the knowledge finding should win.
- **Why:** retiring or correcting legacy rows changes reported results and fix behaviour; it needs a person who can judge migration correctness, not a framework change.
- **Evidence / tests:** `tests/unit/test_knowledge_rule_selection.py` (selection per step, binding, overlap map vs disposition, dedup, maturities unchanged), `tests/integration/test_knowledge_rules_pipeline.py::test_each_construct_is_reported_once`.
- **Risk:** MEDIUM. Reports can carry a legacy finding whose rule is over-broad (it fires outside its real version window) in place of the better-evidenced knowledge finding. Lines with two different constructs are not merged. Existing behaviour is unchanged.
- **Reviewer qualifications:** Odoo migration engineer familiar with the 12 to 19 changes and the legacy script's rule table.
- **Certification impact:** none on framework completion; open retire/correct decisions limit any claim that report content is migration-correct.

## WSE-002 Regenerated PROVISIONAL expected output for 17.0 to 18.0

- **Task / requirement:** 006 T091, T035/T059 (certification parts stay open), FHR-A-002, FHR-A-003, ADR-019.4.
- **Component:** `tests/golden_fixtures/17.0/kbi_demo/expected/18.0/report.json` and `tree/` (written only by `PYTHONPATH=src python3 tools/update_expectations.py --force`).
- **What to review:** the diff against the previous provisional output. `report.json`: findings 5 to 17; module status `STATIC_VALIDATED` to `NEEDS_REVIEW` (`open_review_findings`); new findings with evidence IDs, `maturity`, `review_required`: `17-18.xml.cron-numbercall-removed`, `17-18.python.name-get-removed`, `17-18.python.name-search-to-search-display-name`, `17-18.python.user-has-groups-removed`, `17-18.python.model-renamed-mail-canned-response`, `17-18.csv.model-renamed-mail-canned-response`, `17-18.js.rpc-service-removed`, `17-18.xml.kanban-box-deprecated` (all DETECT_ONLY, `NEEDS_REVIEW`, not edited), and FIXED by FIX_ENABLED rules: `17-18.python.group-operator-renamed` (2), `17-18.xml.tree-to-list` (2, the `view_mode` strings in `models/demo.py` and `views/demo_views.xml`). `tree/models/demo.py` changed: `group_operator=` became `aggregator=` and `'tree,form'` became `'list,form'`; no other file changed. `INDEX.json` input digest unchanged.
- **Why:** the expected output pins what the engine does now; it is not migration truth. Whether these edits are correct for a real 17.0 to 18.0 module (for example the `view_mode` string inside a Python action dict) needs a human.
- **Evidence / tests:** `tests/integration/test_golden_migrations.py`, `tests/integration/test_provisional_corpus.py` (byte match, idempotence, DETECT_ONLY constructs survive, markers). Evidence IDs are those of the rule rows; none were added.
- **Risk:** MEDIUM. A wrong rule would now be baked into a byte-exact expectation. The corpus is labelled PROVISIONAL in every marker file.
- **Reviewer qualifications:** Odoo 17/18 developer with an independent 17.0 and 18.0 reference.
- **Certification impact:** blocks any statement that the 17.0 to 18.0 path is certified; provisional label stays.

## WSE-003 Performance cost of running the knowledge rules

- **Task / requirement:** 006 SC-006, T090, 003 SC-007 (benchmark baseline).
- **Component:** parse caches in `parsers/python/document.py`, `parsers/xml/document.py`, `parsers/python/spans.py` (`all_nodes`), `rules/python/generic.py`.
- **What to review:** the analysis benchmark (300 generated modules, 9 000 files, 14.0 to 19.0, `tests/benchmarks/bench_analyze.py`) rose from the recorded P2 baseline of about 1.1 s to about 10 to 11 s on this machine (101 s before the parse and AST caches). The largest golden module analyses in well under 1 s (SC-006 limit 10 s). The caches keep the most recent 16 parses by `(path, text)`; parsed documents are treated as read-only.
- **Why:** each of about 60 bound rules re-read every file of its kind; P9 sets the enforced budgets.
- **Evidence / tests:** `test_largest_golden_module_analysis_is_fast`; the benchmark is opt-in (`ODOOFLUX_BENCH=1`, passes).
- **Risk:** LOW to MEDIUM for large repositories; not a correctness risk unless a detector mutates a parsed tree (none does).
- **Reviewer qualifications:** maintainer who owns performance budgets.
- **Certification impact:** none for framework completion; a P9 budget could require further optimisation.
