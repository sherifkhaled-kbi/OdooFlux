# Feature Specification: Reporting and UX

**Feature Branch**: `009-reporting-ux`
**Created**: 2026-11-06
**Status**: Draft — planned, not implemented
**Input**: Roadmap phase P8: "Implement CLI and report generation improvements."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Actionable terminal output (Priority: P1)

A developer running OdooFlux in a terminal sees progress by stage, a per-module status with reasons, per-file findings with evidence links, rejected edits with reasons, what was and was not verified, and the exact command to roll back.

**Why this priority**: The terminal is the primary interface. Over-claiming success is the legacy tool's most harmful UX defect (F-REP-1).

**Independent Test**: Render golden report models in colour and plain modes. Compare them with snapshot files.

**Acceptance Scenarios**:
1. **Given** a run with fixed, open, and rejected findings, **When** rendered, **Then** the fixed, open, and rejected counts equal the counts in the report model, and each rejected edit shows its reason.
2. **Given** `NO_COLOR` set or `--no-color`, **When** rendered, **Then** output contains no ANSI escape sequences and column alignment is preserved.
3. **Given** a module with status `STATIC_VALIDATED`, **When** rendered, **Then** the verification-scope block states that installation and behaviour were not verified.

---

### User Story 2 - Machine-readable exports for CI (Priority: P1)

A CI pipeline consumes a JSON report validated against a published schema, uploads SARIF to a code-scanning UI, and fails the build according to `--fail-on`.

**Why this priority**: Automation (OBJ-006) and the exit-code defects (F-VER-4, F-REP-3).

**Independent Test**: Validate the JSON output against `report.schema.json` and the SARIF output against SARIF 2.1.0. Run the exit-code table test.

**Acceptance Scenarios**:
1. **Given** any golden run, **When** exported, **Then** the JSON validates against schema version 1 and SARIF validates against SARIF 2.1.0.
2. **Given** `--fail-on warning` and an open WARNING, **When** the run ends, **Then** the exit code is 1.
3. **Given** a module `BLOCKED`, **When** the run ends, **Then** the exit code is 4 regardless of `--fail-on`.

---

### User Story 3 - Reviewable changes (Priority: P2)

A reviewer reads a unified diff of all kept edits, grouped by file, with each hunk annotated by the rule ID in an accompanying index.

**Independent Test**: Apply the exported diff with `patch -p1` to a copy of the original fixture. The result must be byte-identical to the promoted output.

**Acceptance Scenarios**:
1. **Given** a dry-run, **When** `--diff out.patch` is given, **Then** the patch applies cleanly to the untouched originals.

---

### User Story 4 - Offline HTML report (Priority: P2)

A team lead opens a single HTML file offline and navigates the run summary, modules, files, findings with evidence links, validation layers, AI usage, and recovery instructions.

**Independent Test**: Render a golden model. Assert that the HTML has no external URLs in `src`/`href`/CSS (evidence links are plain `<a>` to official URLs only) and that it contains every schema section.

**Acceptance Scenarios**:
1. **Given** a golden model, **When** rendered to HTML, **Then** the file loads no scripts, styles, or fonts from the network and contains every section listed in [contracts/report-schema-v1.md](contracts/report-schema-v1.md).

### Edge Cases

- Thousands of findings → terminal shows a capped list per file (configurable) with a pointer to the full JSON/HTML. Totals stay exact.
- Non-UTF-8 file content in findings → excerpts escaped. HTML escaping is mandatory (excerpts are untrusted).
- Narrow terminals (<80 columns) → wrap without breaking alignment markers. Tested at 60 and 120 columns.
- Report written to a path inside a scanned module → refused (REQ-SEC-003).
- Legacy JSON consumers → `--report-format legacy-json` is kept for one minor release (D-10).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All outputs MUST be rendered from the versioned report model ([contracts/report-schema-v1.md](contracts/report-schema-v1.md)); renderers MUST NOT compute results. Traces: REQ-REP-001
- **FR-002**: The JSON export MUST validate against the published JSON schema for its `schema_version`. Traces: REQ-REP-001
- **FR-003**: The terminal renderer MUST show stage progress, per-module status with reasons, per-file findings, and actionable guidance, in colour and plain modes. Traces: REQ-REP-002
- **FR-004**: A self-contained static HTML report MUST be produced with no network-loaded resources. Traces: REQ-REP-003
- **FR-005**: SARIF 2.1.0 and unified-diff exports MUST be available ([contracts/sarif-and-diff.md](contracts/sarif-and-diff.md)). Traces: REQ-REP-004
- **FR-006**: Exit codes MUST follow the documented table, and `--fail-on` MUST be configurable. Traces: REQ-REP-005
- **FR-007**: Reports MUST include evidence links, rejected edits, per-layer validation results, verification scope and limits, AI usage, durations, and recovery instructions. Traces: REQ-REP-006, REQ-BIZ-003
- **FR-008**: Untrusted text (code excerpts, messages from logs or AI) MUST be escaped in every renderer. Traces: REQ-REP-003, REQ-SEC-004
- **FR-009**: Report files MUST NOT be written inside scanned module paths. Traces: REQ-SEC-003

### Key Entities

- **ReportModel v1**: see contract.
- **RendererOptions**: colour, width, max findings per file, locale-independent number formatting.
- **ExitPolicy**: `fail_on` threshold and fixed overrides.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % of golden runs produce JSON that validates against schema v1 and SARIF that validates against SARIF 2.1.0.
- **SC-002**: Counts shown in terminal, HTML, JSON, and SARIF are identical for every golden run (cross-renderer consistency test).
- **SC-003**: The exported diff reproduces the promoted output byte-for-byte on every golden fixture.
- **SC-004**: The HTML report contains zero external resource references (scripted check).
- **SC-005**: The exit-code test covers every row of the exit table and every `--fail-on` value.

## Assumptions

- D-06 default: static HTML built with stdlib templates, inline CSS, no JavaScript dependency.
- D-07 default: optional `rich` adapter. The default renderer is stdlib ANSI.
- D-10 default: legacy JSON format and legacy exit-code mapping are kept for one minor release with a deprecation notice.

## Clarifications

### Session 2026-11-06

- Q: What are the exit codes? → A: 0 OK; 1 threshold exceeded (findings at or above `--fail-on`, or module status `FAILED`/`NEEDS_REVIEW` when `--fail-on` includes statuses); 2 usage/config error; 3 rejected edits in write mode; 4 `BLOCKED` or internal tool error. Precedence when several apply: 4 > 3 > 1 > 0.
- Q: What is the default `--fail-on`? → A: `critical` (any open CRITICAL or any `FAILED` module). `--fail-on none` disables code 1.
- Q: Is the HTML interactive? → A: Static. Collapsible sections use native `<details>` elements; no scripts.
