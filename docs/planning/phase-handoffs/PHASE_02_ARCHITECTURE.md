# Phase Handoff — P2 Core Architecture

## 1. Phase ID
P2. Spec Kit feature: [specs/003-core-architecture](../../../specs/003-core-architecture/)

## 2. Phase title
Core Architecture

## 3. Objective
Build the stdlib-only `src/odooflux` core:
- contracts and registries;
- a data-driven version registry and graph;
- a planner with dependency order and blocked-step handling;
- an edit engine with conflict detection and re-scan attribution;
- workspace, promotion, run log, rollback, and resume;
- L1/L2 validators;
- report model v1 and the status decision function;
- discovery;
- a legacy rule adapter.

Then cut over `odooflux.py` to a launcher with characterisation parity.

## 4. Requirements covered
- REQ-ARC-001…006
- REQ-VER-001…006
- REQ-SAF-006…009
- REQ-TRF-001, REQ-TRF-005
- REQ-VAL-001, 002, 006 (model)
- REQ-REP-001 (schema)
- REQ-DEP-002
- REQ-SEC-001
- REQ-PRF-001 (baseline)
- REQ-MAN-001

Mapping: [spec.md](../../../specs/003-core-architecture/spec.md#functional-requirements).

## 5. Repository context
- `odooflux.py` is the legacy script (P0-patched), pinned by the P1 characterisation suite.
- `src/odooflux/**` contains `.gitkeep` scaffolding only, with **no** `__init__.py` (ADR-001).
- Structure and ownership: [PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md).
- Design: [TARGET_ARCHITECTURE.md](../TARGET_ARCHITECTURE.md), [CONTRACTS.md](../architecture/CONTRACTS.md),
  [ARCHITECTURE_DECISIONS.md](../ARCHITECTURE_DECISIONS.md) (ADR-001…016).

## 6. Prerequisites
- P1 exit criteria met.
- D-01 (constitution 2.0.0) approved.
- D-09 (pyproject with optional extras) approved. If D-09 is pending, skip T001 and run via the
  launcher only.
- D-10 default: keep every legacy option; `--api-key` only warns.

## 7. Dependencies
Depends on P1. Downstream: P3, P4, P7, P8 (all depend on P2).

## 8. Expected files and components
See the [plan.md source tree](../../../specs/003-core-architecture/plan.md#source-code-repository-root):
- `pyproject.toml`;
- `src/odooflux/{cli,core/*,discovery,versions/{registry,graph},dependencies,rules/shared,parsers/{python,xml},validation/{syntax,static},reporting/model,ai/providers (legacy wrapper),knowledge/versions.json,utils}`;
- `tests/{unit,contract,integration,benchmarks}` additions;
- `docs/guides/ADDING_A_VERSION.md`;
- `docs/changes/P2_CUTOVER.md`.

## 9. Interfaces and contracts
- Base: [CONTRACTS.md](../architecture/CONTRACTS.md) (`CONTRACT_VERSION = 1`).
- P2 refinements: [contracts/](../../../specs/003-core-architecture/contracts/)
  - `cli.md`: subcommands and exit codes;
  - `registries-and-plugins.md`;
  - `recovery.md`;
  - `result-model-v1.md`.
- Data model and state transitions: [data-model.md](../../../specs/003-core-architecture/data-model.md).

## 10. Official evidence requirements
- `versions.json`:
  - Python ranges from EV-125;
  - Online-release folding from EV-001 (ADR-007);
  - research status copied from [VERSION_COMPATIBILITY_MATRIX.md](../VERSION_COMPATIBILITY_MATRIX.md).
- `legacy-*` rules carry their EV IDs where P0 added them. Otherwise they are listed as waivers in
  `P2_CUTOVER.md` and in each report (Complexity Tracking).
- No new Odoo claims.

## 11. Detailed implementation tasks
Full text: [tasks.md](../../../specs/003-core-architecture/tasks.md).

| Tasks | Scope | Acceptance |
|---|---|---|
| T001–T003 | pyproject, package skeleton, cut-over record | No third-party installs |
| T004–T011 | Guard tests, contracts, registries, utils | TST-003-001…006 |
| T012–T023 | Versions, graph, dependency order, discovery, planner, add-version guide | TST-003-007…013 |
| T024–T033 | Run log, workspace, promotion, rollback, resume | TST-003-014, 015, 030…035 |
| T034–T042 | Edit engine, re-scan, L1/L2, step runner | TST-003-016…020 |
| T043–T047 | Status function, report model, determinism | TST-003-021…023 |
| T048–T050 | Plugins | TST-003-024…026 |
| T051–T058 | Legacy adapter, CLI, renderers, launcher cut-over | TST-003-027…029, 038…040 |
| T059–T062 | Benchmark baseline, structure test, docs, verification | TST-003-036/037 |

## 12. Acceptance criteria
Roadmap exit criteria:
- contract tests pass;
- registries accept sample plugins without core edits;
- the graph plans every pair;
- workspace, run log, rollback, and resume pass failure injection;
- report model v1 is published;
- cut-over is done with characterisation passing or each difference documented;
- the determinism test passes;
- the baseline benchmark is recorded.

Plus spec SC-001…SC-007.

## 13. Unit tests
TST-003-001…012, 014, 016…022, 027, 037.

## 14. Integration tests
TST-003-013, 015, 023…026, 028…035, 038…040.

## 15. Runtime tests
N/A. No Odoo runtime is used in P2. L3–L5 report `UNAVAILABLE`, which caps status (tested in
TST-003-021).

## 16. Negative test cases
- Contract version mismatch (TST-003-025).
- Duplicate registration (TST-003-005).
- Overlapping edits and `before` mismatch (TST-003-016).
- Unresearched step → `BLOCKED` (TST-003-012).
- Resume with a changed source → refused (TST-003-035).
- Rollback conflict skipped (TST-003-033).
- Promotion failure → auto-restore (TST-003-031).
- Planted third-party import, `exec`, or version literal → guard tests fail.

## 17. Security requirements
- No execution or import of customer code (REQ-SEC-001; TST-003-002).
- Plugins only from explicit `--plugin` or config.
- State dir never inside scanned paths.
- Symlinks are not followed out of module roots.
- Redaction utility used for any credential-bearing value.

## 18. Performance requirements
- No more than 20 % slower than the legacy CLI on the P1 fixtures (record both).
- Baseline wall time and peak RSS for 300 synthetic modules recorded in
  `tests/benchmarks/BASELINE.md`. No budget is enforced until P9.

## 19. Backward compatibility
- `python odooflux.py` with legacy flags keeps working.
- The legacy JSON report shape stays the default for `--report`; v1 comes with
  `--report-format json`.
- Every difference is listed in `docs/changes/P2_CUTOVER.md` and verified by TST-003-029.
- Run logs from P0 (`runlog/0`) remain readable for rollback.

## 20. Prohibited changes
- New migration rules or rule semantics (P5).
- Fine-grained span parsers (P4).
- Runtime containers (P7).
- New AI providers (P6).
- Third-party imports in core packages.
- Hardcoded version literals in the engine.
- Removing legacy options without D-10.

## 21. Definition of Done
- All 62 tasks are checked.
- The full offline suite passes (P0, P1, P2 tests).
- Unexplained characterisation failures = 0.
- `BASELINE.md` is recorded.
- The `verification.md` evidence is complete.

## 22. Implementation agent instructions
1. Set `.specify/feature.json` → `{"feature_directory": "specs/003-core-architecture"}`.
2. Read [spec.md](../../../specs/003-core-architecture/spec.md), [plan.md](../../../specs/003-core-architecture/plan.md),
   [research.md](../../../specs/003-core-architecture/research.md), [data-model.md](../../../specs/003-core-architecture/data-model.md),
   [contracts/](../../../specs/003-core-architecture/contracts/), and [tasks.md](../../../specs/003-core-architecture/tasks.md).
3. Run `/speckit-implement` (not run by the planning agent).
4. Do the cut-over (T057) last. Until then, `odooflux.py` stays the legacy implementation.
5. Stop and ask before changing any contract field in CONTRACTS.md (a contract-version change
   needs an ADR).

## 23. Expected verification evidence
`specs/003-core-architecture/verification.md`:
- the unittest output;
- quickstart outputs (`plan` output, ROLLBACK-OK, determinism diff empty);
- the characterisation summary with documented differences;
- the import-graph test output;
- the baseline benchmark numbers.

## 24. Handoff checklist
- [ ] P1 exit verified; D-01, D-09 recorded as approved
- [ ] All TST-003-* pass; SC-001…SC-007 evidenced
- [ ] `P2_CUTOVER.md` complete and tested
- [ ] No core third-party imports; no version literals
- [ ] Remaining scaffold directories still have `.gitkeep`
- [ ] [SPECKIT_READINESS.md](../SPECKIT_READINESS.md) P2 row updated; P3/P4/P7 unblocked
