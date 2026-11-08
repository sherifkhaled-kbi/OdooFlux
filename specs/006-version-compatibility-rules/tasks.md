---
description: "Task list for feature 006 — Version Compatibility Rules (Phase P5)"
---

# Tasks: Version Compatibility Rules

**Input**: Design documents from `/specs/006-version-compatibility-rules/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/rule-catalogue.md; features 004 and 005 exited
**Tests**: Required (Principle V). Per rule: positive, negative, and (fixers) idempotence. Write them first.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…) — Done when: …`

Research-task rule: a task marked **[RESEARCH]** produces evidence records
(`knowledge/evidence/EV-3NN.json`, feature 004 format, status `DOCUMENTED_NOT_TESTED`) or a
recorded negative result, plus an updated `<step>.research.json` and gap status in `gaps.json`.
It must cite only allow-listed official sources at pinned SHAs. Rules gated on a gap MUST NOT
start before that gap's research task is done.

---

## Phase 1: Setup

- [X] T001 Create the rule modules and test/fixture directories listed in plan.md §Source Code; record the new `tools/` directory in `docs/planning/PROJECT_STRUCTURE.md` (REQ-PY-002) — Done when: imports succeed and the structure test passes.
- [X] T002 Write the rule-coverage test that loads all rules and fails if any `FIX_ENABLED` rule lacks positive/negative/idempotence tests, or any `DETECT_ONLY` rule lacks positive/negative tests, or any `review_required` rule has a fixer, in `tests/unit/rules/test_rule_coverage.py` (REQ-TST-002, REQ-PY-003; TST-006-001) — Done when: it passes trivially with 0 rules and fails on a fixture rule missing a test.
- [X] T003 [P] Implement `tools/extract_core_modules.py` (reads an official clone at a SHA, lists `addons/*` and `odoo/addons/*` with `__manifest__.py`, writes `core_modules/<ver>.json` and an evidence record) with a unit test on a synthetic repository in `tests/unit/rules/test_extract_core_modules.py` (REQ-DEP-001; TST-006-002) — Done when: the test passes and the output is sorted and deterministic.

## Phase 2: Foundational (blocks all stories)

- [X] T004 Write failing tests for the Python generic detectors/fixers (`keyword_in_call`, `rename_keyword`, `remove_keyword`, `remove_decorator`, `flag_call`, `flag_method_override`, `flag_class_attribute`, `rewrite_attribute_access`) with import-alias resolution, in `tests/unit/rules/python/test_generic.py` (REQ-PY-002; TST-006-003) — Done when: ≥ 30 cases fail.
- [X] T005 Implement `src/odooflux/rules/python/generic.py` on feature 005 helpers (REQ-PY-002, REQ-TRF-003) — Done when: TST-006-003 passes and each fixer is idempotent.
- [X] T006 [P] Write failing tests for XML/QWeb generic rules (`rename_tag`, `remove_attribute`, `flag_element`, `flag_attribute`, `rename_directive`, `rewrite_view_mode`) in `tests/unit/rules/xml/test_generic.py` (REQ-XML-003, REQ-XML-005; TST-006-004) — Done when: ≥ 20 cases fail.
- [X] T007 Implement `src/odooflux/rules/xml/generic.py`, `src/odooflux/rules/xml/view_mode.py`, and `src/odooflux/rules/qweb/generic.py` (REQ-XML-003, REQ-XML-005) — Done when: TST-006-004 passes.
- [X] T008 Extend the rule loader to bind `detector_ref`/`fixer_ref` with `params`, enforce `review_required ⇒ no fixer` and the maturity/test constraints from data-model.md, in `src/odooflux/rules/shared/loader.py` with tests in `tests/unit/rules/test_binding.py` (REQ-PY-003, REQ-EVD-001; TST-006-005) — Done when: invalid bindings fail loading with specific errors.
- [X] T009 Implement the golden-migration harness (write mode into a temp state dir, normalised report compare, tree compare) in `tests/integration/test_golden_migrations.py` (REQ-TST-003; TST-006-006) — Done when: it runs with zero fixtures and fails on a deliberately mismatched sample.

**Checkpoint**: generic rule machinery ready.

---

## Phase 3: Research (blocking gated rules; parallel)

