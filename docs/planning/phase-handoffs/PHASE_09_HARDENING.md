# Phase Handoff P9 — Hardening and Release Readiness

## 1. Phase ID
P9 — Spec Kit feature [`specs/010-hardening-release`](../../../specs/010-hardening-release/)

## 2. Phase title
Hardening and Release Readiness

## 3. Objective
Gate the release. Every requirement must be verified, performance budgets met at 300 modules, incremental and parallel runs deterministic, the audit log and secret safety proven, the failure-injection suite passing, and a support statement derived from data.

## 4. Requirements covered
REQ-PRF-001…004, REQ-SEC-005, REQ-AI-008 (final removal of CLI keys), REQ-TST-005, plus the final verification of all REQs through the RTM gate.

## 5. Repository context
All earlier phases are delivered under `src/odooflux/`. The RTM is in [REQUIREMENTS_TRACEABILITY_MATRIX.md](../REQUIREMENTS_TRACEABILITY_MATRIX.md). The baseline benchmark and reference machine were recorded in P2.

## 6. Prerequisites
P5, P6, P7, and P8 exit criteria met ([IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#p9--hardening-and-release-readiness)). The P2 baseline exists.

## 7. Dependencies
Orchestrator (P2), recovery (P2), AI credentials (P6), runtime teardown (P7), renderers (P8), matrix data (P3/P5/P7).

## 8. Expected files and components
`src/odooflux/core/orchestrator/{parallel,incremental}.py`, `core/recovery/audit_log.py`, `utils/redaction.py`, `cli/support_statement.py`, `tests/benchmarks/{corpus_gen,run_benchmarks}.py`, `budgets.json`, `REFERENCE_MACHINE.md`, `tests/integration/hardening/*`, `tests/unit/release/*`, `docs/planning/RELEASE_CHECKLIST.md`, `docs/planning/SUPPORT_STATEMENT.md` (generated).

## 9. Interfaces and contracts
[contracts/benchmark-protocol.md](../../../specs/010-hardening-release/contracts/benchmark-protocol.md), [contracts/audit-log.md](../../../specs/010-hardening-release/contracts/audit-log.md).

## 10. Official evidence requirements
The support statement must be generated from knowledge-base research status and runtime results. No path is marked supported without evidence-backed `RULES_TESTED` steps and a `RUNTIME_VALIDATED` target (Principle VI).

## 11. Detailed implementation tasks
See [specs/010-hardening-release/tasks.md](../../../specs/010-hardening-release/tasks.md) (T001–T024).

## 12. Acceptance criteria
Spec SC-001…SC-005. Roadmap exit:
1. Performance budgets are met at 300 modules.
2. Incremental and parallel runs are deterministic.
3. The audit log is complete.
4. Secret scanning is clean.
5. The failure-injection suite passes.
6. Every requirement in the RTM has passing verification.
7. The release checklist is signed off.

## 13. Unit tests
TST-010-001, -002, -003, -009.

## 14. Integration tests
TST-010-004, -005, -007, -008, -010, -011.

## 15. Runtime tests where applicable
TST-010-010 includes runtime teardown fault injection when `ODOOFLUX_RUNTIME_TESTS=1`. Benchmarks TST-010-006 run with `ODOOFLUX_BENCHMARKS=1`.

## 16. Negative test cases
An unmapped REQ, a finding without a citing regression test, an over-budget benchmark, a >20 % regression, a tampered audit log, canary secrets, `--api-key` after the window, kill/disk-full at each injection point, and a failed parallel worker.

## 17. Security requirements
Hash-chained audit log. Redaction of secrets. CLI credential removal. Artefacts confined to the state dir. Secret scan of all artefacts as a release gate.

## 18. Performance requirements
Budgets from [contracts/benchmark-protocol.md](../../../specs/010-hardening-release/contracts/benchmark-protocol.md). Values are derived from the recorded P2 baseline and approved; none are assumed in planning.

## 19. Backward compatibility
The D-10 deprecations end in this phase (`--api-key` and legacy JSON/exit mapping, as decided). The change log lists each removal.

## 20. Prohibited changes
No new features (gaps become new specs). Budgets must not be weakened without recorded approval. No support claims beyond the data.

## 21. Definition of Done
All tasks done. All TST-010-* pass. The RTM gate passes with 0 unmapped REQs. Benchmarks are within budget. The release checklist is signed. The support statement is generated.

## 22. Implementation agent instructions
1. Set `.specify/feature.json` to `{"feature_directory": "specs/010-hardening-release"}`.
2. Build the gate first (US1) to surface gaps early. Route each gap to its owning phase or a new spec instead of fixing silently.
3. Use `/speckit-implement` (not run during planning).

## 23. Expected verification evidence
RTM gate output, benchmark results JSON with machine profile, audit log sample with chain verification, secret-scan output, failure-injection report, the signed release checklist, and the generated support statement.

## 24. Handoff checklist
- [ ] P5–P8 exits verified; baseline present
- [ ] feature.json points at 010
- [ ] Gate (US1) implemented first
- [ ] Budgets recorded with approver
- [ ] All injection points pass
- [ ] Release checklist signed
- [ ] RTM and SPECKIT_READINESS final
