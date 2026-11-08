<!--
Sync Impact Report
- Version change: 1.0.0 → 2.0.0 (MAJOR: Principle I redefined; Technical Constraints redefined)
- Modified principles:
  - I. "Single-File, Standard-Library-Only CLI" → "I. Dependency-Light Core, Isolated Adapters"
    (redefined: the core stays stdlib-only; optional third-party dependencies are allowed only
    inside declared adapters; the single-file rule is replaced by a single entry point)
  - II. "Safe by Default, Non-Destructive" → "II. Safe, Reversible, Non-Destructive" (expanded:
    immutable inputs, workspace copies, atomic promotion, backups outside the addons path)
  - III. "Deterministic Rules First, AI Second" → "III. Deterministic Rules First, Validated AI
    Second" (expanded: provider neutrality, token budgets, no AI-invented rules)
  - IV. "Transparent, Actionable Reporting" → "IV. Transparent, Honest Reporting" (expanded:
    finding-level fix attribution, verification limits, result statuses)
  - V. "Test-Backed Migration Rules" → "V. Test-Backed Rules and Acceptance Criteria" (expanded)
- Added principles: VI. Official Evidence Only; VII. Layered Validation Before Success Claims;
  VIII. Business Logic Preservation and Disclosed Limits; IX. Modular, Extensible Architecture;
  X. Phase-by-Phase Delivery and Independent Verification
- Added sections: none (Technical Constraints and Development Workflow rewritten)
- Removed content:
  - "OdooFlux MUST remain a single-file Python 3 CLI" (replaced by Principle I, single entry point)
  - "Target versions are Odoo 18 and 19" (replaced by the evidence-gated version support rule)
  - "Odoo conventions follow the odoo-dev skill" (removed: a skill is not official evidence;
    conflicts with Principle VI)
- Templates requiring updates: none (Spec Kit templates read this file at runtime)
- Follow-up TODOs:
  - TODO(APPROVAL): Maintainer approval of the 2.0.0 amendment is pending
    (see docs/planning/ARCHITECTURE_DECISIONS.md ADR-002 and docs/planning/PLANNING_GAPS_AND_ASSUMPTIONS.md D-01).
-->
# OdooFlux Constitution

## Core Principles

### I. Dependency-Light Core, Isolated Adapters
- The core engine (discovery, planning, rule execution, edit application, reporting model) MUST
  run on the Python standard library only.
- Optional third-party dependencies (JavaScript parsing, runtime containers, AI provider SDKs,
  rich terminal output) MAY be used only inside a declared adapter, MUST be declared as an
  optional extra, and MUST NOT be imported by core modules.
- When an optional adapter is unavailable, the tool MUST still run and MUST downgrade affected
  results to `NEEDS_REVIEW` instead of failing or claiming success.
- The product MUST keep a single documented command-line entry point. Network access from the
  core MUST use the standard library.

Rationale: zero-install analysis remains possible, while capabilities that the standard library
cannot provide (for example, a JavaScript parser) stay replaceable and optional.

### II. Safe, Reversible, Non-Destructive
- Customer inputs are immutable. Analysis and `--dry-run` MUST NOT create, modify, rename, or
  delete any file inside the scanned modules or addons paths.
- Transformations MUST run against a working copy. Changes are promoted to the target location
  only after validation passes, using atomic replacement.
- Backups MUST be written outside every scanned addons path, MUST be verified after creation,
  and a failed backup MUST abort the write for that module.
- Every write MUST be recorded in a run log sufficient to roll it back.

Rationale: the tool edits customer source code; an unrecoverable or silent change is the worst
possible failure.

### III. Deterministic Rules First, Validated AI Second
- Known migrations MUST be implemented as deterministic, evidence-backed rules.
- AI assistance is optional and opt-in. It MAY address only findings that no deterministic
  rule can safely fix, MUST NOT invent compatibility rules, and MUST pass the same validation
  as deterministic edits.
- The engine MUST be provider-neutral. Per-file, per-module, and per-job token budgets MUST be
  enforced and reported. Token savings MUST NOT reduce correctness.
- Credentials MUST NOT be logged, written to reports, sent to non-provider endpoints, or
  committed. Customer code sent to an AI provider MUST be minimised and disclosed.

Rationale: rule output is reproducible and reviewable; AI output is neither unless validated.

### IV. Transparent, Honest Reporting
- Every finding MUST carry rule ID, file, location, severity, message, suggested action,
  evidence reference, and fix status.
- A finding MAY be reported as fixed only if a re-scan of the written content no longer
  produces it. Rejected edits MUST be reported with the rejection reason.