- [X] T010 [P] [RESEARCH] G-R-20: locate the 17.0 modifier-expression evaluation (names in context, falsy semantics, combination) in `odoo/odoo` 17.0 at a pinned SHA (`addons/web/static/src/` view compilers/evaluators and `ir_ui_view.py`); choose converter mode `literal` or `falsy` (REQ-XML-002, REQ-EVD-001) — Done when: evidence records cite exact path:line, and research.md R-5 of feature 005 is updated with the chosen mode.
- [X] T011 [P] [RESEARCH] G-R-07: determine whether 18.0 accepts `<tree>` arch roots or `tree` in `view_mode` (RNG files, `ir_ui_view.py`, `ir_actions.py`) (REQ-XML-003) — Done when: a recorded result sets `17-18.xml.tree-to-list` severity (CRITICAL if rejected, WARNING if deprecated-but-accepted).
- [X] T012 [P] [RESEARCH] `_context` replacement at 19.0 SHA (`odoo/orm/models.py` near EV-209) (REQ-PY-002) — Done when: an evidence record exists, or the `_context` part of `18-19.python.env-shortcuts-deprecated` is dropped with a reason.
- [X] T013 [P] [RESEARCH] G-R-15: `SavepointCase` replacement semantics in 17.0 `odoo/tests/common.py` (REQ-PY-002) — Done when: evidence decides whether `16-17.tests.savepointcase-removed` may rename to `TransactionCase`.
- [X] T014 [P] [RESEARCH] G-R-16: `user_has_groups` replacement in 18.0 (`has_group` presence, `has_groups` spec format) (REQ-PY-002) — Done when: evidence decides the fixer or keeps the rule detect-only.
- [X] T015 [P] [RESEARCH] G-R-06: data-file tags and roots in `odoo/tools/convert.py` and `odoo/import_xml.rng`/`odoo/addons/base/rng` for 12.0–17.0 (`<openerp>`, `<url>`, `<act_window>`, `<report>` expansion fields) (REQ-XML-003) — Done when: evidence covers each tag per version and the expansion field mapping for act_window/report.
- [X] T016 [P] [RESEARCH] G-R-05: asset bundle names and the XML-template-to-manifest transition (14.0 vs 15.0 `ir_asset.py`, `web/__manifest__.py`) (REQ-JS-003) — Done when: evidence maps legacy template inheritance targets to manifest bundle keys, or records why mapping is not mechanical.
- [X] T017 [P] [RESEARCH] G-R-04: QWeb directive changes 14.0→19.0 beyond EV-201…203 (`ir_qweb.py` directive list per version) (REQ-XML-005) — Done when: each version's directive set is recorded and differences have evidence records.
- [X] T018 [P] [RESEARCH] G-R-09: `<chatter/>` introduction and `oe_chatter`/`message_ids` support per version (`addons/mail/static/src/**` form compiler/renderer) (REQ-XML-003) — Done when: evidence states the first version supporting `<chatter/>` and the last supporting the legacy div, with path:line.
- [X] T019 [P] [RESEARCH] G-R-03 and G-R-08: OWL version per Odoo release (`addons/web/static/lib/owl/owl.js` header), legacy `Widget`/`odoo.define(name, function(require))` support window, service/registry API changes 15.0→19.0 (REQ-JS-002) — Done when: evidence records per version, and a list of candidate JS/OWL rules with evidence.
- [X] T020 [P] [RESEARCH] G-R-10: security data changes (ACL CSV columns, `ir.rule` fields, `res.groups` fields) 14.0→19.0 (REQ-ACL-001) — Done when: evidence records or a negative result exists per step.
- [X] T021 [P] [RESEARCH] G-R-11: controller/HTTP changes 14.0→18.0 (`odoo/http.py` route params) (REQ-PY-002) — Done when: evidence records or a negative result exists per step.
- [X] T022 [P] [RESEARCH] G-R-14: 12.0 `sudo(user)` vs 13.0 `with_user`/`sudo` semantics (12.0 `odoo/models.py:4789`, 13.0 `:5157`/`:5189`) (REQ-PY-003) — Done when: evidence records the equivalence or a non-equivalence; the rule stays review-only unless equivalence is proven.
- [X] T023 [P] [RESEARCH] G-R-17 and G-R-18: legacy claims (Html sanitize, `attachment=False`, `_auto_init`, `phone.validation.mixin`) and backend CSS class changes (REQ-EVD-003) — Done when: each claim gets evidence or is marked `NOT_APPLICABLE`/retired in `legacy_disposition.json`.
- [X] T024 [P] [RESEARCH] G-R-01: source diff research for steps 12-13, 13-14, 14-15 across all categories (no changelog exists, EV-015) (REQ-EVD-001) — Done when: each category of those steps is covered by records or explicit gaps (status RESEARCH_SEEDED or RESEARCHED recorded).
- [ ] T025 [RESEARCH] Peer-review the research records for steps 14-15…18-19 and set `peer_reviewed: true` / `RESEARCHED` where complete (REQ-EVD-001, REQ-EVD-006) — Done when: the reviewer reproduced ≥ 1 location per record from the record alone; the step status is updated. — OPEN (partial verification 2026-11-07: EV-390..396, 400..406, 410..427 source-verified by `tools/verify_evidence.py`, 14 descriptions corrected; peer_reviewed/RESEARCHED NOT set: no independent qualified reviewer, EV-3xx records outside this pass, and NOT_ASSESSED/RESEARCH_SEEDED categories remain; see evidence-verification.md)

