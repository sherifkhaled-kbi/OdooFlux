# Implementation Plan: Reporting and UX

**Branch**: `009-reporting-ux` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/009-reporting-ux/spec.md`

## Summary

Render the versioned report model into terminal (ANSI, optional `rich`), offline HTML, JSON (schema v1 plus legacy format for one release), SARIF 2.1.0, and unified diff. Implement the exit-code table and `--fail-on`. Mockups: [REPORTING_AND_UX.md](../../docs/planning/REPORTING_AND_UX.md).

## Technical Context

**Language/Version**: Python ≥3.10
**Primary Dependencies**: stdlib (`string`, `html`, `json`, `difflib`); optional `rich` (D-07)
**Storage**: report files at user-specified paths outside scanned modules
**Testing**: `unittest` snapshot tests; JSON Schema and SARIF schema validation in tests (schemas vendored as test data)
**Target Platform**: any terminal; HTML in any modern browser offline
**Project Type**: CLI / library
**Performance Goals**: rendering a 300-module report completes well within the job budget (measured in P9)
**Constraints**: renderers are pure functions of the model; all untrusted text escaped
**Scale/Scope**: reports with up to tens of thousands of findings (terminal caps per file)

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I | PASS | stdlib default; `rich` optional adapter |
| II | PASS | Reports refused inside scanned paths |
| III | N/A | Displays AI usage only |
| IV | PASS | This feature implements honest presentation; counts come from the model |
| V | PASS | Snapshot, schema, cross-renderer consistency, and exit-code tests |
| VI | PASS | Evidence URLs from the knowledge base only |
| VII | PASS | Per-layer results and verification scope shown |
| VIII | PASS | Limits section mandatory |
| IX | PASS | Renderer registry |
| X | PASS | Entry requires P2 schema and P7 status model |

## Project Structure

```text
specs/009-reporting-ux/   plan.md, spec.md, research.md, data-model.md, quickstart.md, tasks.md, checklists/, contracts/
src/odooflux/reporting/
├── model/          report.schema.json, schema validation helper (P2 owns the model; P8 publishes the schema)
├── terminal/       ansi.py, rich_adapter.py (optional), progress.py
├── html/           html.py, templates/report.html.tmpl, templates/style.css (inlined at render)
└── exporters/      json_v1.py, legacy_json.py, sarif.py, diff.py
src/odooflux/cli/exit_codes.py
tests/unit/reporting/, tests/integration/reporting/, tests/golden_fixtures/reports/
```

**Structure Decision**: the PROJECT_STRUCTURE.md `reporting/*` rows; the exit policy lives in `cli/`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Optional `rich` adapter | Better tables/progress for interactive users | Mandatory dependency violates Principle I |
