# Implementation Plan: Version Compatibility Rules

**Branch**: `006-version-compatibility-rules` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-version-compatibility-rules/spec.md`

## Summary

Turn the seeded evidence into tested rules. First, close the research gaps that block rules.
Then implement parameterised generic detectors/fixers per language and bind rules to them as
metadata, with per-rule fixtures. Then add manifest, dependency, reference, and security checks
and the business-logic risk inventory, and finally golden multi-step migrations. Legacy rules are
dispositioned per MIGRATION_RULE_ENGINE.md.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: stdlib; feature 005 parsers/transformers; optional JS adapter for JS fixers
**Storage**: Knowledge JSON (`knowledge/compatibility/*.rules.json`, `core_modules/*.json`, `legacy_disposition.json`, new evidence records)
**Testing**: `unittest`; per-rule fixtures; golden migrations; rule-coverage test
**Target Platform**: Linux/macOS/Windows
**Project Type**: CLI tool rules layer
**Performance Goals**: SC-006 (≥50-file module analysed < 10 s)
**Constraints**: No rule without evidence; `review_required` ⇒ no fixer; deterministic ordering
**Scale/Scope**: ~45 initial rules (catalogue Groups A–D), 7 steps, ≥5 source-version golden modules

## Constitution Check (v2.0.0)

| Principle | Check | Status |
|---|---|---|
| I Dependency-light core | Rules use stdlib parsers; JS fixers only with the adapter | PASS |
| II Safe, reversible | Fixes flow through the edit engine and validation; review rules never edit | PASS |
| III Deterministic first | All rules deterministic; AI is feature 007 | PASS |
| IV Honest reporting | Matrix generated; RULES_TESTED only with tests | PASS |
| V Test-backed | Coverage test enforces positive/negative/idempotence | PASS |
| VI Official evidence only | Research tasks precede gated rules; legacy rules without evidence retired or researched | PASS |
| VII Layered validation | Each rule declares validators; runtime confirmation deferred to P7 | PASS |
| VIII Business logic | Review-only class + risk inventory | PASS |
| IX Modular | Rules are data bindings to generic code; new version procedure proven (FR-016) | PASS |
| X Phase delivery | Entry needs P3 and P4 exit | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/006-version-compatibility-rules/
├── spec.md  plan.md  research.md  data-model.md  quickstart.md  tasks.md
├── contracts/rule-catalogue.md
└── checklists/requirements.md
```

### Source Code (repository root)

```text
src/odooflux/rules/python/{generic.py, exceptions.py, sql_constraints.py, routes.py}
src/odooflux/rules/xml/{generic.py, view_mode.py, data_tags.py}
src/odooflux/rules/qweb/generic.py
src/odooflux/rules/javascript/generic.py
src/odooflux/rules/owl/                      # populated only after G-R-03 research
src/odooflux/rules/assets/generic.py
src/odooflux/rules/manifest/{hygiene.py, files.py}
src/odooflux/rules/security/{acl_csv.py, record_rules.py}
src/odooflux/dependencies/{core_modules.py, references.py}
src/odooflux/analyzers/risk_inventory.py
src/odooflux/knowledge/compatibility/{12-13…18-19}.rules.json
src/odooflux/knowledge/compatibility/core_modules/{12.0…19.0}.json
src/odooflux/knowledge/compatibility/legacy_disposition.json
src/odooflux/knowledge/evidence/EV-3NN.json  # new evidence from research tasks
tools/extract_core_modules.py                # maintainer script (reads official clone at SHA)
tests/unit/rules/<language>/test_*.py
tests/golden_fixtures/rules/<rule-id>/{positive,negative}/
tests/golden_fixtures/<source>/<module>/expected/<target>/
tests/integration/test_golden_migrations.py
tests/unit/rules/test_rule_coverage.py
```

**Structure Decision**: Per [PROJECT_STRUCTURE.md](../../docs/planning/PROJECT_STRUCTURE.md).
`tools/` is a new top-level maintainer-scripts directory (not shipped in the package). Its
addition must be recorded in PROJECT_STRUCTURE.md by the implementer.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| New top-level `tools/` directory | Core-module extraction reads official clones and must not ship in the package | Putting it in `src/odooflux` would ship maintainer-only code that needs network/git |

## Amendment 2026-11-07: coverage-gap plan (DRAFT, pending acceptance)

Dependency order: (1) FR-017 binding extension (contract in contracts/rule-catalogue.md) is the only shared code change; it unblocks the manifest version-prefix rule and is independent of the others. (2) Renamed-model family needs no new binding work, only metadata params; first instance rests on EV-450 (already verified), further instances need new evidence. (3) Dependency successors: research per removed module, then `replaced_by` in `core_modules/<ver>.json` (schema change, `tools/extract_core_modules.py` untouched until research lands), then rule. (4) XPath: view-index extractor in `tools/` (maintainer script, like core modules), index data under `knowledge/compatibility/view_index/<ver>.json`, then two DETECT_ONLY rules. Gaps 2 to 4 research tasks run in parallel; tests are written before each implementation (TDD).

New files (planned, not created): `src/odooflux/rules/shared/` run-param support in loader.py; `src/odooflux/rules/python|xml|csv` renamed-model detectors; `tools/extract_view_index.py`; `knowledge/compatibility/view_index/`; tests under `tests/unit/rules/` and `tests/golden_fixtures/rules/<rule-id>/`. Constitution check unchanged: no network at runtime, evidence-first, review_required means no edits.