---

## Phase 4: User Story 1 — 17.0 → 18.0/19.0 rules (P1) 🎯 MVP

- [X] T026 [P] [US1] Write positive/negative/idempotence fixtures and tests for `17-18.xml.tree-to-list` (XML arch, `view_mode` field, Python action dict `view_mode`, string literals not touched) in `tests/unit/rules/xml/test_17_18_tree_to_list.py` (REQ-XML-003; TST-006-007) — Done when: tests fail.
- [X] T027 [US1] Implement and register `17-18.xml.tree-to-list` (after T011) in `knowledge/compatibility/17-18.rules.json` (REQ-XML-003) — Done when: TST-006-007 passes.
- [X] T028 [P] [US1] Tests + rule `17-18.python.group-operator-renamed` (REQ-PY-002; TST-006-008) — Done when: tests pass; maturity FIX_ENABLED.
- [X] T029 [P] [US1] Tests + detect-only review rules `17-18.python.name-get-removed`, `17-18.python.name-search-to-search-display-name`, `17-18.xml.cron-numbercall-removed`, `17-18.xml.kanban-box-deprecated` (REQ-PY-003, REQ-XML-003; TST-006-009) — Done when: positive/negative tests pass and SC-005 holds (no edits).
- [X] T030 [US1] Tests + rule `17-18.python.user-has-groups-removed` at the maturity decided by T014 (REQ-PY-002; TST-006-010) — Done when: tests pass at the recorded maturity.
- [X] T031 [P] [US1] Tests + rules `18-19.python.route-type-json` and `18-19.python.env-shortcuts-deprecated` (after T012) (REQ-PY-002; TST-006-011) — Done when: FIX_ENABLED, with idempotence passing.
- [X] T032 [P] [US1] Tests + review rules `18-19.python.api-returns-removed`, `18-19.python.read-group-deprecated`, `18-19.python.osv-deprecated`, `18-19.xml.kanban-box-removed` (REQ-PY-003, REQ-XML-003; TST-006-012) — Done when: tests pass; 0 edits.
- [X] T033 [US1] Implement bespoke `src/odooflux/rules/python/sql_constraints.py` for `18-19.python.sql-constraints-unsupported` (detect class attribute, report each constraint tuple with suggested `models.Constraint` form as text only) with tests (REQ-PY-003; TST-006-013) — Done when: tests pass; CRITICAL review finding cites EV-006/EV-116.
- [X] T034 [US1] Tests + rule `18-19.any.res-users-groups-id` across Python, XML domains/evals, and CSV (detect-only review) (REQ-PY-003, REQ-ACL-001; TST-006-014) — Done when: tests pass for all three file kinds.
- [ ] T035 [US1] Create `expected/18.0/` and `expected/19.0/` for the 17.0 golden modules and pass the golden harness (REQ-TST-003; TST-006-015) — Done when: 100 % byte match.
- [X] T035-prov [US1] Technical part of T035 (ADR-019): PROVISIONAL golden corpus for 17.0 to 18.0 only. `tests/golden_fixtures/17.0/kbi_demo` with `expected/18.0/{tree,report.json}` produced by `tools/update_expectations.py` from the current engine; every directory carries `PROVISIONAL.md`; `INDEX.json` authority `PROVISIONAL`. Verified by `tests/integration/test_golden_migrations.py` and `tests/integration/test_provisional_corpus.py` (byte-for-byte match, idempotence, SC-005, unsupported target rejected, label guard). 17.0 to 19.0 is not covered (KB-006-T035r). The expected tree pins what the engine does today, not independently reviewed truth.
  - Certification: PENDING_HUMAN_REVIEW (FHR-A-002). T035 itself stays unchecked until an independent reviewer approves the expected tree.

