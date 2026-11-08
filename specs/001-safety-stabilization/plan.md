# Implementation Plan: Safety Stabilization (P0)

**Branch**: `001-safety-stabilization` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-safety-stabilization/spec.md`

## Summary

Patch the legacy `odooflux.py` so it cannot damage modules:
- a validation gate before every write;
- no writes in analyze or dry-run mode;
- backups in a tool-owned state directory, verified, and blocking on failure;
- atomic writes and a run log;
- removal or correction of the unsafe fixers;
- version-aware handling of `@api.returns`, `@api.one`, and `sudo`;
- fix counts from a re-scan;
- version-suffix preservation and `--fail-on`.

Approach and decisions: [research.md](research.md).

## Technical Context

**Language/Version**: Python ≥3.10 (tool runtime)

**Primary Dependencies**: Python standard library only (`ast`, `tokenize`, `xml.etree`, `os`,
`tempfile`, `hashlib`, `json`, `shutil`)

**Storage**: Files. Customer modules (write only in fix mode) and the state directory
(`~/.cache/odooflux` by default)

**Testing**: `unittest` (`python -m unittest discover -s tests`)

**Target Platform**: Linux, macOS, Windows (developer workstations, CI)

**Project Type**: CLI (single legacy script in this phase)

**Performance Goals**: No more than 10 % slowdown versus the current script on the Appendix A
fixture and on the P1 fixture set (validation and re-scan add one parse per changed file)

**Constraints**: No new dependencies; no package restructuring (ADR-001); existing CLI options
keep working

**Scale/Scope**: Fixes for the findings listed in spec FR-007/FR-013; about 14 regression tests
plus the safety integration tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle (v2.0.0) | Status | Justification |
|---|---|---|
| I Dependency-light core | PASS | stdlib only |
| II Safe, reversible | DEVIATION (justified) | Implements immutable analysis, verified external backups, atomic writes and the run log. The "working copy, then promote" clause is not met: the legacy tool still writes into the module after a verified backup. Deferred to P2 (REQ-SAF-007); see Complexity Tracking |
| III Deterministic first, validated AI | PASS | The AI path gets the same validation gate; no new AI behaviour |
| IV Honest reporting | PASS | Re-scan-based fix status (FR-008) |
| V Test-backed | PASS | One regression test per finding (FR-012) |
| VI Official evidence | PASS | Version facts cite EV-101/102/103/109/110 |
| VII Layered validation | PASS (partial scope) | L1 syntax only; higher layers are later phases and are not claimed |
| VIII Business logic | PASS | Semantics-changing fixes (`@api.one`, `@api.returns`) become review findings |
| IX Modular | N/A in P0 | Legacy single file; modularisation is P2 |
| X Phase delivery | PASS | Entry/exit criteria from the roadmap |

Post-design re-check: PASS with one justified deviation (Principle II, working copy), recorded below.

## Project Structure

### Documentation (this feature)

```text
specs/001-safety-stabilization/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
odooflux.py                         # legacy script patched in place (only source file changed)
tests/
├── regression/
│   ├── test_p0_safety_readonly.py      # analyze/dry-run hash tests
│   ├── test_p0_validation_gate.py      # rejected writes
│   ├── test_p0_backup_atomic.py        # backup location, verification, atomic write, fault injection
│   ├── test_p0_python_fixers.py        # F-PY-1/2/4/5/6, EV-101/102/103
│   ├── test_p0_xml_fixers.py           # F-XML-1/2/4
│   ├── test_p0_reporting.py            # re-scan fix counts, exit codes, manifest version
│   └── helpers.py                      # tree hashing, temp addons, CLI runner
└── golden_fixtures/
    └── p0_kbi_demo_v14/                # audit Appendix A fixture (input only)
```

**Structure Decision**: Patch the legacy script only. Tests go under `tests/regression/`. P1
generalises the helpers into the shared harness.

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| Principle II: writes go to the module in place (after a verified backup and atomic per-file replace), not via a workspace copy | P0 must stop active damage in the legacy single-file tool now; workspace promotion needs the P2 job/recovery components (REQ-SAF-007) | Adding a workspace to the legacy script would duplicate P2's `core/jobs` and `core/recovery` and be discarded at cut-over. The verified backup outside the addons path plus atomic writes and the run log make every P0 write reversible in the meantime |
