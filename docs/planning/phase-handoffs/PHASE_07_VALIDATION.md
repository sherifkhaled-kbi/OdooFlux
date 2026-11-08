# Phase Handoff P7 — Runtime and Behavioral Validation

## 1. Phase ID
P7 — Spec Kit feature [`specs/008-runtime-behavioral-validation`](../../../specs/008-runtime-behavioral-validation/)

## 2. Phase title
Runtime and Behavioral Validation

## 3. Objective
Decide module result statuses honestly from the validation layers that actually ran. Add L3 dependency integrity, optional RNG validation, isolated install and upgrade on the target version, and source/target behavioural comparison.

## 4. Requirements covered
REQ-VAL-003, REQ-VAL-004, REQ-VAL-005, REQ-VAL-006, REQ-XML-004 (RNG), REQ-ACL-002, REQ-BIZ-002, REQ-BIZ-003, REQ-SEC-001, REQ-SEC-002, REQ-DEP-003 (L3 part).

## 5. Repository context
The legacy tool has no validation beyond `ast.parse` on AI output (F-VAL-1, F-VAL-2). Target code goes in `src/odooflux/validation/`. Strategy: [VALIDATION_AND_TEST_STRATEGY.md](../VALIDATION_AND_TEST_STRATEGY.md). ADR-011 covers runtime containers.

## 6. Prerequisites
P2 exit criteria met. D-03 decided (default: Docker CLI). D-02 decided for RNG (default: optional `lxml`).

## 7. Dependencies
P2 contracts (`Validator`, `ValidationResult`, `RuntimeEnvironment`), orchestrator, and workspace. Knowledge data (P3) for core module lists and RNG file locations. Can run in parallel with P3–P6.

## 8. Expected files and components
`src/odooflux/validation/status.py`, `validation/dependency/integrity.py`, `validation/static/rng.py`, `validation/runtime/{docker_env,log_classifier}.py`, `validation/behavioral/compare.py`, `knowledge/compatibility/runtime_log_patterns.json`, runtime fixtures in `tests/golden_fixtures/runtime/`, tests in `tests/{unit/validation,integration/validation,runtime}/`.

## 9. Interfaces and contracts
[contracts/status-decision.md](../../../specs/008-runtime-behavioral-validation/contracts/status-decision.md), [contracts/runtime-environment.md](../../../specs/008-runtime-behavioral-validation/contracts/runtime-environment.md), `ValidationResult` extension (`coverage`, `reason`), coordinated with the P2 owner (T009).

## 10. Official evidence requirements
- Runtime CLI options: EV-303.
- RNG schema files per version: EV-302.
- Image provenance: EV-301, plus gaps G-R-13 and G-R-21.
- Log patterns (G-R-22) and test output formats (G-R-23) must be researched from official source at pinned SHAs before the runtime adapter is enabled by default (T001–T004).

## 11. Detailed implementation tasks
See [specs/008-runtime-behavioral-validation/tasks.md](../../../specs/008-runtime-behavioral-validation/tasks.md) (T001–T029).

## 12. Acceptance criteria
Spec SC-001…SC-005. Roadmap exit:
1. Install and upgrade on the target version run in isolation with limits.
2. Log analysis classifies errors.
3. Behavioural comparison of source and target test runs works.
4. The status decision table is fully tested.
5. RNG validation runs when available.

## 13. Unit tests
TST-008-001, -002, -004, -005, -009, -011, -012, -013.

## 14. Integration tests
TST-008-003.

## 15. Runtime tests where applicable
TST-008-006 (install outcomes), -007 (limits and teardown), -008 (upgrade), -010 (behaviour comparison). All opt-in with `ODOOFLUX_RUNTIME_TESTS=1`.

## 16. Negative test cases
Broken view, ACL on missing model, infinite loop at install, missing Docker, missing image, Enterprise dependency, missing Python dependency, no tests in module, no source baseline, `lxml` absent, required layer unavailable (→ BLOCKED).

## 17. Security requirements
Customer code runs only inside containers. The module mount is read-only. No network by default. CPU, memory, pids, and wall-time limits are enforced. No privileged mode. Teardown is guaranteed and resources are labelled with the run ID. Images are digest-pinned and allow-listed. The tool process never executes customer code (TST-008-013).

## 18. Performance requirements
One environment per target version per job, with modules installed in dependency order in one database. Default limits are configured from measured fixture baselines (documented in quickstart results), not assumed.

## 19. Backward compatibility
The legacy CLI has no runtime validation. New options (`--validate`, `--require`, `--validate-intermediate`) are additive. Static-only runs behave as before, with an honest status.

## 20. Prohibited changes
No execution of customer code on the host. No `PASS` for layers that did not run. No hardcoded version-specific log patterns in code (data only). No database migration of customer data.

## 21. Definition of Done
All tasks done with evidence. Offline suite passes. The opt-in runtime suite passes on at least one target version, with results recorded. Research gaps G-R-13…16 are closed or explicitly capped. The matrix is regenerated (T029).

## 22. Implementation agent instructions
1. Set `.specify/feature.json` to `{"feature_directory": "specs/008-runtime-behavioral-validation"}` when starting.
2. Do the research tasks T001–T004 first, recording evidence with SHA/path/line; never use unofficial sources.
3. Use `/speckit-implement` (installed Spec Kit 1.3.1 command; not run during planning).
4. Stop and ask if the status table needs a change: it is a cross-phase contract.

## 23. Expected verification evidence
Offline test logs, runtime test logs with image digests, a resource-cleanup listing per run, updated research.md EV rows, regenerated matrix, and quickstart results.

## 24. Handoff checklist
- [ ] P2 exit verified; D-02, D-03 decided
- [ ] feature.json points at 008
- [ ] Research T001–T004 complete or gaps capped
- [ ] TST-008-* written first
- [ ] Runtime suite run at least once with recorded digests
- [ ] No leftover containers after the test suite
- [ ] RTM and SPECKIT_READINESS updated