- Results MUST use the defined statuses (`VERIFIED_SUCCESS`, `INSTALL_VERIFIED`,
  `STATIC_VALIDATED`, `NEEDS_REVIEW`, `FAILED`, `BLOCKED`). A status MUST NOT be claimed unless
  its conditions are met. Unverified behaviour MUST be disclosed.
- All presentation formats MUST render the same underlying report data.

Rationale: a report that over-claims success is more harmful than one that finds nothing.

### V. Test-Backed Rules and Acceptance Criteria
- Every rule, fixer, validator, and parser adapter MUST ship with tests: a positive sample, a
  negative (must-not-match) sample, and an idempotence check for fixers.
- Every requirement MUST have acceptance criteria and a mapped test or validation method.
- Regression fixtures MUST be added for every defect fixed.

Rationale: structured rewriting of source code regresses easily without fixtures.

### VI. Official Evidence Only
- Every Odoo-specific compatibility claim MUST cite official Odoo documentation or official
  Odoo source (`github.com/odoo/*`) at an immutable revision (commit SHA or release tag).
- Memorised model knowledge, skills, blogs, forums, and third-party migration tools MUST NOT be
  used as authority. They MAY inspire generic techniques only.
- Claims without official evidence MUST be marked `UNVERIFIED` and MUST NOT drive automatic
  transformations.
- A source-to-target path MUST NOT be advertised as supported until its rules are evidence-backed
  and its required validation tests pass.

Rationale: incorrect compatibility rules silently damage customer modules.

### VII. Layered Validation Before Success Claims
- Every written file MUST pass syntax validation for its language before promotion.
- Static compatibility, dependency integrity, runtime installation, and behavioural validation
  are distinct layers. A higher status MUST NOT be reported when a required layer did not run
  or did not pass.
- Valid syntax MUST NOT be equated with a successful migration.

Rationale: a module that parses is not a module that installs, and installing is not the same
as behaving correctly.

### VIII. Business Logic Preservation and Disclosed Limits
- Transformations MUST NOT change business behaviour except where the target version requires
  it and the rule documents the change.
- Semantics-changing constructs (for example, recordset iteration, ORM overrides, constraints,
  security rules) MUST be flagged for review rather than silently rewritten.
- The tool MUST state what was and was not verified. Static analysis alone MUST NOT be presented
  as proof of preserved business logic.

Rationale: customers depend on behaviour, not syntax.

### IX. Modular, Extensible Architecture
- Versions, rules, parsers, validators, AI providers, runtime environments, and report formats
  MUST be added through registries and documented contracts, without editing the core engine.
- No maximum Odoo version may be hardcoded in the engine.
- Every edit MUST be a targeted, attributable edit (rule ID, location, before/after). Whole-file
  rewrites are allowed only when the contract justifies them.

Rationale: new Odoo releases arrive every year; the engine must absorb them as data and plugins.

### X. Phase-by-Phase Delivery and Independent Verification
- Work proceeds through the approved roadmap phases. A phase starts only when its entry criteria
  are met and ends only when its exit criteria are verified with recorded evidence.
- No silent changes to existing behaviour: every behaviour change MUST be specified, tested, and
  noted in the change record.
- Implementation agents MUST stop and request clarification instead of redesigning a phase.

Rationale: independent agents can deliver safely only against explicit, verifiable contracts.

## Technical Constraints

- Language: Python 3.10 or newer for the tool itself (the minimum supported by the newest
  verified Odoo target; see the evidence register). The tool parses customer code written for
  Python 3 versions supported by Odoo 12 and later.
- Supported Odoo versions are those listed in the Version Registry with research status and
  passing validation. Odoo Online intermediate releases (x.1–x.4) are mapped to the next on-premise
  major version.
- Exit codes MUST distinguish success, unresolved findings above the configured threshold,
  rejected changes, and tool errors.
- The legacy entry point `odooflux.py` remains the supported command until the Phase 2
  cut-over criteria are met.

## Development Workflow

- Changes follow the Spec Kit flow: constitution → specify → clarify → plan → tasks → analyze →
  implement, one roadmap phase per feature directory under `specs/`.
- Every task MUST reference the requirement it implements and the test that verifies it.
- Pull requests MUST state the principles and phase they affect and justify any added
  complexity in the plan's Complexity Tracking section.
- Commits MUST be focused; refactors are kept separate from behaviour changes.

## Governance

This constitution supersedes other practices. Amendments require a documented change to this
file, a Sync Impact Report, and maintainer approval. Versioning is semantic: MAJOR for removed
or redefined principles, MINOR for new principles or materially expanded guidance, PATCH for
clarifications. Every plan MUST pass the Constitution Check; every review MUST verify
compliance; violations require explicit written justification in Complexity Tracking.

**Version**: 2.0.0 | **Ratified**: 2026-11-06 | **Last Amended**: 2026-11-06
