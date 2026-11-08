# Feature Specification: Core Architecture (Phase P2)

**Feature Branch**: `003-core-architecture`

**Created**: 2026-11-06

**Status**: Draft — planned, not implemented

**Input**: Roadmap phase P2 ([IMPLEMENTATION_ROADMAP.md](../../docs/planning/IMPLEMENTATION_ROADMAP.md#p2--core-architecture)):
introduce the modular `src/odooflux` core (contracts, registries, version graph, planner,
workspace and recovery, report model) and cut over the legacy CLI without behaviour regressions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Same results through the new core (Priority: P1)

A developer keeps running `python odooflux.py …` with the same options. After cut-over the
command runs through the new core and produces the same reports, fixed files, and exit codes as
the P0/P1-pinned legacy behaviour, except for documented differences.

**Why this priority**: The refactor must not break users (REQ-ARC-004, Principle X).

**Independent Test**: The P1 characterisation suite passes against the cut-over entry point. Each
failing case is listed in the cut-over change record as an intended difference.

**Acceptance Scenarios**:

1. **Given** the P1 golden fixtures, **When** the characterisation suite runs after cut-over, **Then**
   all cases pass or match a documented difference.
2. **Given** the old option set (`--module`, `--modules`, `--addons-path`, `--from-version`,
   `--to-version`, `--fix`, `--backup`, `--dry-run`, `--report`, `--no-color`, `--skip`,
   `--show-fixed`, `--filter-severity`, `--fail-on`, `--state-dir`, `--ai-fix`), **When** used,
   **Then** each is accepted or rejected with a documented replacement message (D-10).

---

### User Story 2 - Any researched path is planned as explicit steps (Priority: P1)

A developer asks for 14.0 → 19.0 and sees the plan: the consecutive steps, the modules in
dependency order, and which steps are not yet researched. Unresearched steps block the run
unless `--allow-unverified` is given, which caps results at `NEEDS_REVIEW`.

**Why this priority**: This is the backbone of multi-version migration (OBJ-001; REQ-VER-002/003).

**Independent Test**: `odooflux plan --from 14.0 --to 19.0` on fixture data prints five steps. With
registry data marking 15-16 `NOT_ASSESSED`, the plan is `BLOCKED` and names that step.

**Acceptance Scenarios**:

1. **Given** registry versions 12.0–19.0, **When** any s<t pair is planned, **Then** the steps are
   exactly the consecutive pairs from s to t.
2. **Given** a step with research status `NOT_ASSESSED`, **When** planning without
   `--allow-unverified`, **Then** the plan status is `BLOCKED` and the step is named.
3. **Given** a registry entry for a synthetic `20.0` added as data only, **When** 19.0→20.0 is planned,
   **Then** one step is returned without any core code change.
4. **Given** modules A depends on B, **When** planning, **Then** B is processed before A; a cycle is
   reported as a finding and the cycle members are `BLOCKED`.

---

### User Story 3 - Recoverable runs (Priority: P1)

A developer's fix run works on a copy in the state directory. Originals change only at the end,
after validation. If the run is interrupted, it can be resumed; if the result is unwanted, it can
be rolled back to byte-identical originals.

**Why this priority**: OBJ-008; REQ-SAF-007/008/009.

**Independent Test**: Kill a multi-module fix run after module 1 is promoted; `odooflux resume
<run-id>` finishes with the same final report as an uninterrupted run. `odooflux rollback <run-id>`
restores every file listed in the run log to its pre-hash.

**Acceptance Scenarios**:

1. **Given** a fix run, **When** transforms and validation are in progress, **Then** the original
   module digest is unchanged.
2. **Given** a completed run, **When** rollback runs, **Then** every written file matches its
   `sha256_before`, and files created by the run are removed.
3. **Given** a run interrupted between modules, **When** resume runs, **Then** completed modules are
   not reprocessed and the final report equals an uninterrupted run (excluding timing fields).
4. **Given** a promotion failure on file k of n, **When** it happens, **Then** files 1..k-1 are
   restored automatically and the module is `FAILED` with the reason.

---

### User Story 4 - Plugins without touching the core (Priority: P2)

A contributor adds a rule, validator, parser, renderer, runtime, AI provider, or version by
registering it. The core is not edited. A plugin with the wrong contract version is rejected with
a clear message.

**Why this priority**: OBJ-007; REQ-ARC-002/006.

**Independent Test**: Contract tests register one sample plugin of each kind from `tests/contract/`
and run them; a sample with `contract_version = 99` is rejected.

**Acceptance Scenarios**:

1. **Given** a sample rule plugin, **When** registered, **Then** its findings appear in a run.
2. **Given** a plugin declaring an unsupported contract version, **When** loading, **Then** loading fails
   with an error naming the plugin and both versions, and the run continues without it.

---

### User Story 5 - One report model, deterministic output (Priority: P2)

A CI user receives a JSON report that validates against a published schema v1. It is identical
across runs on the same input and configuration, except for timing fields.

**Why this priority**: REQ-REP-001 (schema), REQ-ARC-005.

**Independent Test**: Run twice on a fixture; the normalised JSON is byte-identical and validates
against `report.schema.json`.

**Acceptance Scenarios**:

1. **Given** identical inputs, **When** run twice, **Then** reports are identical except
   `started_at`, `finished_at`, and `durations`.
2. **Given** the schema, **When** the report is validated, **Then** it passes, and status fields use only
   the six result statuses.

### Edge Cases

- Requested source version lower than any registry entry → `BLOCKED` with the supported range.
- Manifest version disagrees with `--from-version` → finding; the plan uses the explicit flag
  (REQ-VER-006).
- Module with no manifest inside an addons path → skipped with an INFO finding.
- State directory on another filesystem → promotion still uses a temp file in the target directory.
- Resume with a modified source module (hash differs from the run log) → refused; the user must
  start a new run.
- Rollback after the user edited a promoted file → that file is skipped with a conflict finding,
  not overwritten.
- Plugin raising an exception in `detect` → finding `RULE_ERROR`, run continues, module capped at
  `NEEDS_REVIEW`.
- Symlinks inside modules → not followed out of the module root.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Core packages (`core`, `discovery`, `versions`, `dependencies`, `reporting/model`,
  `utils`, `cli`, `validation/syntax`, `validation/static`, `rules/shared`) MUST import only the
  standard library and other OdooFlux core packages. Traces: REQ-ARC-001
- **FR-002**: Registries MUST exist for versions, rules, parsers, validators, runtime
  environments, AI providers, and renderers. They accept entries declaring `contract_version` and
  reject mismatches. Traces: REQ-ARC-002, REQ-ARC-006
- **FR-003**: No Odoo version literal may appear in engine code. Versions come only from registry
  data. Traces: REQ-ARC-003
- **FR-004**: The root `odooflux.py` MUST become a launcher delegating to `src/odooflux/cli`. The cut-over
  happens only when the characterisation suite passes or every difference is documented.
  Traces: REQ-ARC-004
- **FR-005**: Reports MUST be deterministic: sorted collections, stable IDs, and no environment-
  dependent fields other than timing. Traces: REQ-ARC-005
- **FR-006**: The Version Registry MUST load `OdooVersion` records (schema in
  [contracts](contracts/)) from `src/odooflux/knowledge/` data. P2 ships records for 12.0–19.0
  with `research_status` from the compatibility matrix. Traces: REQ-VER-001
- **FR-007**: The Version Graph MUST return consecutive steps for any s<t in the registry and
  report steps lacking research. Traces: REQ-VER-002, REQ-VER-003
- **FR-008**: The planner MUST refuse plans with unresearched steps (`BLOCKED`) unless
  `--allow-unverified`, which caps every module at `NEEDS_REVIEW`. Traces: REQ-VER-003
- **FR-009**: The engine MUST apply rules per step in dependency order and resolve or reject
  overlapping edits per [CONTRACTS.md](../../docs/planning/architecture/CONTRACTS.md#edit).
  Traces: REQ-VER-004, REQ-TRF-001
- **FR-010**: A documented procedure and test MUST show adding a version by data, rules, and
  fixtures only. Traces: REQ-VER-005
- **FR-011**: Discovery MUST detect the source version from the manifest (`ast.literal_eval`) and
  report mismatches with the requested source. Manifests are never renamed outside write mode.
  Traces: REQ-VER-006, REQ-MAN-001
- **FR-012**: Every run MUST transform an isolated workspace copy and promote validated files via
  backup → atomic replace → run-log entry. Traces: REQ-SAF-006, REQ-SAF-007
- **FR-013**: `rollback <run-id>` MUST restore pre-run bytes for every logged file and skip files
  changed after the run (conflict finding). Traces: REQ-SAF-008
- **FR-014**: Runs MUST checkpoint after each module, and `resume <run-id>` MUST complete
  interrupted runs with identical results. Traces: REQ-SAF-009
- **FR-015**: Layer-1 syntax validators (Python, XML, manifest) MUST be registry validators run
  before promotion. Layer-2 MUST re-scan the output against the target-step rules and attach the
  results. Traces: REQ-VAL-001, REQ-VAL-002
- **FR-016**: Fix status MUST be computed by the engine's re-scan diff (finding IDs present before,
  absent after). Traces: REQ-TRF-005
- **FR-017**: The report model v1 and its JSON schema MUST be published. Status values MUST follow
  the decision table in [VALIDATION_AND_TEST_STRATEGY.md](../../docs/planning/VALIDATION_AND_TEST_STRATEGY.md#result-statuses),
  implemented as a pure function with layer outcomes as input.
  Traces: REQ-REP-001, REQ-VAL-006
- **FR-018**: Multi-module runs MUST process modules in topological dependency order. Cycles are
  findings. Traces: REQ-DEP-002
- **FR-019**: The core MUST never import or execute customer code. A static test enforces no
  `exec`, `eval`, `importlib`, or `runpy` on scanned paths. Traces: REQ-SEC-001
- **FR-020**: A benchmark harness MUST record the baseline time and peak memory for a generated
  300-module repository. Traces: REQ-PRF-001
- **FR-021**: Legacy rules MUST be wrapped as rules under a legacy step adapter so that cut-over
  parity holds until P5 replaces them. Traces: REQ-ARC-004, REQ-TRF-001
- **FR-022**: `pyproject.toml` MUST declare the package, the console entry point `odooflux`, and
  optional extras (`js`, `rng`, `runtime`, `ai`, `rich`) with no packages in the core
  dependency list (D-09). Traces: REQ-ARC-001

### Key Entities

`OdooVersion`, `MigrationStep`, `MigrationPlan`, `ModuleRef`, `Rule`, `Document`, `Finding`, `Edit`,
`Validator`, `ValidationResult`, `RunState`, `RunLogEntry`, `Checkpoint`, `ReportModel`, `Plugin`.
See [data-model.md](data-model.md).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % of P1 characterisation cases pass after cut-over or are listed as intended
  differences (count of unexplained failures = 0).
- **SC-002**: Planning returns the correct consecutive steps for all 28 ordered pairs among 12.0–19.0.
- **SC-003**: Rollback restores byte-identical originals on 100 % of golden fixtures.
- **SC-004**: Resume after an interruption at each module boundary yields reports equal to an
  uninterrupted run on the multi-module fixture.
- **SC-005**: Two runs on every fixture produce identical normalised reports.
- **SC-006**: One sample plugin per registry kind (7 kinds) loads without core edits; a wrong
  contract version is rejected.
- **SC-007**: Baseline benchmark numbers (wall time, peak RSS) for 300 modules are recorded in
  `tests/benchmarks/BASELINE.md`.

## Assumptions

- D-01 (constitution 2.0.0) and D-09 (pyproject with optional extras) are approved before P2
  starts. Without D-09 the package is still runnable via the launcher, and the extras are deferred.
- D-10 default: all legacy options are kept. `--api-key` keeps working with a deprecation warning
  until P6/P9.
- Registry research statuses in P2 are copied from the planning matrix. P3 replaces them with
  validated knowledge-base data.
- Only legacy rules run after P2; new rules arrive in P5.
- Parallel execution is out of scope (P9). P2 runs modules sequentially but in dependency order.

## Clarifications

### Session 2026-11-06

- Q: Where do commands like `plan`, `rollback`, `resume` live? → A: Subcommands of the single
  entry point (`odooflux migrate|plan|rollback|resume`). Running without a subcommand keeps the
  legacy flag interface (= `migrate`).
- Q: How is parity with legacy rules preserved? → A: A legacy step adapter wraps the legacy rule
  tables and fixers as `Rule` objects under step `legacy-*`. They are retired in P5 (FR-021).
- Q: Does P2 introduce the Edit model for legacy fixers? → A: Yes, at file granularity. A legacy
  fixer's whole-file output is diffed into line-span Edits so that reporting and rollback use one
  model. Fine-grained spans come in P4.
- Q: Default for unresearched steps? → A: `BLOCKED`. `--allow-unverified` caps results at
  `NEEDS_REVIEW` (Principle VI).
- Q: Is the 300-module budget enforced in P2? → A: No. Baseline only; P9 sets and enforces it.
