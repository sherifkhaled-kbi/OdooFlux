# Migration Rule Engine

Design of the version-aware engine: registries, planning, execution, recovery, and the rule
lifecycle. Contracts are in [architecture/CONTRACTS.md](architecture/CONTRACTS.md). Decisions:
[ADR-007](ARCHITECTURE_DECISIONS.md#adr-007--version-graph-of-consecutive-major-steps),
[ADR-008](ARCHITECTURE_DECISIONS.md#adr-008--evidence-status-is-separate-from-rule-maturity),
[ADR-009](ARCHITECTURE_DECISIONS.md#adr-009--knowledge-base-stored-as-json-data).
Owner phases: P2 (registries, graph, planner, executor, recovery), P3 (data), P4 (edit
engine), P5 (rules).

## 1. Components

| Component | Location | Responsibility |
|---|---|---|
| Version Registry | `src/odooflux/versions/registry/` | Loads `knowledge/compatibility/versions.json` → `OdooVersion` list; validates ordering, Python ranges, statuses (REQ-VER-001) |
| Version Graph | `src/odooflux/versions/graph/` | Consecutive major steps; `path(s, t)` → steps; marks steps whose research status is below the configured minimum as blocked (REQ-VER-002/003) |
| Version Adapters | `src/odooflux/versions/adapters/` | Non-rule per-version facts: Python range, file-kind mapping changes (e.g. view type names), manifest file names, asset bundle naming. Pure data accessors |
| Rule Registry | `src/odooflux/rules/shared/` | Loads rule metadata from `knowledge/compatibility/<step>.rules.json`, binds detector/fixer code by rule ID, validates evidence references and maturity (REQ-EVD-001/003) |
| Planner | `src/odooflux/core/orchestrator/` | Builds `MigrationPlan`: steps × dependency-ordered modules (REQ-DEP-002) |
| Executor | `src/odooflux/core/orchestrator/` + `core/engine/` | Runs each step: parse → detect → plan edits → AI escalation (optional) → apply → L1/L2 validation → re-scan |
| Checkpoint Manager | `src/odooflux/core/recovery/` | Persists per-module, per-step completion with document hashes (REQ-SAF-009) |
| Recovery Manager | `src/odooflux/core/recovery/` | Rollback from run log; resume from last checkpoint (REQ-SAF-008/009) |

## 2. Version registry data

```json
{ "id": "17.0", "major": 17, "python_min": "3.10", "python_max": null,
  "online_releases": ["16.1","16.2","16.3","16.4"],
  "research_status": "RESEARCH_SEEDED", "support_status": "UNSUPPORTED",
  "evidence": ["EV-125"] }
```

There is no maximum version constant. The graph is derived by sorting entries by `major`
(REQ-ARC-003).

## 3. Shared vs version-specific rules

- **Version-specific rules** belong to exactly one step (`"step": "16-17"`). They run only when
  that step is in the plan.
- **Shared rules** (`"step": "*"`) are version-independent hygiene checks (for example, manifest
  parse errors, unreadable files, XML well-formedness). They run once per module at the start
  and are never Odoo compatibility claims, so they need no Odoo evidence. Their evidence field
  holds `NOT_APPLICABLE` with a justification.
- Rule **code** is grouped by language (`rules/python`, `rules/xml`, …); rule **metadata** is
  grouped by step. One code function may serve several rules (for example, a generic
  "rename keyword argument" fixer parameterised by metadata).

## 4. Rule maturity

| Maturity | Meaning | Allowed actions |
|---|---|---|
| `DRAFT` | Metadata exists; tests incomplete | Not loaded in normal runs (`--include-draft` for development) |
| `DETECT_ONLY` | Evidence + detector tests pass; no fixer, or fixer not yet trusted | Detect, report, suggest |
| `FIX_ENABLED` | Evidence `DOCUMENTED_NOT_TESTED` or `VERIFIED`, plus positive/negative/idempotence tests pass | Detect and produce Edits |
| `RETIRED` | Superseded or proven wrong | Not loaded; kept for history |

Evidence statuses `UNVERIFIED` and `CONFLICTING` cap a rule at `DETECT_ONLY` (REQ-EVD-003).
`review_required` rules never produce silent edits; their results are capped at `NEEDS_REVIEW`
(REQ-PY-003).

## 5. Rule dependencies, ordering, and conflicts

1. **Within a step**, rules are ordered topologically by `depends_on`, then by rule ID for
   determinism (REQ-ARC-005). Cycles in `depends_on` fail rule loading.
2. **Across steps**, all rules of step `s→s+1` finish (including validation) before step
   `s+1→s+2` starts, on the step's output document.
3. **Edits** from one rule batch are checked for overlap. Precedence: higher severity, then
   `depends_on` order. Otherwise both edits are rejected and reported (contract in
   [architecture/CONTRACTS.md](architecture/CONTRACTS.md#edit)).
4. `conflicts_with` declares mutually exclusive rules. If both match the same span, the first by
   order wins and the second is reported as `REJECTED` with reason `conflict:<rule>`.
5. After each batch the document is re-parsed. Edits whose `before` text no longer matches are
   rejected (stale span).

## 6. Planner

Input: request `(source, target)`, module paths, options. Steps:
1. Discover modules and detect each declared version (REQ-VER-006).
2. Compute `path(source, target)`.
3. Mark steps below the minimum research status as `blocked_steps`.
4. If blocked and `--allow-unverified` is not set, return a `BLOCKED` plan naming the steps
   (REQ-VER-003).
5. Order modules topologically by `depends` (cycles → finding, not a crash; REQ-DEP-002).

## 7. Executor

For each module (dependency order), for each step:
1. Parse the documents (cached by hash).
2. Run the detectors of the step's loaded rules.
3. Collect fixer edits.
4. Optionally escalate eligible open findings to AI (P6).
5. Apply edits in the workspace and run L1 syntax plus rule-declared validators. Reject failing
   edits and restore that document to its pre-batch text.
6. Re-scan; set `FIXED` only for findings that disappeared (REQ-TRF-005).
7. Write a checkpoint.

After the last step, run L3 (and L4/L5 if enabled), decide the status, then promote (write mode
only).

## 8. Unsupported-version handling

| Situation | Behaviour |
|---|---|
| Source or target missing from the registry | Exit as tool error; message lists known versions |
| Target ≤ source | Usage error |
| Step with `research_status` below the minimum | Plan `BLOCKED`, or `NEEDS_REVIEW` with `--allow-unverified` (detect-only for that step) |
| Detected manifest version ≠ requested source | Finding; with `--trust-manifest`, the detected version is used |
| Customer Python not parseable by the tool interpreter | File-level `NEEDS_REVIEW` finding; no edits to that file |

## Adding a new Odoo version

Procedure for an implementer (example: Odoo 20.0). No core code changes are permitted
(REQ-VER-005).

1. **Registry entry.** Add `20.0` to `knowledge/compatibility/versions.json` with
   `research_status: NOT_ASSESSED` and `support_status: UNSUPPORTED`. Fill `python_min` from
   official `odoo/release.py` or `setup.py` at a pinned SHA (new evidence record).
2. **Pin revisions.** Record SHAs for `odoo/odoo` 20.0, `odoo/documentation` 20.0, and the
   bundled OWL version in `knowledge/official_sources/revisions.json`.
3. **Research step 19-20** using the workflow in
   [OFFICIAL_SOURCES_STRATEGY.md](OFFICIAL_SOURCES_STRATEGY.md#research-workflow-per-transition-step-n--n1).
   Create evidence records and gap records; set `research_status` to `RESEARCH_SEEDED`, then
   `RESEARCHED` after peer review.
4. **Refresh existing evidence** against the 20.0 SHA (refresh workflow). Rules whose evidence
   moved or vanished are demoted.
5. **Write rules** in `knowledge/compatibility/19-20.rules.json`, with code in
   `rules/<language>/`. Each rule starts as `DRAFT`.
6. **Tests.** For every rule, add positive, negative, and idempotence tests, plus a golden fixture
   `tests/golden_fixtures/19.0/<module>` with the expected 20.0 output. Promote maturity as tests
   pass.
7. **Core module list.** Add the 20.0 core module list (for `depends` checks) from the pinned
   source tree to `knowledge/compatibility/core_modules/20.0.json`.
8. **Runtime.** Add the runtime image reference for 20.0 (provenance per ADR-011) and run the
   golden fixture install. On success, mark evidence `VERIFIED` and the matrix cell
   `RUNTIME_VALIDATED`.
9. **Regenerate the matrix** and set `support_status: SUPPORTED` only when all steps on the path
   are `RULES_TESTED` and the target is `RUNTIME_VALIDATED`.
10. **Change record.** Document the new support statement in the release notes.

## Legacy rule disposition

Every rule tuple in the legacy `odooflux.py` (commit `c9914e6`, lines 87–406), with its
disposition for the new engine:
- **keep**: claim confirmed; port with evidence.
- **correct**: claim partly wrong; port with corrected step, maturity, or fixer.
- **retire**: wrong, out of scope (pre-12.0), or noise.
- **needs-research**: no official evidence yet.

Audit findings are referenced from [../reviews/ODOO_MODULE_UPGRADER_AUDIT.md](../reviews/ODOO_MODULE_UPGRADER_AUDIT.md).

### PYTHON_RULES

| # | Legacy rule (category) | Disposition | New rule / reason | Evidence / gap |
|---|---|---|---|---|
| 1 | `openerp` namespace | retire | No `openerp` package in 12.0, the lowest supported source | EV-205 |
| 2 | `@api.one/multi/returns` | correct | Split: `12-13.python.api-multi-removed`, `12-13.python.api-one-removed` (review), `18-19.python.api-returns-removed` (review). Legacy said "v14+" and removed `@api.returns` for all targets | EV-101, EV-102; F-PY-1/3/4 |
| 3 | Old API `cr, uid` signature | needs-research | Pre-12 construct; keep as shared hygiene detection only if 12.0 rejects it | G-R-01 |
| 4 | `fields.Char(size=…)` | needs-research | Claimed "ignored in v13+"; not located in official source | G-R-01; F-PY-2 |
| 5 | `execute_kw` INFO | retire | Noise; not a compatibility claim | F-VER-4 |
| 6 | `.sudo(user)` | correct | `12-13.python.sudo-user-argument`, detect-only; never rewrite boolean flags; semantics unresolved | EV-103; G-R-14; F-PY-5 |
| 7 | `_inherits` warning | retire | Supported mechanism; misleading warning | F-VER-3 |
| 8 | `osv` import | correct | 12.0 still ships `odoo/osv` (EV-211 notes `orm.py`/`osv.py` present); fold into `18-19.python.osv-deprecated` | EV-002, EV-211 |
| 9 | `_columns` dict | retire | Pre-12 API; 12.0 has no `_columns` attribute handling | EV-211 |
| 10 | `_defaults` dict | retire | Pre-12 API, same as #9 | EV-211 |
| 11 | `openerp.tools` `html_sanitize` import | retire | Same as #1 | EV-205 |
| 12 | Python 2 `print` | retire | Supported sources are Python 3 (≥3.5) | EV-125 |
| 13 | `fields.Html` sanitize (17) INFO | needs-research | Claim unverified | G-R-17 |
| 14 | `qweb.` / `t-widget` (15) | needs-research | Regex too broad (F-VER-3); legacy widgets need JS research | G-R-03 |
| 15 | `attachment=False` (18) | needs-research | Claim unverified | G-R-17 |
| 16 | `werkzeug.contrib` | retire | Not an Odoo claim (third-party library); may return as a generic dependency check | — |
| 17 | `ir.values` | retire | Model absent in 12.0 | EV-206 |
| 18 | `message_post_with_template` | correct | `16-17.python.message-post-with-template`; removed in 17.0, not "signature changed in v16" | EV-207 |
| 19 | `_auto_init` (19) INFO | needs-research | Claim unverified | G-R-17 |
| 20 | TransientModel INFO | retire | Noise | F-VER-4 |
| 21 | AbstractModel INFO | retire | Noise | F-VER-4 |
| 22 | Selection lambda default | retire | Claim false per audit; no official evidence of removal | F-VER-3 |
| 23 | `_cr.execute` with `%` formatting | correct | Shared security hygiene rule (`*.python.sql-string-formatting`), not a migration claim; combine with `18-19.python.env-shortcuts-deprecated` | EV-209 |
| 24 | `openerp.http` import | retire | Same as #1 | EV-205 |
| 25 | `from openerp.` | retire | Same as #1 | EV-205 |
| 26 | `import openerp` | retire | Same as #1 | EV-205 |
| 27 | `Warning` import (odoo) | correct | `16-17.python.warning-exception`; removal is in 17.0, not 14 | EV-110 |
| 28 | `Warning` import (openerp) | retire | Same as #1 | EV-205 |
| 29 | `raise Warning(` | correct | Part of `16-17.python.warning-exception` | EV-110 |

### XML_RULES

| # | Legacy rule | Disposition | New rule / reason | Evidence / gap |
|---|---|---|---|---|
| 1 | `<openerp>` root | needs-research | Check whether 12.0 `convert.py` accepts `<openerp>` | G-R-06 |
| 2 | `attrs=` | correct | `16-17.xml.attrs-removed`; converter must emit Python expressions | EV-109; F-XML-2/3 |
| 3 | `states=` | correct | `16-17.xml.states-attribute-removed`; no in-tag comments | EV-109; F-XML-1/4 |
| 4 | `<act_window>` | correct | `16-17.xml.act-window-tag` (deprecated 16.0, removed 17.0) | EV-117 |
| 5 | `<menuitem>` INFO | retire | Noise | F-VER-4 |
| 6 | `<url>` tag | needs-research | Not located | G-R-06 |
| 7 | `groups_id=` attribute | needs-research | Unclear claim; may relate to EV-114 (field rename, 19.0) | EV-114; G-R-10 |
| 8 | `web_client_action` (16) | needs-research | Claim unverified | G-R-03 |
| 9 | arch `type="xml"` INFO | retire | Noise | F-VER-4 |
| 10 | "Editable Form" (17) | retire | Regex does not match the stated claim | F-VER-3 |
| 11 | `monetary` widget INFO | retire | Noise | F-VER-4 |
| 12 | `<tree>` (18) | correct | `17-18.xml.tree-to-list`, gated for all sources below 18.0 including 18→19 leftovers | EV-112; F-VER-1 |
| 13 | `oe_chatter` div | needs-research | `<chatter/>` window unresolved | G-R-09; F-XML-5/6 |
| 14 | `message_ids` field | needs-research | Same as #13 | G-R-09 |
| 15 | `activity_ids` field | needs-research | Same as #13 | G-R-09 |
| 16 | `message_follower_ids` field | needs-research | Same as #13 | G-R-09 |
| 17 | `mail_thread` widget | needs-research | Same as #13 | G-R-09 |
| 18 | `<chatter>` placement INFO | needs-research | Same as #13 | G-R-09 |
| 19 | `<page attrs=>` (17) | retire | Duplicate of #2 | EV-109 |
| 20 | `noupdate="0"` INFO | retire | Noise | F-VER-4 |
| 21 | `<header>` placement (17) INFO | retire | Noise; claim unverified | F-VER-4 |

### MANIFEST_RULES, JS_TS_RULES, CSS_RULES

| # | Legacy rule | Disposition | New rule / reason | Evidence / gap |
|---|---|---|---|---|
| M1 | `version` key INFO | correct | Shared rule `*.manifest.version-prefix`; preserve the module suffix (REQ-MAN-002) | F-MAN-1 |
| M2 | `installable: False` | keep | Shared hygiene rule (not an Odoo version claim) | — |
| M3 | `auto_install: True` INFO | retire | Noise; replaced by `depends` checks (REQ-DEP-001) | — |
| M4 | `application: True` INFO | retire | Noise | — |
| J1 | `odoo.define(` | correct | Loader API still exists in 17.0; legacy `function(require)` form needs research. Detect-only | EV-122; G-R-08 |
| J2 | `require('web.` | needs-research | Tied to J1 | G-R-08 |
| J3 | `Widget.extend(` | needs-research | Legacy widget removal window | G-R-03 |
| J4 | `ajax.jsonRpc(` (16) | correct | Fold into `17-18.js.rpc-service-removed` research; legacy suggestion (`env.services.rpc`) is wrong for 18.0+ | EV-120; F-VER-6 |
| J5 | jQuery `.on('click'` INFO | retire | Noise | F-VER-4 |
| J6 | `useRef(` INFO | needs-research | OWL API research | G-R-03 |
| C1 | `.o_form_sheet_bg` | needs-research | CSS class changes unresearched | G-R-18 |
| C2 | `.o_list_view` | needs-research | Same as C1 | G-R-18 |

### Version-specific legacy rules

| # | Legacy rule | Disposition | Reason | Evidence / gap |
|---|---|---|---|---|
| V18-1 | `spreadsheet_dashboard` reorganised | retire | Module present in 17.0 and 18.0 | EV-212 |
| V18-2 | `website.published.mixin` removed in 18 | retire | Contradicted: the model is still defined in 18.0 | EV-208 |
| V18-3 | `phone.validation.mixin` path changed | needs-research | Name not found at 16.0–18.0 by name search | G-R-17 |
| V18-4 | `<notebook invisible=>` (18) | retire | Unverified, vague | — |
| V18-5 | manifest version must be `18.0` | correct | Merged into `*.manifest.version-prefix` (target-aware) | F-MAN-1 |
| V19-1 | manifest version must be `19.0` | correct | Same as V18-5 | F-MAN-1 |

Totals: 68 legacy rules. 1 keep, 16 correct, 29 retire, 22 needs-research.
