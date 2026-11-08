---
description: "Task list for P8 — Reporting and UX"
---

# Tasks: Reporting and UX

**Input**: Design documents from `/specs/009-reporting-ux/`
**Prerequisites**: P2 (report model) and P7 (status model, verification scope) complete
**Tests**: Required (Principle V). Write tests first; they must fail before implementation.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…) — Done when: …`

## Phase 1: Setup

- [X] T001 Create golden report models (JSON) covering every status, fixed/open/rejected findings, AI usage on/off, runtime on/off in `tests/golden_fixtures/reports/` (REQ-REP-001, REQ-REP-006) — Done when: ≥1 model per status value and each optional section present and absent at least once.
  - Note: Goldens are generated from synthetic scenario states (`tests/unit/reporting/fixtures.py`, `tests/golden_fixtures/reports/build_goldens.py`); synthetic mechanics fixtures, no migration truth. Model gained additive fields (summary, ai_usage, warnings, optional provisional, per-module path/blocked/reversible, finding auto_fixable/rejection_reason, scope layer_outcomes, run.tool_version); `schema_version` stays 1.0.0.
- [X] T002 [P] Vendor SARIF 2.1.0 and JSON Schema meta-schema as test data in `tests/golden_fixtures/schemas/` with source URLs and retrieval date (REQ-REP-004) — Done when: files exist with provenance header.
  - Note: Vendored 2026-11-07 from the OASIS errata01 URL and json-schema.org (2020-12 meta-schema plus its seven vocabulary files); provenance, URLs, sha256 and retrieval date in `tests/golden_fixtures/schemas/PROVENANCE.json` (JSON cannot carry a comment header). Validated with the in-repo stdlib validator `tests/unit/reporting/schema_validator.py`.

## Phase 2: Foundational

- [X] T003 [P] Unit test: JSON v1 export validates against `report.schema.json` for every golden model in `tests/unit/reporting/test_json_schema.py` (REQ-REP-001; TST-009-001) — Done when: fails before T005, passes after.
- [X] T004 [P] Unit test: cross-renderer count consistency (terminal, HTML, JSON, SARIF) in `tests/unit/reporting/test_cross_renderer_counts.py` (REQ-REP-001, REQ-REP-006; TST-009-002) — Done when: counts extracted from every renderer equal the model's summary.
- [X] T005 Publish `src/odooflux/reporting/model/report.schema.json` and `src/odooflux/reporting/exporters/json_v1.py` (REQ-REP-001) — Done when: TST-009-001 passes.
- [X] T006 Implement renderer registry with contract version in `src/odooflux/reporting/__init__.py` registry module (REQ-REP-001, REQ-ARC-006) — Done when: a sample renderer registers without core edits; mismatched version is rejected.

## Phase 3: User Story 1 — Terminal (P1) 🎯 MVP

- [X] T007 [P] [US1] Snapshot tests colour/plain at widths 60/80/120 in `tests/unit/reporting/test_terminal_snapshots.py` (REQ-REP-002; TST-009-003) — Done when: snapshots exist for every golden model; no ANSI in plain mode.
- [X] T008 [P] [US1] Unit test: verification-scope and recovery blocks always rendered in `tests/unit/reporting/test_terminal_sections.py` (REQ-REP-006, REQ-BIZ-003; TST-009-004) — Done when: `STATIC_VALIDATED` model output states install and behaviour unverified; rollback command shown in write mode.
- [X] T009 [P] [US1] Unit test: escaping of untrusted excerpts (ANSI injection, control chars) in `tests/unit/reporting/test_terminal_escaping.py` (REQ-REP-002, REQ-SEC-004; TST-009-005) — Done when: control characters from fixtures are neutralised.
- [X] T010 [US1] Implement `src/odooflux/reporting/terminal/ansi.py` and `progress.py` (REQ-REP-002, REQ-REP-006) — Done when: TST-009-003/004/005 pass.
- [X] T011 [US1] Implement optional `src/odooflux/reporting/terminal/rich_adapter.py` selected only when `rich` is importable and `--ui rich` (REQ-REP-002) — Done when: absence of `rich` falls back to ANSI without error (test in TST-009-003 variant).
  - Note: Verified against a real `rich` installed to a throwaway directory outside the repo (5/5 tests); in the default environment `rich` is absent and the rich test is skipped while the fallback test runs.

## Phase 4: User Story 2 — CI exports and exit codes (P1)

- [X] T012 [P] [US2] Unit test: SARIF output validates against SARIF 2.1.0 and maps per contract in `tests/unit/reporting/test_sarif.py` (REQ-REP-004; TST-009-006) — Done when: all golden models validate; level mapping and fingerprints asserted.
- [X] T013 [P] [US2] Unit test: exit-code table and `--fail-on` matrix in `tests/unit/cli/test_exit_codes.py` (REQ-REP-005; TST-009-007) — Done when: every row and precedence combination asserted.
- [X] T014 [P] [US2] Unit test: legacy JSON format parity with the P1 characterisation outputs in `tests/unit/reporting/test_legacy_json.py` (REQ-REP-001, REQ-ARC-004; TST-009-008) — Done when: legacy-json output matches characterised fields for golden fixtures and prints a deprecation notice.
  - Note: Parity is asserted against the existing P1 legacy writer (`reporting/model/legacy_json.py`) on every scenario, excluding timestamp and elapsed seconds (the deterministic model carries neither); no separate stored characterisation files were used.
- [X] T015 [US2] Implement `src/odooflux/reporting/exporters/sarif.py` (REQ-REP-004) — Done when: TST-009-006 passes.
- [X] T016 [US2] Implement `src/odooflux/cli/exit_codes.py` and `--fail-on`/`--fail-on-status` options (REQ-REP-005) — Done when: TST-009-007 passes.
  - Note: `--fail-on-status`, `--exit-codes {legacy,v1}` added. DEFAULT is still the characterised legacy mapping (D-10, one minor release) because the v1 table reports a manifest-less module as BLOCKED=4 and two existing tests (`tests.regression.test_p0_reporting.ExitCodeTests.test_fail_on_thresholds`, `tests.contract.test_plugin_kinds.PluginKindsTests.test_validator_effect_rejects_the_edit`) encode the legacy result. `--fail-on-status` implies v1. Flipping the default is an owner decision (see ws-d-human-review.md FHR item on exit-code default).
- [X] T017 [US2] Implement `src/odooflux/reporting/exporters/legacy_json.py` (REQ-REP-001) — Done when: TST-009-008 passes.

## Phase 5: User Story 3 — Unified diff (P2)

- [X] T018 [P] [US3] Integration test: exported diff applies with `patch -p1` and reproduces promoted output byte-for-byte in `tests/integration/reporting/test_diff_apply.py` (REQ-REP-004; TST-009-009) — Done when: passes for every golden fixture incl. CRLF and no-final-newline files.
- [X] T019 [US3] Implement `src/odooflux/reporting/exporters/diff.py` with hunk index (REQ-REP-004) — Done when: TST-009-009 passes.
  - Note: Originals are read from the pre-run backup (write mode) or the untouched module (no write). Follow-up (WSD-05): a dry run now computes the same edits in memory, so `--fix --dry-run --diff` exports what write mode would promote (`tests/integration/reporting/test_dry_run_diff.py`); only `analyze` yields an empty patch, with a CLI note.

## Phase 6: User Story 4 — Offline HTML (P2)

- [X] T020 [P] [US4] Unit test: HTML has every schema section and zero external resource references in `tests/unit/reporting/test_html.py` (REQ-REP-003, REQ-REP-006; TST-009-010) — Done when: scripted scan finds no `src=`/`href=`/`url(` to non-evidence URLs and no `<script>`.
- [X] T021 [P] [US4] Unit test: HTML escaping of untrusted text (XSS payload fixtures) in `tests/unit/reporting/test_html_escaping.py` (REQ-REP-003, REQ-SEC-004; TST-009-011) — Done when: payloads render inert.
- [X] T022 [US4] Implement `src/odooflux/reporting/html/html.py` with templates in `src/odooflux/reporting/html/templates/` (REQ-REP-003) — Done when: TST-009-010/011 pass.
  - Note: Template and CSS are embedded in `html/html.py` (not data files under `templates/`) so the wheel needs no package-data entry.

## Phase 7: Polish & Cross-Cutting

- [X] T023 [P] Integration test: report output paths inside scanned modules are refused in `tests/integration/reporting/test_output_paths.py` (REQ-SEC-003; TST-009-012) — Done when: exit code 2 with a clear message.
- [X] T024 [P] Regression tests citing F-REP-1, F-REP-2, F-REP-3, F-VER-4 in `tests/regression/test_reporting_findings.py` (REQ-TST-005, REQ-REP-005; TST-009-013) — Done when: one test per finding ID passes.
- [ ] T025 Mockup parity review against [REPORTING_AND_UX.md](../../docs/planning/REPORTING_AND_UX.md) recorded in the phase verification log (REQ-REP-002, REQ-REP-006) — Done when: each mockup section is matched or a documented deviation is approved.
  - Technical part: automated checklist of required mockup sections is IMPLEMENTED and VERIFIED in `tests/unit/reporting/test_mockup_checklist.py` (known deviations listed there).
  - Certification: PENDING_HUMAN_REVIEW (register fragment `docs/reviews/fragments/ws-d-human-review.md`, item WSD-01). Not approved; no agent records parity.
- [X] T026 Run [quickstart.md](quickstart.md) and record results (REQ-REP-001) — Done when: all five scenarios recorded.
  - Note: Results in quickstart.md. Scenario 2/3 re-run after the WSD-05 follow-up: the dry-run diff is non-empty, byte-identical to the write-mode patch, and applies with `patch -p1` to IDENTICAL output.

## Dependencies & Execution Order

- Setup → Foundational (T003–T006) → US1 and US2 in parallel → US3, US4 → Polish.
- US2 T014 depends on the P1 characterisation outputs.

### Parallel Example: User Story 2

```bash
Task: "T012 SARIF test in tests/unit/reporting/test_sarif.py"
Task: "T013 exit code test in tests/unit/cli/test_exit_codes.py"
Task: "T014 legacy JSON test in tests/unit/reporting/test_legacy_json.py"
```

## Implementation Strategy

MVP: JSON v1 plus the terminal. Then the CI exports and exit codes, then the diff and the HTML.
