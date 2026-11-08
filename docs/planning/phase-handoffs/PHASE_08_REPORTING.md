# Phase Handoff P8 — Reporting and UX

## 1. Phase ID
P8 — Spec Kit feature [`specs/009-reporting-ux`](../../../specs/009-reporting-ux/)

## 2. Phase title
Reporting and UX

## 3. Objective
Render the versioned report model into terminal, offline HTML, JSON (schema v1 plus a legacy format), SARIF 2.1.0, and unified diff, with a documented exit-code policy and `--fail-on`.

## 4. Requirements covered
REQ-REP-001…006, REQ-BIZ-003 (presentation part), REQ-SEC-003 (report paths), REQ-SEC-004 (escaping).

## 5. Repository context
Legacy reporting (`print_report`, `save_json_report`, `print_combined_summary`, exit codes in `main`) has defects F-REP-1, F-REP-2, F-REP-3, and F-VER-4. Design and mockups: [REPORTING_AND_UX.md](../REPORTING_AND_UX.md).

## 6. Prerequisites
P2 exit (report model). P7 status model and verification scope merged. D-06, D-07, and D-10 decided (defaults: static stdlib HTML, optional `rich`, one-release legacy compatibility).

## 7. Dependencies
P2 `reporting/model`, P7 `validation/status.py`, P6 `ai_usage` section (optional; renders "AI disabled" when absent).

## 8. Expected files and components
`src/odooflux/reporting/model/report.schema.json`, `reporting/terminal/{ansi,progress,rich_adapter}.py`, `reporting/html/html.py` + templates, `reporting/exporters/{json_v1,legacy_json,sarif,diff}.py`, `cli/exit_codes.py`, tests in `tests/{unit/reporting,unit/cli,integration/reporting,regression}/`, golden models in `tests/golden_fixtures/reports/`.

## 9. Interfaces and contracts
[contracts/report-schema-v1.md](../../../specs/009-reporting-ux/contracts/report-schema-v1.md), [contracts/sarif-and-diff.md](../../../specs/009-reporting-ux/contracts/sarif-and-diff.md), the `Renderer` contract in [CONTRACTS.md](../architecture/CONTRACTS.md#renderer), and the exit-code table in [data-model.md](../../../specs/009-reporting-ux/data-model.md).

## 10. Official evidence requirements
No new Odoo claims. Evidence links rendered in reports must come from knowledge-base records and allow-listed domains (REQ-EVD-004). SARIF and JSON Schema meta-schemas are vendored with provenance (T002).

## 11. Detailed implementation tasks
See [specs/009-reporting-ux/tasks.md](../../../specs/009-reporting-ux/tasks.md) (T001–T026).

## 12. Acceptance criteria
Spec SC-001…SC-005. Roadmap exit:
1. All renderers consume the model.
2. Terminal snapshots (colour and plain) pass.
3. The HTML report works offline.
4. SARIF validates.
5. The diff applies.
6. The `--fail-on` table is tested.
7. Mockup parity is reviewed.

## 13. Unit tests
TST-009-001…008, -010, -011.

## 14. Integration tests
TST-009-009 (diff applies), -012 (output paths).

## 15. Runtime tests where applicable
Not applicable.

## 16. Negative test cases
ANSI/control-character injection in excerpts, HTML/XSS payloads, report path inside a scanned module, narrow terminal widths, huge finding counts, missing optional sections, `rich` not installed, invalid `--fail-on` value (exit 2).

## 17. Security requirements
Escape all untrusted text. The HTML report contains no scripts and no network resources. Reports are never written inside scanned paths. Reports contain no secrets (verified again in P9).

## 18. Performance requirements
Rendering must not be the bottleneck for a 300-module report (measured in P9). The terminal caps the per-file listing, while totals stay exact.

## 19. Backward compatibility
`--report-format legacy-json` and the legacy exit-code mapping are kept for one minor release with a deprecation notice (D-10). The new default exit codes are documented in the README and changelog.

## 20. Prohibited changes
Renderers must not compute or alter results. The report model must not change without a `schema_version` rule. Severity and status semantics must not change.

## 21. Definition of Done
All tasks done. All TST-009-* pass. Schemas are published. Mockup parity is recorded. The quickstart is recorded. The RTM is updated.

## 22. Implementation agent instructions
1. Set `.specify/feature.json` to `{"feature_directory": "specs/009-reporting-ux"}`.
2. Read the feature docs, then [REPORTING_AND_UX.md](../REPORTING_AND_UX.md) mockups.
3. Use `/speckit-implement` (not run during planning).
4. Stop and ask if a model field is missing. The model is owned by P2, and P6/P7 extend it.

## 23. Expected verification evidence
Test logs, sample outputs for every format from golden models (attached to the verification log), the schema validation report, the `patch -p1` transcript, and the mockup parity review.

## 24. Handoff checklist
- [ ] P2 and P7 prerequisites verified; D-06, D-07, D-10 decided
- [ ] feature.json points at 009
- [ ] Tests first
- [ ] All formats generated from the same golden model and counts equal
- [ ] Exit-code table documented in README
- [ ] RTM and SPECKIT_READINESS updated
