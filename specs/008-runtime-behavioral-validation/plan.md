# Implementation Plan: Runtime and Behavioral Validation

**Branch**: `008-runtime-behavioral-validation` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/008-runtime-behavioral-validation/spec.md`

## Summary

Implement the status decision table, L3 dependency integrity, optional RNG validation, a container runtime adapter (install, upgrade, and tests with limits, read-only mounts, no network), log classification, and source/target test comparison. Close research gaps G-R-13 to G-R-23 first.

## Technical Context

**Language/Version**: Python ≥3.10
**Primary Dependencies**: stdlib (`subprocess`, `json`, `shutil`); optional: Docker CLI on host (D-03), `lxml` for RNG (D-02)
**Storage**: logs and runtime artefacts under `<state-dir>/runs/<run-id>/runtime/`
**Testing**: `unittest`; runtime suite opt-in `ODOOFLUX_RUNTIME_TESTS=1`
**Target Platform**: Linux (runtime layer); macOS/Windows with Docker Desktop are best-effort
**Project Type**: CLI / library
**Performance Goals**: one environment per target version per job; modules installed in dependency order in a single database
**Constraints**: default limits configurable (no assumed values; baseline measured on fixtures and documented in quickstart)
**Scale/Scope**: up to 300 modules per job (batched installs)

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I | PASS | Docker CLI and lxml are optional adapters; absence → UNAVAILABLE |
| II | PASS | Read-only mount of the workspace copy; no writes to customer paths |
| III | N/A | No AI |
| IV | PASS | Status reasons and verification scope in every report |
| V | PASS | Decision table sweep, runtime fixtures, regression tests |
| VI | PASS | CLI options and RNG files cited (EV-302, EV-303); gaps listed |
| VII | PASS | This feature implements it |
| VIII | PASS | L5 coverage attribute; limits stated |
| IX | PASS | `RuntimeEnvironment` and `Validator` registries |
| X | PASS | Entry requires P2 and D-03 |

## Project Structure

```text
specs/008-runtime-behavioral-validation/
├── plan.md, spec.md, research.md, data-model.md, quickstart.md, tasks.md
├── checklists/requirements.md
└── contracts/status-decision.md, contracts/runtime-environment.md

src/odooflux/validation/
├── status.py                    status decision (contract status-decision.md)
├── dependency/integrity.py      L3
├── static/rng.py                optional lxml adapter
├── runtime/docker_env.py        RuntimeEnvironment backend
├── runtime/log_classifier.py    patterns from knowledge data
└── behavioral/compare.py        TestComparison
src/odooflux/knowledge/compatibility/runtime_log_patterns.json   (data; research G-R-22)
tests/unit/validation/, tests/runtime/, tests/golden_fixtures/runtime/
```

**Structure Decision**: matches the PROJECT_STRUCTURE.md `validation/*` rows. `status.py` sits at `validation/` level because it consumes all layers.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| External Docker runtime | Isolation of untrusted code (REQ-SEC-001) | Local execution offers no isolation |
| Optional `lxml` | RELAX NG validation unavailable in stdlib | Custom RNG subset validator would be incomplete and error-prone |
