# Planning Gaps, Decisions, and Assumptions

This document covers:
- decisions that need maintainer approval;
- open research gaps;
- assumptions the plan relies on;
- limits of the planning research.

Implementation agents MUST NOT decide a pending `D-NN` themselves. They proceed with the stated
**default** only where the phase is not blocked by that decision.

## 1. Decisions pending approval

| ID | Question | Options | Default (assumed by the plan) | Impact if changed | Blocks |
|---|---|---|---|---|---|
| D-01 | Approve constitution 2.0.0 (stdlib core, optional adapters, evidence-only rules)? | (a) approve 2.0.0; (b) keep 1.0.0 single-file stdlib-only; (c) amend differently | (a). Already applied to `.specify/memory/constitution.md` with `TODO(APPROVAL)`; see [ADR-002](ARCHITECTURE_DECISIONS.md#adr-002--dependency-policy-stdlib-core-optional-adapters) | (b) makes the `src/` package, JS parsing, RNG validation, and runtime validation non-compliant; P2–P9 would need redesign | P2 and later |
| D-02 | Which optional parsers? | JS: tree-sitter (MIT) / esprima (BSD, unmaintained) / Node + acorn. RNG: lxml (BSD) / none | tree-sitter for JS; lxml for RNG view validation ([ADR-005](ARCHITECTURE_DECISIONS.md#adr-005--xml-stdlib-expat-span-locator-optional-rng-adapter), [ADR-006](ARCHITECTURE_DECISIONS.md#adr-006--javascript-optional-parser-adapter-detection-only-fallback)) | No JS adapter means JS stays detect-only; no lxml means no RNG layer and a lower maximum status | P4 (JS adapter), P7 (RNG) |
| D-03 | Use Docker for runtime and behavioural validation? | (a) Docker CLI adapter; (b) Podman-compatible CLI; (c) no runtime layer | (a), with the adapter interface allowing (b) later ([ADR-011](ARCHITECTURE_DECISIONS.md#adr-011--runtime-validation-in-disposable-containers)) | (c) caps every result at `STATIC_VALIDATED` | P7 |
| D-04 | Lowest supported source version for the first release? | 12.0 / 13.0 / 14.0 / 15.0 | 14.0; 12.0 and 13.0 added once G-R-01 research is done | A lower floor needs 12→14 source-diff research before release | P5 scope, P9 support statement |
| D-05 | Is Odoo Enterprise source accessible? | Authorised access / none | None. Enterprise modules are out of scope; dependency on them gives `NEEDS_REVIEW`/`BLOCKED` with explanation | Access would add Enterprise research and runtime images | P3, P5, P7 (scope only) |
| D-06 | HTML report technology? | Static stdlib HTML (inline CSS, no JS) / templating library / JS framework | Static stdlib HTML ([ADR-010](ARCHITECTURE_DECISIONS.md#adr-010--presentation-independent-report-schema)) | A library would be an optional adapter (D-01 policy) | P8 |
| D-07 | Rich terminal output? | Stdlib ANSI only / optional `rich` adapter | Stdlib ANSI baseline + optional `rich` adapter | None for core behaviour | P8 |
| D-08 | AI data policy and default provider? | Default off / on; consent flag; default provider none / Anthropic / other | AI **off** by default. No default provider. An explicit `--ai-consent` is required before any customer code is sent. Supported adapters: fake, Anthropic, OpenAI-compatible, local | Turning AI on by default would violate Principle III's opt-in rule | P6 |
| D-09 | Introduce `pyproject.toml` with optional extras in P2? | Yes / keep a script-only distribution | Yes. Extras: `js`, `rng`, `runtime`, `ai-anthropic`, `ai-openai`, `rich`. A zero-dependency core install remains possible | Without packaging metadata, extras must be documented manually | P2 |
| D-10 | Legacy CLI deprecations at cut-over? | Keep all / deprecate with aliases / remove | Remove `--api-key` (security, REQ-AI-008). Alias `--filter-severity`→`--min-severity`, `--ai-fix`→`--ai`, and `--ai-verbose`→`--verbose` for one release. Make `--backup` implicit in fix mode, with `--no-backup` requiring confirmation. Offer `--legacy-json` for one release. See [MIGRATION_MAP.md](MIGRATION_MAP.md#2-cli-option-mapping) | Keeping `--api-key` leaves the credential-leak risk | P2 (cut-over), P8 |

## 2. Research gaps

Seeded from [research/OFFICIAL_EVIDENCE_REGISTER.md](research/OFFICIAL_EVIDENCE_REGISTER.md#research-gaps-seed-list).

| ID | Gap | Why it matters | Planned closure |
|---|---|---|---|
| G-R-01 | No ORM changelog for 12.0→15.0 (EV-015) | 12→13, 13→14, 14→15 rules need source-diff evidence | P3 research procedure: diff `odoo/` core files between pinned SHAs |
| G-R-02 | Enterprise source not accessed | No Enterprise rules or runtime validation | Only if D-05 changes |
| G-R-03 | OWL version per Odoo release and OWL API changes (`github.com/odoo/owl`) | OWL component rules (REQ-JS-002) | P3: map `web/static/lib/owl` version per branch; read the OWL changelog at tags |
| G-R-04 | QWeb directives (`t-esc`, `t-raw`, `t-out`) changes beyond presence counts | QWeb rules (REQ-XML-005) | P3: inspect `ir_qweb.py` per branch for deprecation warnings |
| G-R-05 | Asset bundle names and the 15.0 move from XML asset templates to manifest `assets` beyond EV-123/124 | Asset rules (REQ-JS-003) | P3: compare `web` manifests and `ir_asset.py` across 14.0/15.0 |
| G-R-06 | View RNG schema differences (`odoo/addons/base/rng/`) | RNG validation (REQ-XML-004) and view rules | P3: diff RNG files per step |
| G-R-07 | Whether 18.0 still accepts a `<tree>` arch root | Gating of the `tree`→`list` rule and the 18→19 rule | P3 source check, P7 runtime test |
| G-R-08 | Whether 17.0+ accepts the legacy `odoo.define(name, function(require){…})` form | JS module rules; NF-04 | P3 source check of `module_loader.js`, P7 runtime test |
| G-R-09 | `<chatter/>` introduction version and `oe_chatter` support window (probe counts ambiguous) | Chatter rules (F-XML-5/6) | P3: read the mail form compiler per branch |
| G-R-10 | Security model changes (`res.groups`, `ir.rule`, ACL CSV columns) per version | REQ-ACL-001 | P3 |
| G-R-11 | HTTP controller changes before 19.0 (`auth`, `csrf`, route types) | Controller rules | P3 |
| G-R-12 | Data migration requirements between versions (`odoo/upgrade-util` official but not reviewed) | Scope boundary: data migration is a non-goal, but findings must point to it | P3: review `upgrade-util` and upgrade docs at pinned SHAs |
| G-R-13 | Official container image provenance: `github.com/odoo/docker` (Odoo organisation) not researched; tags/versions per Odoo release unknown | ADR-011 image source and pinning (D-03) | P7: inspect `odoo/docker` at a pinned SHA; record image digests |
| G-R-14 | Semantic equivalence of 12.0 `sudo(user)` and 13.0 `with_user(user)` / `with_user(user).sudo()` (defined in [004 research](../../specs/004-official-source-intelligence/research.md)) | Legacy `.sudo(x)` fixer may add superuser mode on top of the user switch | P5 research task before any sudo fixer |
| G-R-15 | Replacement for `SavepointCase` in 17.0 (`TransactionCase` behaviour) (004 research) | 16→17 test-class rule stays DETECT_ONLY | P5 research task |
| G-R-16 | Replacement API for `user_has_groups` in 18.0 (`has_group`/`has_groups`, see EV-210) (004 research) | 17→18 rule stays DETECT_ONLY | P5 research task |
| G-R-17 | Unverified legacy claims: `fields.Html` sanitize defaults (17), `attachment=False` (18), `_auto_init` (19), `phone.validation.mixin` path (004 research) | Legacy rules marked needs-research in [MIGRATION_RULE_ENGINE.md](MIGRATION_RULE_ENGINE.md) | P5 research tasks |
| G-R-18 | Backend CSS class changes per version (004 research) | Legacy CSS rules retired until researched | P5 research task |
| G-R-19 | Odoo 20.0 not inspected (no release branch evaluated during planning) (004 research) | Registry has no 20.0 entry; matrix row `NOT_ASSESSED` | P3 refresh workflow once released |
| G-R-20 | Evaluation context and semantics of 17.0+ view modifier expressions (names available, falsy handling, combinations) (defined in [005 research](../../specs/005-structured-transformations/research.md)) | Gates enabling the `attrs` fixer | P4/P5 research before FIX_ENABLED |
| G-R-21 | Runtime images for versions ≤17.0 are not present at `odoo/docker` master (EV-301) (defined in [008 research](../../specs/008-runtime-behavioral-validation/research.md)) | Runtime validation for ≤17.0 targets/baselines | P7 research: repository history or build-from-source procedure |
| G-R-22 | Log message patterns for classifying install/upgrade errors per version (008 research) | L4 log analysis | P7 research tasks from official source |
| G-R-23 | Test-runner output format per version for per-test outcome parsing (008 research) | L5 behavioural comparison | P7 research tasks |

## 3. Planning assumptions

| ID | Assumption | If wrong |
|---|---|---|
| A-01 | OdooFlux migrates module **source** only; database data migration is out of scope | Requires a new objective and phases |
| A-02 | The tool runs on Python ≥ 3.10 and can parse customer Python for Odoo ≥ 12.0 (Odoo 12 requires ≥ 3.5; EV-125) | Syntax edge cases (e.g., identifiers that became keywords) become parse findings |
| A-03 | Users can install optional extras when they need JS edits, RNG, runtime, or AI | Results are capped at lower statuses |
| A-04 | Odoo Online releases x.1–x.4 ship on-premise in the next major (ADR-007) | Some rules move one step earlier; each rule is source-checked anyway (RSK-018) |
| A-05 | Customer modules are untrusted input | — (conservative by design) |
| A-06 | The current single maintainer team approves decisions D-01…D-10 before the blocked phases start | Phases stay `BLOCKED` in [SPECKIT_READINESS.md](SPECKIT_READINESS.md) |
| A-07 | Golden fixtures are synthetic modules written for the project, not customer code | Customer-code fixtures would need consent and anonymisation |

## 4. Known limitations of the planning research

- **Branch-tip SHAs, not release tags.** `odoo/odoo` publishes no per-release tags for these
  branches at the time of research. Evidence is pinned to branch-tip commits of 2024-01-29 to
  2026-11-06 (see the register). Later commits on stable branches can differ (RSK-017).
- **No runtime tests.** Every record is `DOCUMENTED_NOT_TESTED`. Nothing was installed in a
  running Odoo.
- **No Enterprise source** (G-R-02).
- **Online release mapping.** The docs changelog lists Online releases (15.2…18.4). Their mapping
  to on-premise majors is an assumption (A-04) that each rule must confirm in source.
- **Targeted probes, not a full diff.** About 35 constructs were checked. Absence of a
  documented change for a construct is not evidence that it did not change.
- **12.0–15.0** have no ORM changelog in the official docs (G-R-01).

## 5. Quality-gate issues found so far

| Issue | Status |
|---|---|
| Constitution 2.0.0 applied but not yet approved (D-01) | Open: blocks P2 |
| Research covers selected claims only; most matrix cells remain `NOT_ASSESSED` | Open by design: P3 scope |
| The `docs/planning/phase-handoffs/.gitkeep` placeholder should be removed once handoffs exist (noted in [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)) | Open: housekeeping |
| `--dry-run` writes `__manifest__.py` (NF-18): the earlier audit understated F-SAFE-1 | Recorded in [CURRENT_ARCHITECTURE_AUDIT.md](CURRENT_ARCHITECTURE_AUDIT.md); P0 |
| Earlier audit F-PY-3 statement is version-dependent (EV-102) | Corrected in the audit and the register |
