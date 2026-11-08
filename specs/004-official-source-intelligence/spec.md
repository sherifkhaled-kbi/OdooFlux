# Feature Specification: Official Source Intelligence

**Feature Branch**: `004-official-source-intelligence`
**Created**: 2026-11-06
**Status**: Draft — planned, not implemented
**Phase**: P3 ([handoff](../../docs/planning/phase-handoffs/PHASE_03_OFFICIAL_SOURCES.md))
**Input**: User description: "Build the evidence registry, source research process, and version knowledge base so that every Odoo compatibility rule is backed by pinned official evidence, and the version compatibility matrix is generated from data."

## Clarifications

### Session 2026-11-06

- Q: Which sources count as evidence? → A: Only the allow-list in [OFFICIAL_SOURCES_STRATEGY.md](../../docs/planning/OFFICIAL_SOURCES_STRATEGY.md#approved-sources-allow-list); Enterprise only with authorised access (D-05 default: none).
- Q: Is a branch name an acceptable revision? → A: No. A 40-hex commit SHA or a catalogued tag is required.
- Q: When is evidence `VERIFIED`? → A: Only after a runtime test on the target version (Phase P7) confirms it; until then `DOCUMENTED_NOT_TESTED` (ADR-008).
- Q: How do Odoo Online releases (x.1–x.4) map? → A: To the next on-premise major (ADR-007).
- Q: Does this feature complete version research? → A: No. It delivers the knowledge base, validators, refresh workflow, generated matrix, and migrated seed (EV-001…EV-212). Per-step research completion is scheduled in feature 006.
- Q: Lowest source version to register? → A: 12.0 entries are registered; the first supported release target is decided by D-04 (default 14.0). The registry must not encode that decision as code.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Rules cannot exist without official evidence (Priority: P1)

A rule author adds a migration rule. Loading the knowledge base fails unless the rule cites at
least one evidence record. That record must use an allow-listed official URL, an immutable
revision, an exact location, and a valid status.

**Why this priority**: This is the core of Principle VI. Without it every later rule can be wrong.

**Independent Test**: Load a fixture knowledge base containing one valid and several invalid
rules or records. Loading reports exactly the invalid ones, with specific reasons.

**Acceptance Scenarios**:

1. **Given** a rule with no `evidence`, **When** the knowledge base loads, **Then** loading fails with `rule <id>: missing evidence`.
2. **Given** an evidence record citing `https://stackoverflow.com/...`, **When** validated, **Then** it is rejected with `url not in allow-list`.
3. **Given** a record with `revision: "17.0"`, **When** validated, **Then** it is rejected with `revision must be a commit SHA or catalogued tag`.
4. **Given** a rule whose evidence is `UNVERIFIED` and maturity `FIX_ENABLED`, **When** loaded, **Then** its maturity is capped to `DETECT_ONLY` and a warning is reported.

---

### User Story 2 - Version registry describes every known version as data (Priority: P1)

The engine reads the list of Odoo versions, their Python ranges, Online releases, research status,
and support status from data. Adding version 20.0 requires only a data entry.

**Why this priority**: The planner (P2) and every rule (P5) depend on it. REQ-ARC-003 forbids
hardcoded maxima.

**Independent Test**: Registry data for 12.0–19.0 loads and validates. A test fixture adding
20.0 loads without code changes.

**Acceptance Scenarios**:

1. **Given** the shipped registry, **When** loaded, **Then** it lists 12.0–19.0 in order, each with `research_status` and `support_status`.
2. **Given** a fixture adding `20.0` with `NOT_ASSESSED`, **When** loaded, **Then** it appears in the graph and every path into it is reported as blocked.
3. **Given** two entries with the same major, **When** loaded, **Then** loading fails.

---

### User Story 3 - Seed evidence is migrated and gaps are first-class data (Priority: P2)

Maintainers see every planning-phase evidence record (EV-001…EV-015, EV-101…EV-125,
EV-201…EV-212) and every gap (G-R-01…G-R-19) as validated knowledge-base data.

**Why this priority**: It preserves planning research and makes gaps visible to the planner and
the matrix.

**Independent Test**: Count of migrated records equals the count in the planning register plus
feature research. Each record passes validation.

**Acceptance Scenarios**:

1. **Given** the migrated data, **When** validated, **Then** all records pass, with status `DOCUMENTED_NOT_TESTED` (or `NOT_APPLICABLE` where marked).
2. **Given** a gap record, **When** the matrix is generated, **Then** the affected step/category cell is not higher than `RESEARCH_SEEDED`.

---

### User Story 4 - Refresh evidence against new revisions (Priority: P2)

When Odoo publishes new commits or a new major version, a maintainer runs the refresh workflow
and gets a report for each record: unchanged, moved (new line), or missing. Missing records
demote dependent rules.

**Why this priority**: Evidence decays as branches move. REQ-EVD-005.

**Independent Test**: Run refresh against two fixture git repositories (old and new SHA), where
one record moved and one disappeared. The report classifies both correctly, and the dependent
rule is capped.

**Acceptance Scenarios**:

1. **Given** a record whose matched text moved 12 lines, **When** refreshed, **Then** it is reported `moved` with the new line and a proposed update.
2. **Given** a record whose matched text is gone, **When** refreshed, **Then** it is reported `missing` and set `CONFLICTING`, and its rules are capped at `DETECT_ONLY`.
3. **Given** no local clone for a revision, **When** refreshed, **Then** the record is reported `unavailable`, not `missing`.

---

### User Story 5 - Compatibility matrix generated from data (Priority: P3)

The published matrix is regenerated deterministically from registry, research, gaps, and rule
data, so it can never claim more than the data supports.

**Why this priority**: Honest reporting (Principle IV), REQ-EVD-006.

**Independent Test**: Generate twice; the outputs are byte-identical. Hand-editing the
committed file makes the check fail.

**Acceptance Scenarios**:

1. **Given** the shipped data, **When** the matrix is generated, **Then** no cell exceeds `RESEARCH_SEEDED` (planning reality).
2. **Given** a rule marked `RULES_TESTED` without test evidence, **When** generated, **Then** the generator refuses, citing the rule.

### Edge Cases

- Evidence record citing a deleted file at the new SHA (path renamed, e.g. `odoo/models.py` → `odoo/orm/models.py` in 19.0): refresh reports `missing` and proposes candidate paths found by searching for the match text.
- An absence claim ("ABSENT at 18.0"): verified by confirming the match text is not found in the stated path **and** not found repository-wide under the declared search scope.
- Duplicate evidence IDs, or two records with identical claim and location: rejected (duplicates) or warned (identical).
- A record whose `target_applicability` spans an Online release: normalised to the next major with a note.
- Non-UTF-8 source files at a revision: read as bytes, decoded with `errors="replace"`, location still checked.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST validate every evidence record against the evidence schema (all fields in [data-model.md](data-model.md#evidencerecord)) and reject unknown status values. Traces: REQ-EVD-002.
- **FR-002**: The system MUST reject evidence URLs outside the allow-list and revisions that are not a 40-hex SHA or a catalogued tag. Traces: REQ-EVD-004.
- **FR-003**: The system MUST fail loading when any rule lacks a valid evidence reference, except shared hygiene rules (`step: "*"`) whose evidence is an explicit `NOT_APPLICABLE` justification. Traces: REQ-EVD-001.
- **FR-004**: The system MUST cap rules with only `UNVERIFIED` or `CONFLICTING` evidence at `DETECT_ONLY`, and report the cap. Traces: REQ-EVD-003.
- **FR-005**: The system MUST load the version registry from data, validate ordering and uniqueness, and expose research and support status per version and per step. Traces: REQ-VER-001, REQ-ARC-003.
- **FR-006**: The shipped data MUST contain registry entries 12.0–19.0, the migrated seed evidence (EV-001…EV-015, EV-101…EV-125, EV-201…EV-212), and gaps G-R-01…G-R-19. Traces: REQ-VER-001, REQ-EVD-002.
- **FR-007**: The system MUST provide a refresh command that classifies each record as `unchanged`, `moved`, `missing`, or `unavailable` against given revisions, writes a report, and, only with `--apply`, updates locations and demotes missing records to `CONFLICTING`. Traces: REQ-EVD-005.
- **FR-008**: The system MUST generate the Version Compatibility Matrix deterministically from data and provide a check mode that fails when the committed matrix differs. Traces: REQ-EVD-006.
- **FR-009**: The matrix generator MUST NOT report any cell above the level proven by data (e.g., `RULES_TESTED` requires recorded passing tests for every rule in that cell). Traces: REQ-EVD-006, REQ-EVD-003.
- **FR-010**: The system MUST document the research procedure and refresh procedure for implementers, including the new-version procedure. Traces: REQ-EVD-005, REQ-VER-005.

### Key Entities

- **EvidenceRecord**: one official claim at a pinned location (fields in [data-model.md](data-model.md#evidencerecord)).
- **OdooVersion**: a registry entry (contract in [CONTRACTS.md](../../docs/planning/architecture/CONTRACTS.md#odooversion)).
- **StepResearchRecord**: per-step, per-category research coverage and gaps.
- **RevisionCatalogue**: pinned SHAs/tags per repository and branch.
- **ResearchGap**: a known unknown, linked to steps, categories, and blocked rules.
- **RuleMetadata**: rule fields from the Rule contract, minus code.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % of shipped evidence records pass schema, allow-list, and revision validation (count reported by the validator equals the number of record files).
- **SC-002**: Every seed record in the planning register and in [research.md](research.md) exists as data (zero missing IDs in a reconciliation test).
- **SC-003**: A synthetic version 20.0 can be added with zero changes to non-data files (verified by a test that loads a fixture registry).
- **SC-004**: Refresh classifies 4/4 fixture cases correctly (unchanged, moved, missing, unavailable).
- **SC-005**: Two matrix generations are byte-identical, and the committed matrix check passes in CI.
- **SC-006**: Validation of the full knowledge base completes in under 5 seconds on the reference machine.

## Assumptions

- Phase P2 has delivered the package layout, contracts (`OdooVersion`, `Rule`), and the rule-registry loader skeleton under `src/odooflux/`.
- Local git and network access are available to maintainers running the refresh workflow; tests use local fixture repositories only.
- Enterprise evidence is out of scope unless D-05 changes.
- The JSON schema vocabulary is documentation; validation code is stdlib.
