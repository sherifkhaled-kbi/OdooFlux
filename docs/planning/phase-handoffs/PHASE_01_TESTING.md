# Phase Handoff — P1 Test Foundation

## 1. Phase ID
P1. Spec Kit feature: [specs/002-test-foundation](../../../specs/002-test-foundation/)

## 2. Phase title
Test Foundation

## 3. Objective
An offline `unittest` foundation:
- a shared harness;
- golden fixtures for source versions 12.0–18.0 with expected legacy outputs;
- a black-box characterisation suite that pins the P0-patched CLI behaviour for the P2 cut-over;
- a regression index;
- a rule-coverage report;
- opt-in gates for runtime, network, and AI suites.

## 4. Requirements covered
REQ-TST-001, 002 (report-only), 003, 004, 005, 006. Mapping: [spec.md](../../../specs/002-test-foundation/spec.md#functional-requirements).

## 5. Repository context
- `odooflux.py` patched by P0.
- `tests/regression/test_p0_*.py`, `tests/regression/helpers.py`, and
  `tests/golden_fixtures/p0_kbi_demo_v14/` exist from P0.
- Other `tests/` subdirectories contain `.gitkeep` only.

## 6. Prerequisites
P0 exit criteria met ([PHASE_00_SAFETY.md](PHASE_00_SAFETY.md)).

## 7. Dependencies
Depends on P0. Downstream: P2 (characterisation gates the cut-over), P5 (fixtures, coverage
enforcement), P3 (research data entry may start after P1).

## 8. Expected files and components
`tests/README.md`, `tests/_support/*`, `tests/{unit,integration,regression,contract,runtime,benchmarks}/__init__.py`,
`tests/golden_fixtures/{.gitattributes,INDEX.json,v12_*,v13_*,v14_kbi_demo,v15_*,v16_*,v17_*,v18_*}`,
`tests/regression/INDEX.md`, `tools/update_expectations.py`, `specs/002-test-foundation/verification.md`.

## 9. Interfaces and contracts
- Fixture layout and INDEX schema: [data-model.md](../../../specs/002-test-foundation/data-model.md).
- Harness API: `copy_fixture`, `tree_digest`, `run_legacy_cli`, `normalize_report`,
  `requires_runtime/network/ai`.
- Environment flags: `ODOOFLUX_RUNTIME_TESTS`, `ODOOFLUX_NETWORK_TESTS`, `ODOOFLUX_AI_TESTS`.

## 10. Official evidence requirements
Fixtures may only contain version-specific constructs backed by an EV record (or generic syntax).
Each fixture README lists its EV IDs (research R-03). No new Odoo claims.

## 11. Detailed implementation tasks
Full text: [tasks.md](../../../specs/002-test-foundation/tasks.md).

| Tasks | Scope | Acceptance |
|---|---|---|
| T001–T002 | Packages, fixture attributes | P0 tests still pass |
| T003–T007 | Harness and P0 migration | TST-002-001/002/003 |
| T008–T009 | Docs, offline guard | TST-002-004 |
| T010–T017 | Seven golden fixtures | TST-002-005 (SC-002) |
| T018–T022 | Expectation updater, characterisation | TST-002-006/007/008 (SC-003) |
| T023–T026 | Regression index, runtime gate, coverage report | TST-002-009/010/011 |
| T027–T028 | Timing, verification | SC-001…SC-005 |

## 12. Acceptance criteria
Roadmap exit criteria:
- `python -m unittest discover -s tests` passes offline;
- golden fixtures exist for 12.0–18.0 with expected legacy outputs;
- characterisation pins the CLI;
- opt-in suites are skipped by default.

Plus spec SC-001…SC-005.

## 13. Unit tests
TST-002-001/002/003 (harness), TST-002-011 (coverage report).

## 14. Integration tests
TST-002-004 (offline guard), 005 (fixture validity), 006 (characterisation), 007 (sensitivity),
008 (input immutability), 009 (regression index).

## 15. Runtime tests
Only the gate (TST-002-010). Real runtime tests are P7.

## 16. Negative test cases
- A mutated expectation is detected (TST-002-007).
- A planted network call fails under the offline guard.
- The updater refuses a dirty tree.
- A fixture with a wrong manifest prefix fails validity.

## 17. Security requirements
Fixtures are synthetic; no customer code. Tests never write outside temp dirs (TST-002-008).

## 18. Performance requirements
Default suite under 120 s (SC-001). Record it in `verification.md`.

## 19. Backward compatibility
No change to `odooflux.py`. P0 tests keep their assertions (T007).

## 20. Prohibited changes
- Modifying `odooflux.py`.
- Adding dependencies (pytest is optional for local use only).
- Putting product code in `src/`.
- Changing P0 test assertions.

## 21. Definition of Done
- All 28 tasks are checked.
- The default suite passes offline in under 120 s.
- Seven fixtures are indexed.
- Characterisation passes.
- The regression index is complete.
- `verification.md` is written.

## 22. Implementation agent instructions
1. Set `.specify/feature.json` → `{"feature_directory": "specs/002-test-foundation"}`.
2. Read spec, plan, research, data-model, and tasks for 002.
3. Run `/speckit-implement` (not run by the planning agent).
4. Author fixtures by hand and keep them minimal. Every construct gets an EV reference or is
   generic.
5. Generate expectations only with `tools/update_expectations.py`. Never hand-edit expected outputs.
6. Stop and ask if a fixture needs an Odoo construct without an EV record.

## 23. Expected verification evidence
`specs/002-test-foundation/verification.md`:
- the full unittest output (counts, skips with reasons);
- the suite duration;
- the fixture index;
- characterisation case count;
- the regression index snapshot.

## 24. Handoff checklist
- [ ] P0 exit verified
- [ ] All TST-002-* pass; skips explained
- [ ] SC-001…SC-005 evidenced
- [ ] No change to `odooflux.py`
- [ ] Expectations generated by the tool and committed
- [ ] [SPECKIT_READINESS.md](../SPECKIT_READINESS.md) P1 row updated
