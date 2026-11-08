# Feature Specification: Hardening and Release Readiness

**Feature Branch**: `010-hardening-release`
**Created**: 2026-11-06
**Status**: Draft — planned, not implemented
**Input**: Roadmap phase P9: "Security, performance, reliability, scalability, and production acceptance."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Release gate with verified requirements (Priority: P1)

The maintainer decides whether a release can ship. Every requirement in the traceability matrix has passing verification evidence. Every advertised version path meets the support rule. The release checklist is signed off.

**Why this priority**: Principles IV, VI, and X. Without this gate, the earlier phases cannot be trusted together.

**Independent Test**: Run the RTM completeness check. It fails on any REQ without a passing test or a recorded verification.

**Acceptance Scenarios**:
1. **Given** a REQ with no mapped passing test or verification record, **When** the completeness check runs, **Then** it fails and names the REQ.
2. **Given** a version path whose steps are not all `RULES_TESTED` or whose target is not `RUNTIME_VALIDATED`, **When** the support statement is generated, **Then** that path is listed as unsupported or experimental, never supported.
3. **Given** a resolved finding `F-…` without a regression test citing it, **When** the check runs, **Then** it fails (REQ-TST-005).

---

### User Story 2 - Performance at scale (Priority: P1)

A partner with 300 custom modules needs analysis to finish within a documented budget. A second run on unchanged input must be much faster, and parallel runs must produce the same report as serial runs.

**Why this priority**: OBJ-007 scale requirement.

**Independent Test**: Benchmark on the synthetic 300-module corpus: serial, parallel, and incremental runs. Compare reports and record wall time and peak RSS against budgets.

**Acceptance Scenarios**:
1. **Given** the P2 baseline, **When** the P9 benchmark runs, **Then** wall time and peak RSS are within the budgets set in [contracts/benchmark-protocol.md](contracts/benchmark-protocol.md), and a regression of more than 20 % fails CI.
2. **Given** an unchanged corpus, **When** re-run incrementally, **Then** zero files are re-parsed and the report is identical except for timing fields.
3. **Given** `--jobs N`, **When** run, **Then** the report is byte-identical to `--jobs 1`, excluding timing fields.

---

### User Story 3 - Auditability and secret safety (Priority: P2)

A security reviewer gets an audit log of every consequential action and can confirm that no secret appears in any artefact.

**Independent Test**: Run an integration scenario with write mode, AI (fake provider) and runtime (when enabled). Assert one audit entry per action type, and that a secret scan of all artefacts finds no canary secrets.

**Acceptance Scenarios**:
1. **Given** a write-mode run, **When** it finishes, **Then** the audit log has entries for config load, each file write, backup creation and verification, AI request metadata, and runtime launch and teardown.
2. **Given** canary secrets in the environment and config, **When** all artefacts are scanned, **Then** zero matches are found.
3. **Given** the deprecation window for `--api-key` has ended (D-10), **When** the option is used, **Then** the CLI rejects it with exit code 2 and does not echo the value.

---

### User Story 4 - Reliability under failure (Priority: P2)

Operators need the tool to survive crashes, full disks, and kills at any stage without corrupting customer files.

**Independent Test**: The failure-injection suite injects faults at every write, promotion, backup, checkpoint, and teardown step, then asserts that originals are intact or restorable via rollback.

**Acceptance Scenarios**:
1. **Given** a kill between backup verification and promotion, **When** the run is resumed or rolled back, **Then** every module is either fully promoted or byte-identical to the original.
2. **Given** a disk-full error during a write, **When** it occurs, **Then** the target file is unchanged and the module is `BLOCKED`.

### Edge Cases

- Benchmark machine variance → budgets are expressed relative to the recorded reference machine. CI uses the same runner class.
- A partially failed parallel worker → its modules are reported `BLOCKED` with the worker error; other modules are unaffected.
- Audit log location inside a scanned path → refused (REQ-SEC-003).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: An RTM completeness check MUST fail when any REQ lacks a passing mapped test or a recorded verification (RV/EV). Traces: REQ-TST-005, REQ-TST-002
- **FR-002**: Each resolved finding `F-…` MUST have a regression test whose name or docstring cites the ID. Traces: REQ-TST-005
- **FR-003**: Analysis of the 300-module synthetic corpus MUST meet the documented wall-time budget. Regressions over 20 % against the stored baseline MUST fail CI. Traces: REQ-PRF-001
- **FR-004**: Incremental mode MUST skip unchanged files using content hashes plus rule-set and tool-version digests. Traces: REQ-PRF-002
- **FR-005**: Parallel execution MUST produce reports identical to serial execution, excluding timing fields. Traces: REQ-PRF-003
- **FR-006**: Peak memory per worker MUST stay within the documented budget. Traces: REQ-PRF-004
- **FR-007**: An append-only audit log MUST record every consequential action ([contracts/audit-log.md](contracts/audit-log.md)). Traces: REQ-SEC-005
- **FR-008**: After the D-10 deprecation window, credentials passed as CLI arguments MUST be rejected. A secret scan of all artefacts MUST be part of the release gate. Traces: REQ-AI-008
- **FR-009**: The failure-injection suite MUST cover every write, promotion, backup, checkpoint, rollback, and teardown step. Traces: REQ-SAF-005, REQ-SAF-008, REQ-SAF-009
- **FR-010**: A generated support statement MUST list each version path as supported, experimental, or unsupported, derived from matrix data. Traces: REQ-VER-003, REQ-EVD-006

### Key Entities

- **BenchmarkResult**: corpus ID, machine profile, mode (serial/parallel/incremental), wall time, peak RSS, files parsed, report digest.
- **AuditEntry**: see contract.
- **ReleaseChecklist**: items, evidence links, sign-off.
- **SupportStatement**: path, status, reasons, evidence.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The RTM completeness check reports 0 unmapped REQs at release.
- **SC-002**: The 300-module benchmark meets its budgets; the incremental re-run re-parses 0 files; the parallel report digest equals the serial digest.
- **SC-003**: The secret scan finds 0 canary matches across all artefacts.
- **SC-004**: 100 % of failure-injection points leave originals intact or restorable.
- **SC-005**: The support statement lists no path as supported unless all of its steps are `RULES_TESTED` and its target is `RUNTIME_VALIDATED`.

## Assumptions

- Budgets are numbers derived from the P2 baseline and recorded in the benchmark protocol. None are assumed now.
- The reference machine is defined in P2 (CPU model, cores, RAM, storage type, OS, Python version).
- D-10: the `--api-key` deprecation window is one minor release.

## Clarifications

### Session 2026-11-06

- Q: How is the 300-module corpus built? → A: It is generated deterministically from golden-fixture templates by a seeded generator committed in `tests/benchmarks/`. No customer code is used.
- Q: Does P9 add new features? → A: No. It hardens, measures, and gates. Gaps found become new specs, not P9 scope creep (RSK on scope creep).
