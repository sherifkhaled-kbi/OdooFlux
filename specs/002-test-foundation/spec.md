# Feature Specification: Test Foundation (Phase P1)

**Feature Branch**: `002-test-foundation`

**Created**: 2026-11-06

**Status**: Draft — planned, not implemented

**Input**: Roadmap phase P1 ([IMPLEMENTATION_ROADMAP.md](../../docs/planning/IMPLEMENTATION_ROADMAP.md#p1--test-foundation)):
a reliable, offline test foundation that pins current behaviour before the P2 refactor.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One command runs the whole offline suite (Priority: P1)

A contributor clones the repository and runs one documented command. All non-runtime tests run
offline with the standard library and report pass/fail.

**Why this priority**: Without a runnable suite no later phase can prove its exit criteria
(Principle V, X).

**Independent Test**: On a machine with no network and no Docker, `python -m unittest discover -s tests`
exits 0.

**Acceptance Scenarios**:

1. **Given** a fresh clone with Python ≥3.10, **When** the contributor runs the command, **Then** all
   default suites run and the exit code is 0.
2. **Given** network access disabled, **When** the suite runs, **Then** no test fails or hangs for lack
   of network.

---

### User Story 2 - Current behaviour is pinned by characterisation tests (Priority: P1)

A maintainer about to refactor (P2) has tests that pin what the legacy CLI outputs today: issues,
categories, severities, exit codes, JSON shape, and fixed files.

**Why this priority**: The P2 cut-over must prove parity or document every difference (REQ-ARC-004).

**Independent Test**: Run the characterisation suite against the P0-patched `odooflux.py`; it
passes. Deliberately changing one rule message makes it fail with a readable diff.

**Acceptance Scenarios**:

1. **Given** the golden fixtures, **When** the legacy CLI runs in analyze mode with `--report`, **Then**
   the normalised JSON equals the stored expected report.
2. **Given** the golden fixtures, **When** the legacy CLI runs with `--fix` on a copy, **Then** the
   resulting tree equals the stored expected tree byte for byte.
3. **Given** an intended behaviour change, **When** the maintainer runs the documented update
   command, **Then** the expected files are regenerated and the diff is reviewable in version control.

---

### User Story 3 - Golden fixtures per source version (Priority: P2)

A rule author finds a small, realistic fixture module for each source version 12.0–18.0 with
input, expected fix output, and expected report.

**Why this priority**: P5 rules need per-version fixtures (REQ-TST-003).

**Independent Test**: The fixture index lists seven fixtures (12.0…18.0). Each has `input/`,
`expected/<target>/`, and `expected_report.json`. A validity check confirms every input `.py`
parses and every `.xml` is well-formed.

**Acceptance Scenarios**:

1. **Given** the fixture index, **When** the fixture-validity test runs, **Then** every fixture has the
   required layout and parseable inputs.
2. **Given** a fixture for source X, **When** its manifest version is read, **Then** it starts with `X.`.

---

### User Story 4 - Regression and opt-in suites (Priority: P3)

Every resolved audit finding has a regression test that names its ID. Suites that need Docker,
network, or AI providers run only when explicitly enabled.

**Why this priority**: Prevents re-introducing defects (REQ-TST-005). Keeps the default suite
offline (REQ-TST-006).

**Independent Test**: The default run skips runtime and AI suites with a visible skip reason.
Setting `ODOOFLUX_RUNTIME_TESTS=1` attempts them.

**Acceptance Scenarios**:

1. **Given** no environment flags, **When** tests run, **Then** runtime and AI tests are reported as
   skipped with the flag name in the reason.
2. **Given** the finding list, **When** the regression-index test runs, **Then** each finding marked
   resolved in the regression index has at least one test citing its ID.

### Edge Cases

- Absolute paths and timestamps in reports: normalised before comparison (stored as `<MODULE>`
  and `<TS>`).
- Platform line endings: fixtures are stored with LF. Comparison is byte-exact; Windows checkouts
  are protected by `.gitattributes` (`* -text` for fixtures).
- Colour codes: characterisation runs use `--no-color`.
- Fixture for 12.0 contains Python 3.5-era syntax: must parse on Python ≥3.10 (REQ-PY-004 preview).
- An expected-output update run on a dirty tree: the update script refuses unless `--force`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST provide a `unittest` suite discoverable with
  `python -m unittest discover -s tests` that runs offline using only the standard library.
  Traces: REQ-TST-001
- **FR-002**: A shared harness MUST provide fixture copying into temp dirs, tree digests, CLI
  invocation with captured exit codes, report normalisation, and opt-in skip decorators.
  Traces: REQ-TST-001, REQ-TST-006
- **FR-003**: Golden fixtures MUST exist for source versions 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, and
  18.0. Each has `input/`, `expected/<target>/` for target 18 and 19 where the pair is valid, and
  `expected_report.<target>.json`.
  Traces: REQ-TST-003
- **FR-004**: Each fixture MUST contain constructs relevant to its version. It MAY only use
  constructs whose existence in that version is backed by an `EV-…` record or is generic Python/XML.
  The fixture README lists the EV IDs used.
  Traces: REQ-TST-003
- **FR-005**: A characterisation suite MUST compare legacy CLI outputs (normalised JSON report,
  stdout summary lines, exit code, fixed tree) with stored expectations for every fixture and
  target.
  Traces: REQ-TST-004
- **FR-006**: An expectation-update script MUST regenerate expected outputs deterministically and
  print a summary of changed files.
  Traces: REQ-TST-004
- **FR-007**: A rule-test coverage check MUST enumerate legacy rule categories and report which lack
  positive, negative, and idempotence tests. In P1 it reports gaps without failing, because legacy
  rules are retired in P5. P5 switches it to failing mode.
  Traces: REQ-TST-002
- **FR-008**: A regression index (`tests/regression/INDEX.md`) MUST map each resolved finding ID to
  its tests, and a test MUST verify the index against test docstrings.
  Traces: REQ-TST-005
- **FR-009**: Suites needing Docker, network, or AI MUST be gated by `ODOOFLUX_RUNTIME_TESTS=1`,
  `ODOOFLUX_NETWORK_TESTS=1`, or `ODOOFLUX_AI_TESTS=1` and skipped otherwise.
  Traces: REQ-TST-006
- **FR-010**: The P0 tests under `tests/regression/` MUST be migrated onto the shared harness
  without changing what they assert.
  Traces: REQ-TST-001, REQ-TST-005
- **FR-011**: Test conventions (naming, IDs, fixture layout, how to add a regression test) MUST be
  documented in `tests/README.md`.
  Traces: REQ-TST-001

### Key Entities

- **Golden fixture**: source version, input tree, expected outputs per target, expected report,
  evidence IDs used.
- **Characterisation case**: fixture × target × mode (analyze/fix) → expected artefacts.
- **Regression index entry**: finding ID → test IDs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The default suite completes offline in under 120 seconds on a developer laptop.
- **SC-002**: 7 golden fixtures (12.0–18.0) exist, all inputs parse, all layouts are valid.
- **SC-003**: Characterisation covers 7 fixtures × 2 modes × valid targets, and every case passes on
  the P0-patched script.
- **SC-004**: 100 % of findings marked resolved in P0 appear in the regression index with at least
  one test (count-based, verified by test).
- **SC-005**: With no flags set, 0 runtime/AI tests execute; with a flag set, they execute.

## Assumptions

- P1 starts after P0 is done; it characterises the **P0-patched** behaviour, not the original
  defects.
- Fixtures are small, synthetic, and authored for testing. No customer code is used.
- Odoo itself is not needed for P1 tests. Runtime suites are only scaffolded (skip markers) and
  are filled in P7.
- D-04 (lowest source for the first release, default 14.0) does not limit fixtures: 12.0 and 13.0
  fixtures are created for test coverage even if not released as supported.

## Clarifications

### Session 2026-11-06

- Q: pytest or unittest? → A: `unittest` (ADR-016); pytest may be used as a runner only.
- Q: Which targets get expected outputs? → A: 18 and 19 for every source below the target (the legacy
  CLI accepts only `--to-version 18|19`).
- Q: Are 12.0/13.0 fixtures in scope despite weak documentation (G-R-01)? → A: Yes. They only use
  constructs with EV records (EV-101, EV-103, EV-110, EV-124, EV-125) or generic syntax.
- Q: Should the coverage check fail in P1? → A: No. It reports only, until P5 replaces the legacy
  rules.
- Q: Where do runtime test skeletons live? → A: `tests/runtime/` with a skip-unless-flag base class;
  the content comes in P7.
