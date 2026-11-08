# Phase Handoff — P0 Safety Stabilization

## 1. Phase ID
P0. Spec Kit feature: [specs/001-safety-stabilization](../../../specs/001-safety-stabilization/)

## 2. Phase title
Safety Stabilization

## 3. Objective
Stop the legacy `odooflux.py` from damaging customer modules:
- no writes outside `--fix`;
- no invalid file ever written;
- backups outside scanned paths, verified;
- atomic writes and a run log;
- unsafe or incorrect fixers removed or made version-correct;
- fix counts from a re-scan.

## 4. Requirements covered
REQ-SAF-001, 002, 003, 004, 005, 006 (log), 010; REQ-TRF-005; REQ-MAN-001 (write-mode-only rename),
REQ-MAN-002; REQ-REP-005 (basic `--fail-on`); REQ-SEC-003; REQ-VAL-001; REQ-TST-005.
Mapping: [spec.md](../../../specs/001-safety-stabilization/spec.md#functional-requirements).

## 5. Repository context
- One application file: `odooflux.py` (1,801 lines, stdlib only) at commit `c9914e6`.
- No tests exist yet; scaffold directories under `tests/` contain `.gitkeep` only.
- Defects and reproductions: [ODOO_MODULE_UPGRADER_AUDIT.md](../../reviews/ODOO_MODULE_UPGRADER_AUDIT.md),
  Appendix A.
- `src/odooflux/` is scaffolding only. **Do not** put code there in P0 (ADR-001).

## 6. Prerequisites
- Planning package approved. D-01 is not required for P0 (stdlib only).
- Python ≥3.10.

## 7. Dependencies
None (first phase). Downstream: P1 builds on these tests; P2 consumes the run-log format.

## 8. Expected files and components
`odooflux.py` (patched); `tests/__init__.py`, `tests/regression/{__init__,helpers}.py`,
`tests/regression/test_p0_*.py`; `tests/golden_fixtures/p0_kbi_demo_v14/`;
`docs/changes/P0_CHANGE_RECORD.md`; `specs/001-safety-stabilization/verification.md`.

## 9. Interfaces and contracts
- CLI additions: `--state-dir`, `--fail-on {none,info,warning,critical}`; exit codes 0/1/3 (2 =
  argparse).
- Run log `odooflux.runlog/0` and BackupManifest: [data-model.md](../../../specs/001-safety-stabilization/data-model.md).
- Forward-compatible with [CONTRACTS.md](../architecture/CONTRACTS.md) (Finding status vocabulary).

## 10. Official evidence requirements
Version-dependent behaviour must follow these records, and messages must cite them:
- EV-101: `@api.one`/`@api.multi` removed in 13.0.
- EV-102: `@api.returns` removed in 19.0.
- EV-103: `sudo(user)` changed to `sudo(flag)` plus `with_user` in 13.0.
- EV-109: `attrs`/`states` rejected from 17.0.
- EV-110: `Warning` removed in 17.0.

See [OFFICIAL_EVIDENCE_REGISTER.md](../research/OFFICIAL_EVIDENCE_REGISTER.md). Do not add new
Odoo claims in P0.

## 11. Detailed implementation tasks
Full text: [tasks.md](../../../specs/001-safety-stabilization/tasks.md).

| Tasks | Scope | Acceptance |
|---|---|---|
| T001–T002 | Harness helpers, P0 fixture | Fixture reproduces 25 issues on the unpatched script |
| T003–T008 | State dir, atomic write, run log | TST-001-001/002/003 |
| T009–T011 | US1 read-only analysis | TST-001-004/005/006 |
| T012–T024 | US2 validation gate and fixer repairs | TST-001-007…016 |
| T025–T027 | US3 backups | TST-001-017/018/019 |
| T028–T039 | US4 version-correct fixes, re-scan counts, manifest suffix | TST-001-020…027 |
| T040–T043 | US5 exit codes, no artefacts in modules | TST-001-028/029/030 |
| T044–T046 | Change record, help text, verification | SC-001…SC-005 evidenced |

## 12. Acceptance criteria
Roadmap exit criteria:
- every Appendix A reproduction has a passing regression test;
- the analyze/dry-run hash test passes;
- injected invalid output is never written;
- backups are outside the addons path and verified;
- fix counts come from a re-scan.

Plus spec SC-001…SC-005.

## 13. Unit tests
TST-001-011/012 (Python fixers), 013/014 (XML fixer), 015, 020–023 (version-aware fixes), 024
(attrs detect-only), 026 (manifest suffix), 027 (messages).

## 14. Integration tests
TST-001-004/005/006 (read-only), 007–010 (validation gate incl. AI path), 016 (fixture fix outputs
valid), 017–019 (backups), 025 (re-scan counts), 028–030 (exit codes, artefacts), 003 (run log).

## 15. Runtime tests
N/A. P0 only performs syntax validation; containerised runtime validation is P7.

## 16. Negative test cases
- Invalid fixer output (Python, XML, manifest) → not written.
- `.sudo(False)`/`.sudo(True)` → unchanged.
- `@api.returns` with target 18 → kept.
- `states=` with an existing `invisible=` → skipped.
- State dir inside the scanned path → exit 4.
- Backup verification mismatch → `BLOCKED`.
- `os.replace` failure → original intact.

## 17. Security requirements
- No tool artefacts inside customer modules (REQ-SEC-003; TST-001-030).
- API keys never written to logs or the run log (existing behaviour preserved; checked by grepping
  the run log in TST-001-030).

## 18. Performance requirements
No more than 10 % slower than the unpatched script on the P0 fixture. Record both timings in
`verification.md`.

## 19. Backward compatibility
- All existing CLI options are kept.
- Behaviour changes are listed in `docs/changes/P0_CHANGE_RECORD.md`:
  - default exit code (`--fail-on critical`);
  - backup location;
  - detect-only rules (`attrs`, `@api.one`, JS);
  - the `@api.returns` gating;
  - the manifest suffix.
- The JSON report keeps its fields; `fix_applied` now means "absent on re-scan".

## 20. Prohibited changes
- Creating `src/odooflux/` code or any `__init__.py` outside `tests/`.
- Adding dependencies.
- Restructuring `odooflux.py` beyond the listed fixes.
- Adding new migration rules.
- Changing AI prompts or model.
- Removing CLI options.

## 21. Definition of Done
- All 46 tasks are checked.
- `python -m unittest discover -s tests` passes offline.
- The quickstart outputs are recorded in `verification.md`.
- The change record is complete.
- No file outside `odooflux.py`, `tests/`, `docs/changes/`, and `specs/001-*/verification.md` is
  modified.

## 22. Implementation agent instructions
1. Set the active feature: `.specify/feature.json` → `{"feature_directory": "specs/001-safety-stabilization"}`.
2. Read [spec.md](../../../specs/001-safety-stabilization/spec.md), [plan.md](../../../specs/001-safety-stabilization/plan.md),
   [research.md](../../../specs/001-safety-stabilization/research.md), and [tasks.md](../../../specs/001-safety-stabilization/tasks.md).
3. Run the Spec Kit implement command for this feature: `/speckit-implement`. The planning agent
   has **not** run it.
4. Write each test first and confirm it fails, then implement. Mark a task `[x]` only when its
   "Done when" holds.
5. Line references are at `c9914e6`. If the file has drifted, locate the code by function name.
6. Stop and ask if a fix would require a new Odoo claim or a structural refactor.

## 23. Expected verification evidence
`specs/001-safety-stabilization/verification.md` containing:
- the unittest output;
- the quickstart command outputs (READ-ONLY-OK, PY-OK, XML-OK, backup listing, run log excerpt);
- before/after timing;
- the list of test IDs → finding IDs.

## 24. Handoff checklist
- [ ] Entry criteria met (plan approved)
- [ ] All tasks done; all TST-001-* pass
- [ ] SC-001…SC-005 evidenced
- [ ] Change record written
- [ ] Prohibited changes respected (check `git diff --stat`)
- [ ] `.specify/feature.json` updated for P1 (`specs/002-test-foundation`) by the P1 agent
- [ ] [SPECKIT_READINESS.md](../SPECKIT_READINESS.md) P0 row updated to "Implemented"
