# Implementation Plan: Test Foundation (P1)

**Branch**: `002-test-foundation` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-test-foundation/spec.md`

## Summary

Build the offline `unittest` foundation:
- shared harness;
- seven golden fixtures (12.0–18.0) with expected legacy outputs;
- a black-box characterisation suite against `odooflux.py`;
- an expectation-update script;
- a regression index;
- a rule-test coverage report;
- opt-in gates for runtime, network, and AI suites.

## Technical Context

**Language/Version**: Python ≥3.10

**Primary Dependencies**: stdlib only (`unittest`, `subprocess`, `tempfile`, `hashlib`, `json`)

**Storage**: Fixture files in the repository

**Testing**: `python -m unittest discover -s tests`

**Target Platform**: Linux, macOS, Windows; CI

**Project Type**: CLI test infrastructure

**Performance Goals**: Default suite under 120 s on a developer laptop (SC-001)

**Constraints**: No network, no Docker, no Odoo installation needed for default suites; fixtures
are synthetic

**Scale/Scope**: 7 fixtures, about 40 characterisation cases, harness, P0 regression migration

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Justification |
|---|---|---|
| I | PASS | stdlib `unittest` |
| II | PASS | Tests run on temp copies; `input/` is never modified (asserted) |
| III | PASS | AI suites are opt-in only |
| IV | PASS | Characterisation pins report content |
| V | PASS | This feature implements V |
| VI | PASS | Fixture constructs cite EV records (research R-03) |
| VII | N/A | No validation layers built here |
| VIII | PASS | No behaviour change to the tool |
| IX | PASS | Black-box tests survive restructuring |
| X | PASS | Exit criteria from the roadmap |

Post-design re-check: PASS.

## Project Structure

### Documentation (this feature)

```text
specs/002-test-foundation/
├── plan.md  research.md  data-model.md  quickstart.md  tasks.md
└── checklists/requirements.md
```

### Source Code (repository root)

```text
tests/
├── README.md                     # conventions
├── __init__.py
├── _support/                     # harness (package)
│   ├── __init__.py
│   ├── fixtures.py               # copy_fixture, load_index
│   ├── digest.py                 # tree_digest
│   ├── cli.py                    # run_legacy_cli
│   ├── normalize.py              # report normalisation
│   └── optin.py                  # requires_runtime / requires_network / requires_ai
├── unit/            test_harness_*.py
├── integration/     test_characterisation.py, test_fixture_validity.py
├── regression/      INDEX.md, test_p0_*.py (migrated), test_regression_index.py
├── contract/        __init__.py (empty until P2)
├── runtime/         __init__.py, test_runtime_placeholder_gate.py
├── benchmarks/      __init__.py
└── golden_fixtures/ INDEX.json, v12_*/ … v18_*/
tools/
└── update_expectations.py        # regenerates expected outputs
```

**Structure Decision**: The harness lives in `tests/_support/` (test-only code, not product code).
The expectation updater lives in `tools/` because it is a developer utility.

## Complexity Tracking

None.
