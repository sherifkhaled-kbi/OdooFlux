# Implementation Plan: Hardening and Release Readiness

**Branch**: `010-hardening-release` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/010-hardening-release/spec.md`

## Summary

Measure and enforce performance budgets (serial, parallel, incremental), add a hash-chained audit log, finish credential hardening, complete the failure-injection suite, and gate the release with an RTM completeness check and a generated support statement.

## Technical Context

**Language/Version**: Python ≥3.10
**Primary Dependencies**: stdlib (`concurrent.futures`, `tracemalloc`/`resource`, `hashlib`)
**Storage**: incremental index and audit log under the state directory
**Testing**: `unittest`; benchmarks opt-in (`ODOOFLUX_BENCHMARKS=1`)
**Target Platform**: Linux reference machine for budgets; functional tests on all platforms
**Project Type**: CLI / library
**Performance Goals**: budgets recorded from the P2 baseline (contracts/benchmark-protocol.md)
**Constraints**: no new features; determinism across `--jobs`
**Scale/Scope**: 300 modules × 30 files synthetic corpus

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I | PASS | stdlib only |
| II | PASS | Failure-injection suite proves recoverability |
| III | PASS | Credential CLI argument removal; secret scan |
| IV | PASS | Support statement derived from data |
| V | PASS | RTM gate, regression citation gate |
| VI | PASS | Support claims require evidence and runtime validation |
| VII | PASS | Release blocked unless status claims are backed |
| VIII | PASS | Support statement lists verification limits |
| IX | PASS | No core changes needed for new versions (verified by the P2 synthetic-version test, re-run here) |
| X | PASS | Entry requires P5–P8 exit |

## Project Structure

```text
specs/010-hardening-release/   plan.md, spec.md, research.md, data-model.md, quickstart.md, tasks.md, checklists/, contracts/
src/odooflux/core/orchestrator/parallel.py, incremental.py
src/odooflux/core/recovery/audit_log.py
src/odooflux/utils/redaction.py (extended)
tests/benchmarks/ (corpus_gen.py, run_benchmarks.py, budgets.json, REFERENCE_MACHINE.md)
tests/integration/hardening/, tests/regression/, tests/unit/release/test_rtm_completeness.py
docs/planning/RELEASE_CHECKLIST.md, docs/planning/SUPPORT_STATEMENT.md (generated)
```

**Structure Decision**: uses existing `core/orchestrator`, `core/recovery`, and `utils` (PROJECT_STRUCTURE.md). No new top-level directories.

## Complexity Tracking

None.
