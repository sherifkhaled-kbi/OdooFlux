# Implementation Plan: Core Architecture (P2)

**Branch**: `003-core-architecture` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-core-architecture/spec.md`

## Summary

Create the `src/odooflux` package with:
- the contracts from [CONTRACTS.md](../../docs/planning/architecture/CONTRACTS.md);
- generic registries with contract-version checks;
- the version registry and graph (data-driven);
- a planner with dependency ordering and blocked-step handling;
- an engine that applies Edits with conflict detection and re-scan attribution;
- a workspace with promotion, run log, rollback, checkpoint, and resume;
- L1/L2 validators;
- report model v1 plus the status decision function;
- discovery;
- a legacy rule adapter for parity;
- the CLI with subcommands;
- the cut-over launcher, `pyproject.toml` (D-09), an import-graph test, and a baseline benchmark.

## Technical Context

**Language/Version**: Python ≥3.10

**Primary Dependencies**: stdlib only in the core. Optional extras are declared, not used (D-09).

**Storage**: Files. Knowledge JSON in the package; state dir (`~/.cache/odooflux`).

**Testing**: `unittest`. Characterisation (P1), contract tests, failure injection.

**Target Platform**: Linux, macOS, Windows

**Project Type**: CLI and library (single project, `src/` layout)

**Performance Goals**: No more than 20 % slower than the legacy CLI on the P1 fixtures. Baseline
recorded for 300 modules (budget set in P9).

**Constraints**:
- no customer code execution (REQ-SEC-001);
- deterministic output (REQ-ARC-005);
- no version literals in the engine (REQ-ARC-003);
- legacy CLI parity (REQ-ARC-004).

**Scale/Scope**: About 12 sub-packages, 7 registries, about 40 tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Justification |
|---|---|---|
| I Dependency-light core | PASS | Import-graph test (FR-001); extras only declared |
| II Safe, reversible | PASS | Workspace, verified backup, atomic promotion, rollback, resume |
| III Deterministic first | PASS | The legacy AI path is wrapped unchanged; the provider abstraction is P6 |
| IV Honest reporting | PASS | Re-scan attribution in the engine; status decision function |
| V Test-backed | PASS | Contract, unit, integration, and failure-injection tests per FR |
| VI Official evidence | PASS with justified exception | `legacy-*` rules have no full evidence until P5; each run lists the waiver in the report (see Complexity Tracking) |
| VII Layered validation | PASS | L1/L2 implemented; L3–L5 reported `UNAVAILABLE`, which caps status |
| VIII Business logic | PASS | No new transformations |
| IX Modular | PASS | Registries, no version literals |
| X Phase delivery | PASS | Entry requires D-01/D-09; cut-over gated by characterisation |

Post-design re-check: PASS (with the one exception justified below).

## Project Structure

### Documentation (this feature)

```text
specs/003-core-architecture/
├── plan.md  research.md  data-model.md  quickstart.md  tasks.md
├── contracts/ (README, cli, registries-and-plugins, recovery, result-model-v1)
└── checklists/requirements.md
```

### Source Code (repository root)

```text
pyproject.toml                         # NEW (D-09): package, console script, optional extras
odooflux.py                            # becomes launcher at cut-over (T057)
src/odooflux/
├── __init__.py                        # __version__
├── __main__.py                        # python -m odooflux
├── builtins.py                        # registers built-ins
├── cli/            __init__.py, main.py, commands/{migrate,plan,rollback,resume,versions}.py, legacy_options.py
├── core/
│   ├── contracts/  __init__.py (CONTRACT_VERSION), versions.py, rules.py, documents.py, findings.py, edits.py, validation.py, runtime.py, ai.py, report.py, plugins.py
│   ├── engine/     apply.py (edit application, conflicts), rescan.py, step_runner.py
│   ├── orchestrator/ run.py, status.py (decision function)
│   ├── jobs/       state_dir.py, workspace.py, promote.py
│   └── recovery/   runlog.py, checkpoint.py, rollback.py, resume.py
├── discovery/      modules.py, manifest.py, ignore.py
├── versions/registry/ loader.py     versions/graph/ graph.py
├── dependencies/   graph.py (topological order, cycles)
├── rules/shared/   registry_loader.py, legacy_adapter.py, legacy_rules.py (moved tables)
├── parsers/python/ document.py      parsers/xml/ wellformed.py
├── validation/syntax/ python.py, xml.py, manifest.py   validation/static/ rescan.py
├── reporting/model/ model.py, report.schema.json, schema_check.py, json_renderer.py, legacy_terminal.py, legacy_json.py
├── ai/providers/   legacy_anthropic.py (wrapped legacy call, unchanged behaviour)
├── knowledge/      versions.json
└── utils/          hashing.py, atomic.py, paths.py, redact.py
tests/
├── unit/ …  contract/ (samples/ + tests)  integration/ …  benchmarks/ generate_repo.py, bench_analyze.py, BASELINE.md
docs/changes/P2_CUTOVER.md
```

**Structure Decision**: Follows [PROJECT_STRUCTURE.md](../../docs/planning/PROJECT_STRUCTURE.md).
Only the directories above get code in P2; the other scaffold directories keep `.gitkeep`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Principle VI: `legacy-*` rules without complete evidence | Cut-over parity (REQ-ARC-004) before P5 replaces the rules | Dropping legacy rules at cut-over would silently remove detections users rely on |
| Legacy report shape kept alongside v1 | Characterisation parity and existing CI consumers | Breaking JSON consumers without a D-10 decision violates Principle X |
