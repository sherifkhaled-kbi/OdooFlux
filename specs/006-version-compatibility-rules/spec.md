# Feature Specification: Version Compatibility Rules

**Feature Branch**: `006-version-compatibility-rules`
**Created**: 2026-11-06
**Status**: Draft — planned, not implemented
**Phase**: P5 ([handoff](../../docs/planning/phase-handoffs/PHASE_05_VERSION_COMPATIBILITY.md))
**Input**: User description: "Implement researched, version-specific migration rules for Python/ORM, XML views and data, QWeb, JavaScript/OWL, assets, manifests, dependencies, and security data, each backed by official evidence and tests, plus a business-logic risk inventory."

## Clarifications

### Session 2026-11-06

- Q: Which steps must be complete for this phase? → A: 14-15 through 18-19 (D-04 default: lowest first-release source 14.0). 12-13 and 13-14 are researched as far as possible, and paths through them stay `BLOCKED` until `RESEARCHED`.
- Q: May a rule be written where research is incomplete? → A: No fixer. A detector is allowed only if official evidence for the detected construct exists. Otherwise the research task comes first.
- Q: How are semantics-changing constructs handled? → A: As `review_required` detect-only rules with evidence links. Examples: `@api.one`, `@api.returns`, `name_get`, `_name_search`, `_sql_constraints`, `read_group`, field `states`, `sudo(user)`.
- Q: What happens to the legacy rules? → A: They are disposed per [MIGRATION_RULE_ENGINE.md §Legacy rule disposition](../../docs/planning/MIGRATION_RULE_ENGINE.md#legacy-rule-disposition): ported (keep/correct), retired, or researched.
- Q: Are Enterprise modules covered? → A: No (D-05 default). Enterprise dependencies are reported as unknown, with WARNING.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Migrating a 17.0 module to 18.0 or 19.0 gets correct, evidenced findings and safe fixes (Priority: P1)

A migration engineer runs OdooFlux on a 17.0 module targeting 18.0 or 19.0. Every finding cites
official evidence. Safe mechanical changes are applied (for example `<tree>`→`<list>`,
`group_operator`→`aggregator`, `type='json'`→`'jsonrpc'`, `_cr`→`env.cr`). Semantics-changing
constructs are flagged for review rather than rewritten.

**Why this priority**: Highest customer value and the strongest evidence (EV-002…010,
EV-102…120, EV-209/210).

**Independent Test**: Golden fixtures `tests/golden_fixtures/17.0/*` migrated to 18.0 and 19.0
match the expected trees and reports. Every rule for steps 17-18 and 18-19 passes its
positive, negative, and idempotence tests.

**Acceptance Scenarios**:

1. **Given** a 17.0 view with `<tree>` and `view_mode` `tree,form` in XML and in a Python action dict, **When** migrated to 18.0, **Then** all are rewritten to `list` and the output is well-formed.
2. **Given** a model with `_sql_constraints` migrated to 19.0, **When** analysed, **Then** a CRITICAL review-required finding cites EV-116 and EV-006, and the module status is at most `NEEDS_REVIEW`.
3. **Given** `@api.returns('self')` in an 18.0 module targeting 18.0 only, **When** analysed, **Then** no finding is raised (the rule belongs to step 18-19).
4. **Given** `self._cr.execute(...)` in an 18.0 module targeting 19.0, **When** fixed, **Then** it becomes `self.env.cr.execute(...)` and the finding is marked `FIXED` by re-scan.

---

### User Story 2 - Migrating 14.0–16.0 modules through multiple steps (Priority: P1)

A 14.0 module targeting 19.0 is processed step by step. Each step's rules apply to the previous
step's output: attrs/states conversion at 16-17, `t-esc` at 14-15, `args=`→`domain=` at 15-16,
`Warning`→`UserError` at 16-17.

**Why this priority**: Multi-step migration is OBJ-001's core promise.

**Independent Test**: Golden fixtures 14.0, 15.0, and 16.0 → 19.0 match expected outputs. Each
intermediate step's output passes syntax validation.

**Acceptance Scenarios**:

1. **Given** a 16.0 view with `attrs` using `|` and falsy leaves, **When** migrated (with G-R-20 resolved), **Then** the modifiers are correct Python expressions.
2. **Given** `raise Warning('x')` with `from odoo.exceptions import Warning`, **When** migrated across 16-17, **Then** both the import and the raise use `UserError` and the file compiles.
3. **Given** a 14.0 QWeb template with `t-raw`, **When** migrated, **Then** a review-required finding (escaping semantics) is raised and no edit is made.

---

### User Story 3 - Dependencies, manifests, and security data are checked (Priority: P2)

The engineer learns about missing data files, wrong load order, unknown or removed `depends`, and
security data using renamed fields (e.g. `groups_id` in 19.0).

**Why this priority**: These cause install failures that syntax checks cannot see.

**Independent Test**: Fixtures with each broken reference produce the expected findings.

**Acceptance Scenarios**:

1. **Given** a manifest listing a missing data file, **When** analysed, **Then** a CRITICAL finding names the path.
2. **Given** `depends: ['website_sale_comparison_wishlist']` absent from the target core list and from scanned modules, **When** analysed, **Then** an `unknown-dependency` WARNING cites the core-module list evidence.
3. **Given** a record rule domain using `groups_id` targeting 19.0, **When** analysed, **Then** a review-required finding cites EV-114.

---

### User Story 4 - Business-logic risk inventory (Priority: P2)

Reviewers get a per-module inventory of overrides, computes, onchanges, constraints,
multi-company code, transactions, crons, controllers, security-sensitive calls, and integrations.
This tells them where to focus manual or behavioural testing.

**Why this priority**: Principle VIII requires disclosing what static analysis cannot prove.

**Independent Test**: The inventory fixture lists every occurrence with class and location.

**Acceptance Scenarios**:

1. **Given** a module overriding `write` and containing `cr.commit()`, **When** inventoried, **Then** both appear with classes `orm-override` and `transaction`.

---

### User Story 5 - JavaScript/OWL and assets findings (Priority: P3)

The engineer sees evidenced findings for removed services, module-system changes, kanban
templates, and asset declarations. With the JS adapter they also get safe fixes where evidence
allows.

**Why this priority**: Evidence is thinner (G-R-03, G-R-05, G-R-08) and JS needs the optional adapter.

**Independent Test**: JS/asset fixtures produce the expected findings with and without the adapter.

**Acceptance Scenarios**:

1. **Given** a 17.0 file using `useService("rpc")`, **When** targeting 18.0, **Then** a review-required finding cites EV-120.
2. **Given** a 14.0 manifest with a `qweb` key, **When** targeting 15.0+, **Then** a finding cites EV-123/124. No fixer runs until G-R-05 is resolved.

### Edge Cases

- A construct already in target form (e.g. `<list>` in 17.0 sources): no finding, no edit.
- A module whose declared version differs from the requested source: handled by the planner (P2). The rules use the planned step.
- The same file touched by rules from several steps: each step re-parses and re-validates. Stale spans are rejected.
- Mixed-case or aliased imports (`from odoo import exceptions as exc; raise exc.Warning`): detected through import resolution. A fixer applies only when resolution is unambiguous.
- Rules whose evidence gets demoted to `CONFLICTING` by a refresh: auto-capped to `DETECT_ONLY` (feature 004).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every rule MUST be defined as metadata in `knowledge/compatibility/<step>.rules.json` with evidence, maturity, risk, `review_required`, and validators, bound to detector/fixer code. Traces: REQ-PY-002, REQ-EVD-001.
- **FR-002**: Each rule MUST have positive, negative, and (if it has a fixer) idempotence tests. A coverage test MUST fail when any loaded rule lacks them. Traces: REQ-TST-002.
- **FR-003**: Python/ORM rules from the seed catalogue MUST be implemented at their proposed maturity, or lower if tests or research are incomplete. Traces: REQ-PY-002.
- **FR-004**: Semantics-changing constructs MUST be detect-only `review_required` findings with evidence and suggested manual action. Traces: REQ-PY-003.
- **FR-005**: View/data rules MUST cover `attrs`/`states` conversion (via the feature 005 converter), `tree`→`list` (XML and Python `view_mode`), kanban `kanban-box`, `<act_window>`/`<report>` tags, cron `numbercall`, and researched chatter changes. Traces: REQ-XML-002, REQ-XML-003.
- **FR-006**: QWeb rules MUST cover `t-esc` (fix) and `t-raw` (review), plus any directive changes found by G-R-04 research. Traces: REQ-XML-005.
- **FR-007**: JS/OWL rules MUST cover the `rpc` service removal (EV-120), module-system evidence (EV-121/122), and OWL changes found by G-R-03/G-R-08 research. Traces: REQ-JS-002.
- **FR-008**: Asset rules MUST detect the legacy manifest `qweb` key and XML asset templates. Fixes are allowed only after G-R-05 research. Traces: REQ-JS-003.
- **FR-009**: Manifest rules MUST check that `data`/`demo`/asset paths exist and that security files load before views. Traces: REQ-MAN-003.
- **FR-010**: Dependency rules MUST check `depends` against the target core-module list (official, pinned) and scanned modules. Traces: REQ-DEP-001.
- **FR-011**: Cross-module reference checks MUST report dangling XML IDs, unknown models, and unknown fields among scanned modules. Unverifiable core references MUST be reported as such. Traces: REQ-DEP-003, REQ-VAL-003.
- **FR-012**: Security data rules MUST scan ACL CSVs, record rules, and groups for evidenced renames. Traces: REQ-ACL-001.
- **FR-013**: The system MUST produce a business-logic risk inventory per module with the classes in research.md R-7. Traces: REQ-BIZ-001.
- **FR-014**: Golden migrations MUST exist for each source version 14.0–18.0 to each later target, with expected trees and reports. Traces: REQ-TST-003.
- **FR-015**: Every legacy rule MUST be dispositioned (ported with evidence, retired, or researched), and the disposition recorded in the knowledge base (`RETIRED` entries with reasons). Traces: REQ-PY-002, REQ-EVD-003.
- **FR-016**: The procedure for adding a version MUST be proven by adding a synthetic version fixture through data, rules, and fixtures only. Traces: REQ-VER-005.

### Key Entities

- **RuleMetadata / RuleBinding**: see [data-model.md](data-model.md).
- **RuleCatalogueEntry**: see [contracts/rule-catalogue.md](contracts/rule-catalogue.md).
- **CoreModuleList**: per-version official module names + SHA.
- **RiskInventoryItem**: class, location, module, note.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % of loaded rules cite evidence and pass their required tests (coverage test reports 0 missing).
- **SC-002**: Steps 14-15…18-19 reach `RESEARCHED` and `RULES_TESTED` in the generated matrix. Any category not reached is listed as a gap with a reason.
- **SC-003**: Golden migrations: 100 % byte match for all (source, target) pairs in scope.
- **SC-004**: All 68 legacy rules have a recorded disposition (0 undispositioned).
- **SC-005**: Zero automatic edits are produced by `review_required` rules (enforced by test).
- **SC-006**: Analysis of the largest golden module (≥ 50 files) completes in under 10 seconds on the reference machine.

## Assumptions

- Features 004 (knowledge base, evidence enforcement) and 005 (parsers, edit engine, converter) have exited.
- Runtime confirmation (`VERIFIED`, `RUNTIME_VALIDATED`) happens in feature 008 (P7); this feature stops at `RULES_TESTED`.
- Research tasks are performed by agents with network access to clone official repositories at pinned SHAs.

## Amendment 2026-11-07: coverage gaps

Status: DRAFT, pending owner acceptance of the rules (see AMENDMENT-REVIEW.md). Spec work only: no rule, code or evidence record is added by this amendment. Background: [coverage-gaps.md](coverage-gaps.md). Existing FR-001..FR-016, SC-001..SC-006 and all existing rules are unchanged.

### Decision rule (applies to every new rule)

A rule is `AUTO_TRANSFORM` (FIX_ENABLED) only if ALL hold: (a) a mechanical old-to-new mapping is stated in official, version-pinned evidence (repository, path, SHA, line match); (b) a false-positive and ambiguity analysis is recorded in the rule's evidence/research note; (c) positive, negative and idempotence tests exist; (d) the owner accepted the rule. Otherwise it is `DETECT_ONLY` with `review_required: true` and no fixer. When in doubt, DETECT_ONLY. Facts not in a verified evidence record are "to be researched" and MUST NOT appear in rule messages.

### Functional Requirements (amendment)

- **FR-017**: Run-supplied parameters. `bind_rule` MUST accept an optional run context (at least the planned step's `target` version) and pass it as a keyword only to detector/fixer functions whose signature declares it. Rules whose functions do not declare it, and callers that pass no run context, MUST behave exactly as before. Static `params` keep precedence rules defined in contracts/rule-catalogue.md. Traces: REQ-PY-002, REQ-VER-005.
- **FR-018**: Renamed-model family. A DETECT_ONLY family MUST flag references to a model renamed in a step (Python `_name`/`_inherit`/`_inherits`/`env[...]`/`comodel_name` string literals; XML `model=`, `res_model`, `inherit_id`/`ref` external ids derived from the renamed model; CSV ACL `model_id:id`), driven by metadata params (`old`, `new`). First instance: `payment.acquirer` to `payment.provider` at 15-16 (EV-450). Further model renames MUST each have their own pinned evidence. No automatic edits (field names, XML ids and tables are not covered by a verified mapping).
- **FR-019**: Manifest version prefix. `*.manifest.version-prefix` MUST be bindable per run with `target` from FR-017, as DETECT_ONLY/`review_required` (its current state). Promotion to FIX_ENABLED requires a separate owner decision on the REQ-MAN-002 opt-out; no Odoo-series evidence exists or is claimed (policy rule).
- **FR-020**: Dependency compatibility. The system MUST distinguish, per step, a `depends` entry that is (i) removed with a known successor, (ii) removed with no known successor, (iii) renamed/merged, from the existing unknown-dependency finding. Successor data (`replaced_by`) MUST come from per-module official evidence; modules without it stay "no successor known". Findings with a successor are DETECT_ONLY suggestions; no edit of `depends` unless the decision rule above is met (single, unambiguous 1:1 rename).
- **FR-021**: XPath/inherited-view stability. The system MUST provide a pinned, per-version index of core view external ids and named anchors (`name=`, `id=`), and a DETECT_ONLY rule flagging `inherit_id` refs absent from the target index, and `xpath` expressions whose named anchor is absent. Unverifiable (non-core, non-scanned) refs MUST be reported as unverifiable, not as errors (consistent with FR-011). No fix.
- **FR-022**: Every new rule MUST cite pinned official evidence, ship positive/negative tests (and idempotence if it has a fixer), be covered by the existing coverage test (FR-002/SC-001), and respect SC-005 (no automatic edits from review_required rules).

### Acceptance scenarios (amendment)

1. Given a 15.0 module with `_inherit = "payment.acquirer"` and a run 15.0 to 16.0, then one DETECT_ONLY finding cites EV-450 and no edit is produced; a run 16.0 to 17.0 yields none.
2. Given a manifest `'version': '15.0.1.0.0'` and a run targeting 16.0, the version-prefix rule reports it; with target 15.0 it reports nothing; with no run context the rule is skipped, not crashed.
3. Given `depends: ['payment_transfer']` for 15.0 to 16.0, the finding states a successor only if a `replaced_by` evidence record exists; otherwise it says no successor is known.
4. Given a view inheriting `payment.payment_acquirer_form` at target 16.0, the rule flags the missing id (evidence EV-450 plus the view index); an id in neither the index nor scanned modules is "unverifiable".
5. All existing rules produce byte-identical results before and after FR-017 (non-regression test).

### Edge cases (amendment)

- Model name is a substring or prefix of another (`payment.acquirer.method`): match whole dotted names only.
- Name appears in comments, docstrings or non-model strings: only AST string literals in the listed positions and XML attributes count.
- Multi-step runs (14 to 18): each step receives its own `target`; a rule bound for step 15-16 is not run for later steps; the old name flagged once.
- Manifest version missing, non-literal, or without numeric prefix: skipped (existing behaviour).
- Dependency present in both the removed list and scanned modules: scanned wins (existing FR-010).
- Index missing for a version: rule emits an "index unavailable" gap, not findings.
- Re-running on already-migrated code: detect rules emit nothing (idempotence of detection).
