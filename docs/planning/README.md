# OdooFlux Planning Package

This directory is the planning and architecture package for turning OdooFlux into a
multi-version Odoo module migration tool. It is **planning only**: no functional code has been
written. Implementation is done phase by phase by independent agents, starting from
[IMPLEMENTATION_AGENT_GUIDE.md](IMPLEMENTATION_AGENT_GUIDE.md).

## Reading order

1. [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md): what, why, current state, decisions pending
2. [CURRENT_ARCHITECTURE_AUDIT.md](CURRENT_ARCHITECTURE_AUDIT.md): what the code does today
3. [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md): all requirements (REQ IDs)
4. [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) and [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md)
5. [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md): phases, dependencies, entry/exit criteria
6. [SPECKIT_READINESS.md](SPECKIT_READINESS.md): per-phase readiness dashboard
7. The phase handoff for the phase you are implementing, in [phase-handoffs/](phase-handoffs/)

## Document index

| Document | Purpose |
|---|---|
| [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) | One-page overview |
| [CURRENT_ARCHITECTURE_AUDIT.md](CURRENT_ARCHITECTURE_AUDIT.md) | Classified findings on the current code |
| [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md) | Requirements with acceptance criteria |
| [OFFICIAL_SOURCES_STRATEGY.md](OFFICIAL_SOURCES_STRATEGY.md) | Evidence policy, research workflow, refresh process |
| [research/OFFICIAL_EVIDENCE_REGISTER.md](research/OFFICIAL_EVIDENCE_REGISTER.md) | Evidence collected during planning (pinned SHAs) |
| [VERSION_COMPATIBILITY_MATRIX.md](VERSION_COMPATIBILITY_MATRIX.md) | Research and coverage status per transition |
| [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) | Target system design |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | Directory responsibilities and scaffold inventory |
| [MIGRATION_MAP.md](MIGRATION_MAP.md) | Current code → target components |
| [MIGRATION_RULE_ENGINE.md](MIGRATION_RULE_ENGINE.md) | Version graph, rule registry, planner, executor |
| [AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md](AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md) | Provider-neutral AI subsystem |
| [VALIDATION_AND_TEST_STRATEGY.md](VALIDATION_AND_TEST_STRATEGY.md) | Validation layers, result statuses, test strategy |
| [SECURITY_AND_SAFETY.md](SECURITY_AND_SAFETY.md) | Safety, recovery, sandboxing, secrets |
| [REPORTING_AND_UX.md](REPORTING_AND_UX.md) | Report schema, terminal/HTML/JSON/SARIF, mockups |
| [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) | Ordered phases and dependency graph |
| [REQUIREMENTS_TRACEABILITY_MATRIX.md](REQUIREMENTS_TRACEABILITY_MATRIX.md) | REQ → spec → phase → tasks → tests |
| [RISK_REGISTER.md](RISK_REGISTER.md) | Risks, mitigations, owners |
| [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) | ADRs |
| [PLANNING_GAPS_AND_ASSUMPTIONS.md](PLANNING_GAPS_AND_ASSUMPTIONS.md) | Open decisions (D-xx), research gaps, assumptions |
| [SPECKIT_READINESS.md](SPECKIT_READINESS.md) | Spec Kit readiness dashboard |
| [SPECKIT_ANALYSIS_REPORT.md](SPECKIT_ANALYSIS_REPORT.md) | Cross-artifact analysis results |
| [IMPLEMENTATION_AGENT_GUIDE.md](IMPLEMENTATION_AGENT_GUIDE.md) | Entry point for implementation agents |
| [architecture/](architecture/) | Diagrams and interface contracts |
| [phase-handoffs/](phase-handoffs/) | One self-contained handoff per phase |

## Phase ↔ Spec Kit feature mapping

| Phase | Title | Spec Kit feature | Handoff |
|---|---|---|---|
| P0 | Safety Stabilization | [specs/001-safety-stabilization](../../specs/001-safety-stabilization/) | [PHASE_00_SAFETY.md](phase-handoffs/PHASE_00_SAFETY.md) |
| P1 | Test Foundation | [specs/002-test-foundation](../../specs/002-test-foundation/) | [PHASE_01_TESTING.md](phase-handoffs/PHASE_01_TESTING.md) |
| P2 | Core Architecture | [specs/003-core-architecture](../../specs/003-core-architecture/) | [PHASE_02_ARCHITECTURE.md](phase-handoffs/PHASE_02_ARCHITECTURE.md) |
| P3 | Official Source Intelligence | [specs/004-official-source-intelligence](../../specs/004-official-source-intelligence/) | [PHASE_03_OFFICIAL_SOURCES.md](phase-handoffs/PHASE_03_OFFICIAL_SOURCES.md) |
| P4 | Structured Transformations | [specs/005-structured-transformations](../../specs/005-structured-transformations/) | [PHASE_04_TRANSFORMATIONS.md](phase-handoffs/PHASE_04_TRANSFORMATIONS.md) |
| P5 | Version Compatibility Rules | [specs/006-version-compatibility-rules](../../specs/006-version-compatibility-rules/) | [PHASE_05_VERSION_COMPATIBILITY.md](phase-handoffs/PHASE_05_VERSION_COMPATIBILITY.md) |
| P6 | AI Assistance | [specs/007-ai-assistance](../../specs/007-ai-assistance/) | [PHASE_06_AI.md](phase-handoffs/PHASE_06_AI.md) |
| P7 | Runtime and Behavioral Validation | [specs/008-runtime-behavioral-validation](../../specs/008-runtime-behavioral-validation/) | [PHASE_07_VALIDATION.md](phase-handoffs/PHASE_07_VALIDATION.md) |
| P8 | Reporting and UX | [specs/009-reporting-ux](../../specs/009-reporting-ux/) | [PHASE_08_REPORTING.md](phase-handoffs/PHASE_08_REPORTING.md) |
| P9 | Hardening and Release Readiness | [specs/010-hardening-release](../../specs/010-hardening-release/) | [PHASE_09_HARDENING.md](phase-handoffs/PHASE_09_HARDENING.md) |

