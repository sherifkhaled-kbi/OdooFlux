# Feature Specification: Runtime and Behavioral Validation

**Feature Branch**: `008-runtime-behavioral-validation`
**Created**: 2026-11-06
**Status**: Draft — planned, not implemented
**Input**: Roadmap phase P7: "Implement isolated Odoo installation, upgrade, and functional verification."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Honest result status from the layers that actually ran (Priority: P1)

A migration engineer needs each module's final status to reflect exactly which validation layers ran and passed, so that a module is never reported as verified on syntax alone.

**Why this priority**: Principle VII; this decision table is needed even when no runtime is available.

**Independent Test**: Feed the status decision function every combination of layer outcomes, findings, and plan flags from [contracts/status-decision.md](contracts/status-decision.md); compare with the expected status.

**Acceptance Scenarios**:
1. **Given** L1–L3 pass and the runtime adapter is unavailable, **When** status is decided, **Then** the module is `STATIC_VALIDATED` and the report lists L4/L5 as unavailable.
2. **Given** L4 install fails, **When** status is decided, **Then** the module is `FAILED` with the classified log excerpt.
3. **Given** all layers pass but one review-required finding is open, **When** status is decided, **Then** the module is `NEEDS_REVIEW`.

---

### User Story 2 - Install and upgrade in an isolated target environment (Priority: P1)

The engineer runs `--validate runtime` and OdooFlux installs the migrated modules, in dependency order, in a disposable target-version environment. The environment has no network, CPU/memory/time limits, and a read-only module mount. OdooFlux then reports registry, view, asset, and ACL loading errors.

**Why this priority**: Installation is the first objective evidence of compatibility (OBJ-009).

**Independent Test**: With `ODOOFLUX_RUNTIME_TESTS=1`, run the install fixture (expected `INSTALL_VERIFIED`) and the broken fixture (expected `FAILED` with a classified error).

**Acceptance Scenarios**:
1. **Given** a clean migrated module, **When** installed with `--stop-after-init`, **Then** L4 = PASS and the log contains no ERROR/CRITICAL lines attributable to the module.
2. **Given** a module with an invalid view, **When** installed, **Then** L4 = FAIL with class `view_validation` and the offending file/xml-id.
3. **Given** a module with an infinite loop at install, **When** the time limit is reached, **Then** the environment is killed, L4 = FAIL with class `timeout`, and no container remains.
4. **Given** an ACL row referencing a missing model, **When** installed, **Then** L4 = FAIL with class `access_rights`.

---

### User Story 3 - Behavioral comparison between source and target (Priority: P2)

The engineer wants evidence that business behaviour is preserved. OdooFlux runs the module's own tests on the source version (baseline) and on the target version, and reports regressions, pre-existing failures, and tests that could not be run.

**Why this priority**: Required for `VERIFIED_SUCCESS`, but depends on US2.

**Independent Test**: Behavioural fixture with one test that passes on both versions, one that regresses, and one that fails on both. Expect L5 = FAIL listing exactly the regression, with the pre-existing failure listed separately.

**Acceptance Scenarios**:
1. **Given** all baseline-passing tests also pass on target and ≥1 test ran, **When** L5 completes, **Then** L5 = PASS with `coverage = full`.
2. **Given** no source-version runtime is available, **When** L5 runs, **Then** target tests run, L5 is reported with `coverage = partial`, and the status cannot exceed `INSTALL_VERIFIED`.
3. **Given** a module without tests, **When** L5 runs, **Then** L5 = SKIPPED with reason `no_tests` and the report states that behaviour is unverified.

---

### User Story 4 - Static dependency integrity and view schema checks (Priority: P2)

Before any runtime, OdooFlux checks module dependencies, models, fields, XML IDs, groups, and Python packages. When the RNG adapter is installed, it also validates modified view archs against the target version's RNG schemas.

**Independent Test**: Fixtures with one broken reference of each kind yield one finding each. A malformed list view fails RNG validation when `lxml` is present; when `lxml` is absent, L2-RNG reports UNAVAILABLE.

**Acceptance Scenarios**:
1. **Given** a view referencing a field that no scanned or core model defines, **When** L3 runs, **Then** a finding `dangling_field` is produced.
2. **Given** `lxml` is not installed, **When** RNG validation is requested, **Then** the validator reports UNAVAILABLE and the status is capped per the decision table.

### Edge Cases