---

## Phase 5: User Story 2 — 14.0–16.0 multi-step rules (P1)

- [X] T036 [P] [US2] Tests + rule `16-17.python.warning-exception` (imports incl. aliases, raises, missing `UserError` import injection) in `src/odooflux/rules/python/exceptions.py` (REQ-PY-002; TST-006-016) — Done when: outputs compile; idempotent.
- [X] T037 [US2] Bind `16-17.xml.attrs-removed` and `16-17.xml.states-attribute-removed` to the feature 005 converter with the mode from T010, and add rule-level fixtures (REQ-XML-002; TST-006-017) — Done when: tests pass; maturity FIX_ENABLED only if T010 resolved G-R-20, otherwise DETECT_ONLY with a recorded reason.
- [X] T038 [P] [US2] Tests + review rules `16-17.python.field-states-parameter`, `16-17.python.name-get-deprecated`, `16-17.python.read-group-signature`, `16-17.python.message-post-with-template` (REQ-PY-003; TST-006-018) — Done when: tests pass; 0 edits.
- [X] T039 [US2] Tests + rules `16-17.xml.act-window-tag`, `16-17.xml.report-tag` (fixers only if T015 produced a field mapping) in `src/odooflux/rules/xml/data_tags.py` (REQ-XML-003; TST-006-019) — Done when: tests pass at the recorded maturity; outputs are well-formed.
- [X] T040 [US2] Tests + rule `16-17.tests.savepointcase-removed` at the maturity from T013 (REQ-PY-002; TST-006-020) — Done when: tests pass.
- [X] T041 [P] [US2] Tests + rules `15-16.python.search-args-keyword`, `15-16.python.x2many-limit-attribute`, `15-16.python.removed-field-attributes` (FIX) and `15-16.python.browse-str-ids`, `15-16.python.deprecated-model-methods`, `15-16.python.fields-view-get` (detect) (REQ-PY-002, REQ-PY-003; TST-006-021) — Done when: tests pass.
- [X] T042 [P] [US2] Tests + rules `14-15.qweb.t-esc-deprecated` (FIX) and `14-15.qweb.t-raw-deprecated` (review), plus any rules from T017 (REQ-XML-005; TST-006-022) — Done when: tests pass.
- [X] T043 [P] [US2] Tests + rules `12-13.python.api-multi-removed` (FIX), `12-13.python.api-one-removed`, `12-13.python.sudo-user-argument` (review; maturity per T022) (REQ-PY-002, REQ-PY-003; TST-006-023) — Done when: tests pass; boolean `sudo(True/False)` produces no finding.
- [ ] T044 [US2] Create golden expected trees for source 14.0, 15.0, and 16.0 modules to each later target and pass the harness (REQ-TST-003; TST-006-024) — Done when: 100 % byte match for all pairs in scope.

---

## Phase 6: User Story 3 — Manifests, dependencies, references, security (P2)