## Conventions (binding for all planning artifacts)

### Identifiers

| ID | Format | Example | Defined in |
|---|---|---|---|
| Product objective | `OBJ-NNN` | `OBJ-008` | [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md) |
| Product requirement | `REQ-<AREA>-NNN` | `REQ-SAF-003` | [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md) |
| Feature requirement | `FR-NNN` (local to a spec) | `FR-004` | each `spec.md`; each FR lists `Traces: REQ-…` |
| Success criterion | `SC-NNN` (local to a spec) | `SC-002` | each `spec.md` |
| Task | `T###` local; global form `<feature>:T###` | `001:T007` | each `tasks.md` |
| Test | `TST-<feature>-NNN` | `TST-001-004` | each `tasks.md` (task that creates the test) |
| Finding (current code) | `F-<AREA>-N` | `F-XML-1` | [../reviews/ODOO_MODULE_UPGRADER_AUDIT.md](../reviews/ODOO_MODULE_UPGRADER_AUDIT.md) |
| Evidence record | `EV-NNN` | `EV-012` | [research/OFFICIAL_EVIDENCE_REGISTER.md](research/OFFICIAL_EVIDENCE_REGISTER.md) |
| Migration rule | `<step>.<area>.<slug>` | `16-17.xml.attrs-removed` | knowledge base (Phase 3/5) |
| Decision pending approval | `D-NN` | `D-03` | [PLANNING_GAPS_AND_ASSUMPTIONS.md](PLANNING_GAPS_AND_ASSUMPTIONS.md) |
| ADR | `ADR-NNN` | `ADR-001` | [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) |
| Risk | `RSK-NNN` | `RSK-004` | [RISK_REGISTER.md](RISK_REGISTER.md) |

Every task line in a `tasks.md` MUST contain at least one `REQ-…` reference. A task that creates
a test MUST also contain its `TST-…` ID. The traceability matrix is compiled from these tags.

### Status vocabularies

| Vocabulary | Values | Meaning |
|---|---|---|
| Evidence status (claim) | `VERIFIED`, `DOCUMENTED_NOT_TESTED`, `UNVERIFIED`, `CONFLICTING`, `NOT_APPLICABLE` | See [OFFICIAL_SOURCES_STRATEGY.md](OFFICIAL_SOURCES_STRATEGY.md#evidence-statuses) |
| Rule maturity | `DRAFT`, `DETECT_ONLY`, `FIX_ENABLED`, `RETIRED` | See [MIGRATION_RULE_ENGINE.md](MIGRATION_RULE_ENGINE.md) |
| Result status (module) | `VERIFIED_SUCCESS`, `INSTALL_VERIFIED`, `STATIC_VALIDATED`, `NEEDS_REVIEW`, `FAILED`, `BLOCKED` | See [VALIDATION_AND_TEST_STRATEGY.md](VALIDATION_AND_TEST_STRATEGY.md#result-statuses) |
| Matrix coverage cell | `NOT_ASSESSED`, `RESEARCH_SEEDED`, `RESEARCHED`, `RULES_DRAFTED`, `RULES_TESTED`, `RUNTIME_VALIDATED` | See [VERSION_COMPATIBILITY_MATRIX.md](VERSION_COMPATIBILITY_MATRIX.md) |
| Readiness (phase) | `READY`, `READY_WITH_DEPENDENCIES`, `BLOCKED`, `INCOMPLETE` | See [SPECKIT_READINESS.md](SPECKIT_READINESS.md) |
| Audit classification | `CONFIRMED_CURRENT`, `PREVIOUSLY_REPORTED`, `ALREADY_RESOLVED`, `REQUIRES_RUNTIME_VERIFICATION`, `NEW_FINDING` | See [CURRENT_ARCHITECTURE_AUDIT.md](CURRENT_ARCHITECTURE_AUDIT.md) |

### Writing rules

- Requirements use MUST / MUST NOT / SHOULD (RFC 2119 sense) and are testable.
- No coverage percentages are invented; use `NOT_ASSESSED` when nothing was measured.
- Odoo-specific claims cite an `EV-…` record or are marked `UNVERIFIED`.
- Links are relative.