- Docker is not installed or the daemon is unreachable → L4/L5 UNAVAILABLE, status capped, no error exit (unless `--require runtime` → `BLOCKED`).
- The target image for the requested version is unavailable (see G-R-21) → L4 UNAVAILABLE with reason `image_unavailable`.
- Module depends on Enterprise modules (D-05: no access) → L4 SKIPPED for that module with reason `enterprise_dependency`; status ≤ `STATIC_VALIDATED`.
- Module requires extra Python packages (`external_dependencies`) → installed only from an allow-listed index inside the container, else L4 FAIL with class `missing_python_dependency`.
- Container teardown fails → reported as a tool warning; a cleanup command is printed; leftovers are labelled with the run ID.
- Very large log output → captured to the state dir, excerpted (configurable lines) in the report.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The status decision MUST follow [contracts/status-decision.md](contracts/status-decision.md) exactly, with precedence `BLOCKED > FAILED > NEEDS_REVIEW > VERIFIED_SUCCESS > INSTALL_VERIFIED > STATIC_VALIDATED`. Traces: REQ-VAL-006, REQ-BIZ-003
- **FR-002**: A validation layer that did not run MUST be reported as `UNAVAILABLE` or `SKIPPED` with a reason; it MUST NOT be reported as `PASS`. Traces: REQ-VAL-006
- **FR-003**: L3 MUST check module dependencies, models, fields, XML IDs, groups, and declared Python packages against scanned modules and target-version knowledge data. Traces: REQ-VAL-003, REQ-DEP-003
- **FR-004**: L4 MUST install (and, on request, upgrade) migrated modules in dependency order in a disposable environment for the target version. Traces: REQ-VAL-004
- **FR-005**: The runtime environment MUST mount the module copy read-only, disable network by default, enforce CPU, memory, and wall-time limits, and always tear down. Traces: REQ-SEC-001, REQ-SEC-002
- **FR-006**: Runtime logs MUST be captured and classified (`import_error`, `registry`, `view_validation`, `access_rights`, `data_load`, `asset_compile`, `missing_python_dependency`, `timeout`, `oom`, `unknown`) with file/xml-id attribution when present. Traces: REQ-VAL-004, REQ-ACL-002
- **FR-007**: L4 MUST check that access rights load and declared groups resolve, and report failures as `FAILED`. Traces: REQ-ACL-002
- **FR-008**: L5 MUST run the module's tests on the target version and, when a source-version runtime is available, on the source version, and compare per-test outcomes. Traces: REQ-VAL-005, REQ-BIZ-002
- **FR-009**: Every report MUST include a verification-scope section listing layers run, unavailable, skipped, and the stated limits of behavioural verification. Traces: REQ-BIZ-003
- **FR-010**: When the RNG adapter is available, modified view archs MUST be validated against the target version's RNG schemas from the knowledge base. Otherwise the check reports UNAVAILABLE. Traces: REQ-XML-004
- **FR-011**: Customer code MUST NOT be imported or executed by the tool process; execution happens only inside the runtime environment. Traces: REQ-SEC-001
- **FR-012**: Runtime adapters MUST implement the `RuntimeEnvironment` contract ([contracts/runtime-environment.md](contracts/runtime-environment.md)), so that other backends can be added without core edits. Traces: REQ-VAL-004, REQ-ARC-002

### Key Entities

- **ValidationResult** (CONTRACTS.md) extended with `coverage` for L5 (see data-model).
- **RuntimeRun**: environment ID, image reference and digest, limits, timings, exit status, log path, classified errors.
- **TestComparison**: per-test outcome on source and target, classification (`pass_both`, `regression`, `fixed`, `fail_both`, `target_only`, `source_only`).
- **StatusDecision**: inputs digest, matched rule row, resulting status, reasons.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The status decision tests cover every row of the decision table, plus a combinatorial sweep of layer outcomes ({PASS, FAIL, UNAVAILABLE, SKIPPED}⁵ × finding flags); every case matches the reference implementation's expected table.
- **SC-002**: Runtime fixtures: the install fixture gives `INSTALL_VERIFIED`, the broken-view fixture gives `FAILED/view_validation`, the loop fixture gives `FAILED/timeout` within limit + teardown grace, and the ACL fixture gives `FAILED/access_rights`.
- **SC-003**: After every runtime test, zero containers, networks, or volumes labelled with the run ID remain.
- **SC-004**: The behavioural fixture reports exactly 1 regression, 1 pre-existing failure, and 1 pass-both.
- **SC-005**: No report produced in the test suite claims `VERIFIED_SUCCESS` without L5 = PASS with `coverage = full`.

## Assumptions

- D-03 default: Docker CLI as the first runtime backend (pending approval).
- D-02 default: `lxml` as the optional RNG adapter (pending approval).
- D-05: no Enterprise source access; Enterprise-dependent modules cannot be runtime-validated.
- Official image provenance is not yet researched (G-R-13, G-R-21). P7 must complete that research before the runtime adapter is enabled by default.

## Clarifications

### Session 2026-11-06

- Q: Is runtime validation mandatory? → A: No. L1–L3 are mandatory; L4/L5 are opt-in (`--validate runtime`, `--validate behavior`). `--require <layer>` makes a layer mandatory, and if that layer is unavailable the result is `BLOCKED`.
- Q: Are intermediate versions validated at runtime? → A: Only with `--validate-intermediate` (ADR-007).
- Q: What counts as L5 PASS? → A: At least one target test ran, there were no regressions against the baseline, and the baseline ran (`coverage = full`). Without a baseline, `coverage = partial`, which caps the status at `INSTALL_VERIFIED`.