- [X] T045 [P] [US3] Tests + shared rules `*.manifest.parse-error`, `*.manifest.version-prefix` (suffix preserved), `*.manifest.not-installable`, `*.manifest.missing-data-file`, `*.manifest.load-order` in `src/odooflux/rules/manifest/{hygiene,files}.py` (REQ-MAN-003, REQ-MAN-002; TST-006-025) — Done when: tests pass.
- [X] T046 [US3] Run `tools/extract_core_modules.py` for 12.0–19.0 at the registry SHAs and commit `core_modules/*.json` and their evidence records (REQ-DEP-001) — Done when: 8 files validate, each citing an evidence record with the SHA.
- [X] T047 [US3] Tests + rule `*.deps.unknown-dependency` (core list + scanned modules; WARNING for unknown, CRITICAL for modules present in the source core list but absent in the target core list) in `src/odooflux/dependencies/core_modules.py` (REQ-DEP-001; TST-006-026) — Done when: tests pass, including an Enterprise-like unknown name → WARNING.
- [X] T048 [US3] Implement the reference index and `*.refs.dangling-reference` (XML IDs, models, fields among scanned modules; core refs reported "unverified (core)") in `src/odooflux/dependencies/references.py` (REQ-DEP-003, REQ-VAL-003; TST-006-027) — Done when: a fixture with a dangling XML ID, unknown field, and unknown model yields 3 findings.
- [X] T049 [US3] Tests + security scanners for ACL CSV and record rules, plus any rules from T020, in `src/odooflux/rules/security/{acl_csv,record_rules}.py` (REQ-ACL-001; TST-006-028) — Done when: tests pass.

---

## Phase 7: User Story 4 — Business-logic risk inventory (P2)

- [X] T050 [US4] Write failing inventory tests covering all 10 classes in research.md R-7 in `tests/unit/analyzers/test_risk_inventory.py` (REQ-BIZ-001; TST-006-029) — Done when: ≥ 1 positive and 1 negative case per class.
- [X] T051 [US4] Implement `src/odooflux/analyzers/risk_inventory.py` and attach the inventory to the module report section (REQ-BIZ-001) — Done when: TST-006-029 passes and the inventory appears in golden reports.

---

## Phase 8: User Story 5 — JavaScript/OWL and assets (P3)

- [X] T052 [US5] Tests + rule `17-18.js.rpc-service-removed` (detect via lexer or adapter; review) in `src/odooflux/rules/javascript/generic.py` (REQ-JS-002; TST-006-030) — Done when: tests pass in both adapter modes.
- [X] T053 [US5] Implement JS/OWL rules derived from T019 evidence in `src/odooflux/rules/{javascript,owl}/`, each with positive/negative tests (REQ-JS-002; TST-006-031) — Done when: every rule from T019's candidate list is implemented or recorded as not implementable.
- [X] T054 [US5] Tests + rules `14-15.manifest.qweb-key` and XML asset-template detection (fix only if T016 gives a mechanical mapping) in `src/odooflux/rules/assets/generic.py` (REQ-JS-003; TST-006-032) — Done when: tests pass at the recorded maturity.

---

## Phase 9: Polish & Cross-Cutting

- [X] T055 Record all 68 legacy dispositions in `knowledge/compatibility/legacy_disposition.json` per MIGRATION_RULE_ENGINE.md, updated by research results, with a test that every legacy row is present (REQ-PY-002, REQ-EVD-003; TST-006-033) — Done when: the test reports 68/68.
- [X] T056 Prove the add-a-version procedure: a test adds synthetic version `99.0` with one step rule and a fixture via data and test files only, then runs a migration (REQ-VER-005; TST-006-034) — Done when: the test passes and `git diff --stat` of the test fixture setup touches no `src/odooflux/**/*.py` file.
- [X] T057 [P] Performance test: analyse the largest golden module (≥ 50 files) < 10 s in `tests/benchmarks/test_rules_perf.py` (REQ-PY-002; TST-006-035) — Done when: it passes on the reference machine.
- [X] T058 Regenerate the matrix (`odooflux knowledge matrix`) and commit it; verify that the steps meet SC-002 or list the exceptions (REQ-EVD-006, REQ-TST-003) — Done when: `--check` passes and the exceptions are listed in `specs/006-version-compatibility-rules/verification.md`.
- [ ] T059 Run quickstart.md and record the outputs in `specs/006-version-compatibility-rules/verification.md` (REQ-TST-002, REQ-TST-003) — Done when: all expectations are met.
- [X] T059-prov Technical part of T059 (ADR-019): quickstart commands run against the PROVISIONAL 17.0 to 18.0 path; outputs recorded under the "PROVISIONAL" heading of `verification.md`, including the expectations that are NOT met (knowledge rules are not yet applied by the migrate pipeline, so the `_sql_constraints` / `@api.returns` smoke expectation fails). Reviewed on the provisional path only.
  - Certification: PENDING_HUMAN_REVIEW (FHR-A-003). T059 itself stays unchecked.

