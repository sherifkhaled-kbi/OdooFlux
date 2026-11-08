# Coverage gaps and dispositions (006)

Written 2026-11-07. Covers T053 (JS/OWL candidate disposition), T058 (SC-002 exceptions, see also verification.md) and the coverage investigation. Evidence IDs are real records under `src/odooflux/knowledge/evidence/`.

## T053: T019 JS/OWL candidate disposition

| Candidate (`rule_candidates.json`) | Disposition | Rule / reason |
|---|---|---|
| `17-18.js.rpc-service-removed` (EV-120, EV-394) | Implemented | `17-18.js.rpc-service-removed`, DETECT_ONLY, review_required; EV-394 added to the rule's evidence |
| `15-16.js.service-registry-on-listener` (EV-393) | Implemented | `15-16.js.service-registry-on` |
| `16-17.js.odoo-define-two-arg-form` (EV-390, EV-391) | Implemented | `16-17.js.odoo-define-legacy-form` |
| `17-18.js.legacy-widget-removed` (EV-392) | Implemented (narrow) | `17-18.js.legacy-widget-removed`: flags imports of `@web/legacy/js/core/widget` only (that exact path is 404 at 18.0 and 19.0). The legacy name `web.Widget` is not flagged: EV-392 evidences it at 15.0/16.0 only |
| `15-16.owl.owl1-component-lifecycle` (EV-340, EV-341, EV-395) | Partly implemented | `15-16.owl.mounted-method` covers `mounted()` (EV-395 line 4198 at 15.0, absent at 16.0). NOT implementable yet: `willStart()` and the `hooks`/`tags` exports. EV-395's description names them, but its locations record only `mounted()` and `exports.hooks` at 15.0 with no 16.0 absence check for `hooks`/`tags`/`willStart` |
| `16-17.js.legacy-widget-esm` (EV-392) | Not implementable | EV-392 shows only that core's widget.js became an ES module at 17.0. It records nothing about user code (`require('web.Widget')`) breaking at 17.0, so there is no verified construct to detect |

Evidence that would unlock the rest: pinned-source locations showing `willStart` method and `hooks`/`tags`/`Component.env` style exports absent from OWL 2.8.4 at 16.0; the module-loader behaviour for `web.Widget` at 17.0.

EV-396 (`serviceRegistry.addValidation`, 18.0) has no user-code construct to migrate (additive); no rule.

## SC-002 exceptions

See `verification.md`. No step reaches `RESEARCHED` or `RULES_TESTED` in the generated matrix; the reasons are listed there.

## Coverage investigation

### payment.acquirer renamed payment.provider (website_payment)
- Evidence: new EV-450 (raw fetch at pinned SHAs): `payment_acquirer.py` / `_name = 'payment.acquirer'` at 15.0, `payment_provider.py` / `_name = 'payment.provider'` at 16.0 through 19.0; website_payment `_inherit`, view `model`, `inherit_id` ref (`payment.payment_acquirer_form` to `payment.payment_provider_form`) and file names follow at 16.0. The rename is at 16.0, not 17.0 as the golden review cases had assumed (those 5 cases now cite EV-450; review_status unchanged).
- No rule implemented: it is not in the seed catalogue or any 006 FR (FR-003/005 name specific rule families), and the rename is not mechanical (fields such as `acquirer_id`, XML ids, tables, data records).
- Proposed task: spec amendment adding a "renamed model" DETECT_ONLY family (Python `_name`/`_inherit`/`env[...]`, XML `model`/`inherit_id` refs) driven by metadata params (old, new), plus evidence for the other model renames found by the same method.

### Manifest version prefix (`*.manifest.version-prefix`, DRAFT)
- Detector and fixer exist (`hygiene:flag_version_prefix` / `fix_version_prefix`) but require keyword `target`. `bind_rule` takes only static `params`, so the rule cannot be bound without a hard-coded version.
- Minimal extension possible: `bind_rule(meta, modules, run_params=None)` supplying `target` (the planned step's target) as a keyword for functions that accept it. It was NOT made: `specs/006` data-model/contract define params as static rule metadata, and `spec.md:114` assigns step planning to the planner (P2). It is also an interface change to the FR-001 binding contract and promoting it to FIX_ENABLED has no Odoo-series evidence (policy only: REQ-MAN-002 / F-MAN-1).
- Proposed task: amend 006 data-model and contracts (run-supplied params), then add run_params to `bind_rule` with tests, then bind the rule per run as DETECT_ONLY/review_required (its current review_required), decide FIX_ENABLED separately with the REQ-MAN-002 opt-out.

### Dependency changes
- Covered: FR-010 / `*.deps.unknown-dependency` against the pinned core-module lists (EV-430..433, 372..375). Per step the lists differ by 22 to 51 removed modules (for example 15.0 to 16.0 removes `payment_transfer`, `payment_test`, `sale_coupon`), so removals surface as unknown-dependency WARNINGs.
- Gap: the lists cannot distinguish a rename or merge from a removal, so no replacement suggestion can be given. Needed evidence: per removed module, the official successor (module `__manifest__`/release notes/commit at the pinned SHA). Proposed task: research task for removed-module successors (payment, loyalty/coupon, sale_* families first), then a `replaced_by` field in `core_modules.json` and a schema change.

### XPath stability of inherited views
- No evidence and no rule. EV-450 shows the concrete risk: the inherited view id `payment.payment_acquirer_form` no longer exists at 16.0. Golden cases for social_media (`base.view_company_form`, `//group[@name='social_media']`) are marked "unverified" for the same reason.
- Needed evidence: a pinned index of core view external ids and the named anchors (`name=`, `id=`) per version, extracted from official sources at the pinned SHAs. Proposed task: research + extractor tool, then a DETECT_ONLY rule that flags an `inherit_id` ref absent from the target index (and xpath anchors absent), without any fix.

## Status (updated 2026-11-07, after owner decisions D-A1..D-A7, ADR-018)

| Gap | Status | Remaining |
|---|---|---|
| payment.acquirer / renamed models | DETECT_ONLY family implemented (12 verified renames, 36 rules, EV-450, EV-500..515) | `acquirer_id` field rename, tables, ACL row ids, unqualified ids: unmapped; no AUTO_TRANSFORM (D-A5 not approved) |
| Manifest version prefix | `*.manifest.version-prefix` bound per run via `bind_rule(run_params)`, DETECT_ONLY (D-A2) | Planner must supply `target` (P2 wiring); fixer stays disabled (D-A3 not approved) |
| Dependency changes | `replaced_by` schema + `*.deps.removed-with-successor` DETECT_ONLY; 2 of 236 removed modules have evidenced successors (EV-520, EV-521) | Scanner has no production caller yet; 234 removed modules have no successor found |
| XPath stability | View index 12.0..19.0 (EV-540..547) + inherit-id/xpath-anchor DETECT_ONLY rules; unverifiable cases report INFO | Non-core modules and unavailable index stay unverifiable; index not yet in package-data |