---

## Phase 10: Coverage-gap amendment (DRAFT; see spec.md Amendment 2026-11-07 and AMENDMENT-REVIEW.md)

Scope: spec work approved; every implementation task needs owner acceptance of its rules. Do not touch `*.rules.json`, evidence, `legacy_disposition`, golden corpus, T025/T035/T044/T059 before the stated gate.

### Tests first (no owner decision needed, tests must fail until implementation)

- [X] T060 [P] Write failing non-regression test for `bind_rule(run_params=...)` per contracts/rule-catalogue.md (FR-017) in `tests/unit/rules/test_bind_run_params.py` — Done when: tests for None, undeclared key ignored, static/run key conflict, missing run key skip all exist and fail for the right reason. Evidence: none (interface).
- [X] T061 [P] Write failing tests for `flag_version_prefix` bound per run: target equal, different, no context (FR-019) — Done when: they exist and fail. Evidence: none (policy).
- [X] T062 [P] Write positive/negative fixtures and tests for the renamed-model family on `payment.acquirer` (Python, XML, CSV; substring, comment and multi-step edge cases) (FR-018) in `tests/golden_fixtures/rules/15-16.*.model-renamed-payment-provider/` — Done when: they exist and fail. Evidence: EV-450.
- [X] T063 [P] Write failing tests for dependency successor findings including "no successor known" (FR-020) — Done when: tests use synthetic `replaced_by` data and fail. Evidence: synthetic only. Result: tests/unit/dependencies/test_dependency_successor.py (TST-006-063).
- [X] T064 [P] Write failing tests for inherit-id and xpath-anchor rules with a synthetic view index including the "unverifiable" and "index unavailable" cases (FR-021) — Done when: they exist and fail. Evidence: synthetic only.

### Research (no owner decision needed; read-only fetch at pinned SHAs, new evidence records only after review)

- [X] T065 [P] Research: other model renames 15.0 to 19.0 by diffing `_name` across the pinned trees of odoo/odoo (addons/*/models) and listing candidates with successor names — Done when: a candidate table with raw-fetch evidence drafts per rename exists in a research note. Evidence required: `_name` present at old SHA and absent/present-new at new SHA, line match. Already verified: only payment.acquirer (EV-450).
- [X] T066 [P] Research: payment.acquirer rename follow-ons (field `acquirer_id` to `provider_id`, XML ids, ACL ids, tables) — Done when: each follow-on is evidenced or marked unmapped. Evidence required: pinned 15.0 vs 16.0 files under addons/payment and website_payment (payment_provider.py, security/ir.model.access.csv, views). Verified: model name only.
- [X] T067 [P] Research: false-positive/ambiguity analysis for AUTO_TRANSFORM on the renamed-model family (e.g. custom models named `*.acquirer`) — Done when: written decision, recommendation DETECT_ONLY unless a safe mapping is shown. Depends on T065, T066.
- [X] T068 [P] Research: successor of each module removed per step 14-15..18-19 (diff `core_modules` lists; start with payment_transfer, payment_test, sale_coupon) — Done when: each removed module has successor evidence (`__manifest__`, commit or release note at pinned SHA) or "none found". Evidence required: official file, SHA, line match. Verified: only the removed-module lists (EV-430..433, 372..375). Result: research-notes/removed-modules.md; EV-520 payment_transfer, EV-521 l10n_be_invoice_bba; payment_test, sale_coupon and the rest: none found.
- [X] T069 [P] Research: view external id and named-anchor extraction design from official XML at pinned SHAs (scope, size, inherited-view chains, ids defined in data vs views) — Done when: design note and coverage estimate exist. Evidence required: official `addons/*/views/*.xml` at each pinned SHA. Verified: only that one id vanished at 16.0 (EV-450).
- [X] T070 [P] Research: owner-policy input for version-prefix fix opt-out (REQ-MAN-002/F-MAN-1) — Done when: a one-page option note exists for the owner. Evidence: policy documents, not Odoo sources.

### Implementation (each gated on owner acceptance in AMENDMENT-REVIEW.md)

- [X] T071 Implement `bind_rule(run_params)` (FR-017) in `src/odooflux/rules/shared/loader.py` — Done when: T060 passes and the full suite plus matrix check are unchanged (SC-001, non-regression). Depends: T060, decision D-A1.
- [X] T072 Bind `*.manifest.version-prefix` per run as DETECT_ONLY/review_required (FR-019) — Done when: T061 passes and the planner supplies `target` (planner wiring belongs to P2; if absent, test through bind only). Depends: T071, T061, D-A2. FIX_ENABLED promotion is out of scope (needs D-A3 and T070).
- [X] T073 Add renamed-model detectors and rule metadata for payment (FR-018) — Done when: T062 passes, rules cite EV-450, maturity DETECT_ONLY, no fixer, coverage test passes. Depends: T062, D-A4. AUTO_TRANSFORM only via a new task after T066/T067 and D-A5.
- [X] T074 [P] Add further renamed-model rule instances found by T065 — Done when: each has evidence from T065 and tests. Depends: T065, T067, D-A4.
- [X] T075 Add `replaced_by` to the core-module list schema and data from T068 (schema change, evidence per entry), then the removed-with-successor rule (FR-020) — Done when: T063 passes and each non-empty `replaced_by` cites evidence. Depends: T063, T068, D-A6. Result: optional `replaced_by` (schema, checks, 2 entries with EV-520/521), rule `*.deps.removed-with-successor`.
- [X] T076 Implement `tools/extract_view_index.py` and index data (FR-021) — Done when: reproducible output at each pinned SHA, size within agreed budget. Depends: T069, D-A7.
- [X] T077 Implement the inherit-id and xpath-anchor DETECT_ONLY rules (FR-021) — Done when: T064 passes with the real index, golden check for `payment.payment_acquirer_form` at 16.0 (EV-450). Depends: T064, T076.
- [X] T078 Update matrix research/rule categories for the new rules and re-run `matrix --check` (T058-style), update coverage-gaps.md statuses — Done when: check passes. Depends: T073..T077 (those done).

Dependencies: T071 before T072. Tests T060..T064 before their implementation. T065/T066 before T067 before T074. T068 before T075. T069 before T076 before T077. T060..T070 are all parallel.

## Phase 11: Pipeline wiring (FC A-5, ADR-018; work state tracked per ADR-019)

- [X] T079 Write failing wiring tests first (`tests/integration/test_planner_wiring.py`) — Done when: recorded red (2 failures, 5 errors) before any wiring code. Depends: T060.
- [X] T080 Planner/orchestrator supplies run params: `run_pipeline` derives `target` (e.g. `"18.0"`) from the plan and binds opted-in rules through `bind_rule(run_params)` (`core/orchestrator/run_inputs.py`; opt-in `--enable-rule ID`, default off) — Done when: `*.manifest.version-prefix` finding reaches the JSON report via the CLI; DETECT_ONLY, no edit even with `--fix`. Depends: T079, FR-017, FR-019.
- [X] T081 Missing required run input yields an INFO gap issue in each module report, never silent and never an exception — Done when: patched empty run params produce one gap and no finding. Depends: T080.
- [X] T082 Dependency scanner runs in the pipeline (`dependencies/scan.py`: removed modules, `replaced_by` successors, unknown dependencies; scanned set = all modules of the run) and its findings, or an INFO gap when no core list exists, appear in every affected module report — Done when: `*.deps.removed-with-successor` (payment_transfer to payment_custom, EV-520) reaches the report via the CLI. Depends: T079, FR-020.
- [X] T083 Integration tests through the real CLI/pipeline for both wirings (not bind-only) — Done when: `tests/integration/test_planner_wiring.py` green. Depends: T080..T082.
- [ ] T084 REQ-MAN-002 opt-out: owner decision on wording and any FIX_ENABLED promotion. Certification: PENDING_HUMAN_REVIEW, register fragment `docs/reviews/fragments/ws-b-human-review.md` (item WSB-001). Version-prefix stays opt-in/DETECT_ONLY; REQ-MAN-002 wording unchanged.

## Phase 12: Knowledge rules in the migrate pipeline (WS-E, ADR-018/ADR-019; work state tracked per ADR-019)

- [X] T085 Write failing tests first (`tests/unit/test_knowledge_rule_selection.py`, `tests/integration/test_knowledge_rules_pipeline.py`) — Done when: recorded red (unit: ImportError; integration: 5 failures of 8) before any wiring code. Depends: T084.
- [X] T086 Step selection and binding: `core/orchestrator/knowledge_rules.py` selects KB rows whose step is in the plan (or `*`), DETECT_ONLY/FIX_ENABLED with a detector, not run-input rules (those stay opt-in), binds them once per run with `run_params` — Done when: unit tests for step to rule selection green. Depends: T085, FR-017.
- [X] T087 Detection through the real pipeline: `plan_module` runs the bound rules on module files of the rule kind (python, xml, csv, javascript, manifest); findings carry rule id, evidence IDs, `maturity`, `review_required` into the module report — Done when: CLI test on a copy of the 17.0 fixture reports the `17-18.*` findings (name_get, group_operator, user_has_groups, mail.shortcode, numbercall, kanban-box, tree-to-list) and 17 to 19 adds `18-19.*` (`_sql_constraints`). Depends: T086.
- [X] T088 FIX_ENABLED knowledge rules edit only through `apply_edits`, then the existing L1 validate and re-scan path, after the legacy fixer; DETECT_ONLY never edit (SC-005) — Done when: `--fix` leaves every DETECT_ONLY construct byte-identical, `group_operator` becomes `aggregator`, and no DETECT_ONLY finding is FIXED. Depends: T087.
- [X] T089 Overlap with the legacy tables: legacy rows keep running unchanged; a knowledge rule is not emitted on a file line a overlapping legacy category already reported (`rules/shared/legacy_overlap.py`, checked against `legacy_disposition.json`) — Done when: dedup unit and CLI tests green; no legacy golden result changed. Depends: T087.
- [X] T090 Performance: parse and AST walk reused across rules (`parsers/python/document.py`, `parsers/xml/document.py`, `parsers/python/spans.py`) — Done when: largest golden module analyses in under 10 s (SC-006) and the 300-module analysis benchmark is measured and recorded in the WS-E fragment. Depends: T087.
- [X] T091 Regenerate the PROVISIONAL expected output (`tools/update_expectations.py --force`) and update the PROVISIONAL section of `verification.md` — Done when: golden and provisional tests green; diff listed in `docs/reviews/fragments/ws-e-human-review.md`. Depends: T088.
- [ ] T092 Retire legacy rows marked `retire`/`correct` in `legacy_disposition.json`, and review the regenerated PROVISIONAL expected output. Certification: PENDING_HUMAN_REVIEW, register fragment `docs/reviews/fragments/ws-e-human-review.md` (items WSE-001, WSE-002). Nothing retired; expected output stays PROVISIONAL.

---

## Dependencies & Execution Order

- Setup (T001–T003) → Foundational (T004–T009) → Research (T010–T025, parallel) and, in parallel, rules with complete evidence:
  - **No research gate:** T028, T029, T031 (except `_context`), T032, T033, T034, T036, T038, T041, T042 (`t-esc`/`t-raw` part), T043 (except sudo maturity), T045, T047, T050–T052.
  - **Research-gated:** T027←T011, T030←T014, T031 (`_context`)←T012, T037←T010, T039←T015, T040←T013, T042 (extra)←T017, T043 (sudo)←T022, T049 (extra)←T020, T053←T019, T054←T016, T055←T023.
- Golden tasks T035/T044 come after their stories' rules. T046 before T047. T058/T059 last.
- Feature dependencies: 004 and 005 exited.

## Parallel Example

```text
Research agents: T010, T011, T012, T013, T014, T015, T016 in parallel (different official files).
Rule agents meanwhile: T028, T032, T036, T041 (independent files, evidence complete).
```

## Implementation Strategy

MVP = US1 (17.0 → 18.0/19.0), the highest-value and best-evidenced path. Then US2 (multi-step
14–16), US3 (install blockers), US4 (inventory), US5 (JS/assets).
