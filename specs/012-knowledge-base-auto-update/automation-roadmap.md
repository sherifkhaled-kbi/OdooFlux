# Automation roadmap: Odoo 16 -> 17 custom-module migration (planning deliverable)

Owner direction: approximately 90% of automated migration work (not 100%); developers handle the rest from the existing
plan and report; functional auto-fixes take priority over certification ceremony; experimental risk is accepted only
when explicitly opted in; the report must say what was fixed, refused and left for developers.

Everything below is **measured** unless labelled *plan*. No coverage figure is claimed before it is measured on the
corpus defined in section 7.

## 1. Coverage gap matrix (rule families that run for 16 -> 17)

Sources of rules: 32 KB rows (16-17 plus shared), the legacy P0 layer (`rules/shared/legacy_rules.py`, wired by
`legacy_adapter.step_for` whenever `--fix` is on), and 2,786 generated DRAFT rows (detect-only, none runnable).
Prevalence = occurrences in the official 16.0 `addons/` tree (5,309 py, 3,833 xml, 355 csv, 3,233 js files), a proxy for
custom code, not a measurement of custom code.

| Family | Rule(s) | Today | Why not fixed | Prevalence (occ / files) | Plan |
|---|---|---|---|---|---|
| XML `attrs=` | `16-17.xml.attrs-removed` (DETECT_ONLY) | detect | converter `transformers/modifiers.py` exists, is unwired; semantics note G-R-20 | 3,834 / 673 | T2 |
| XML `states=` | `16-17.xml.states-attribute-removed` | detect; legacy regex `_convert_states_to_invisible` runs under `--fix` | regex, assumes field `state`, no refusal report | 102 / 29 | T2 |
| Model rename mail.channel -> discuss.channel (python, xml, csv; 9 rows) | `16-17.*.model-renamed-discuss-*` | detect | no fixer | 684 / 86 | T4 |
| Python `name_get`, `_read_group`/`read_group`, `message_post_with_template` | 3 rows | detect | semantic, not mechanical | 148, 410, 30 | manual |
| Python field `states=` parameter | `16-17.python.field-states-parameter` | detect | removing it loses readonly behaviour; needs view edits | 171 / 45 | manual (later) |
| JS legacy `odoo.define` | `16-17.js.odoo-define-legacy-form` | detect | module-system rewrite | 820 / 794 | manual |
| `<act_window>` / `<report>` tags | 2 rows | detect | none found in official 16.0 | 0 | T5 (low) |
| Manifest version prefix | legacy fixer | **fixed** (works) | n/a | n/a | keep |
| Warning import, SavepointCase | 2 FIX_ENABLED rows | **fixed** | n/a | 0, 1 | keep |
| Manifest load order, missing data file, ACL, record rules, view refs | ~10 rows | detect | judgement needed | n/a | manual |
| Generated DRAFT rules | 2,786 | inert | no replacement (0 carry one); noisy names such as `__init__` | n/a | not convertible |
| **Legacy XML fixer (defect)** | `apply_xml_fixes` | **wrong for 16 -> 17** | rewrites `<tree>` -> `<list>`, `view_mode`, chatter without checking the target; verified with `--dry-run` | 560 `<tree>` / 344 | **T0** |

Upper bound from the measured counts above (arithmetic, not achieved coverage): attrs + states + mail.channel are
4,620 of 6,199 counted instances of the eight measured patterns = 74.5 %. Reaching 90 % by instance count would also need
JS `odoo.define` (13 %) or the field `states=` parameter. This must be decided with data after T2 and T4 are measured.

## 2. Architecture decisions

* **AD-1 Experimental registry, KB untouched.** A code table maps a shipped rule id to an experimental fixer. The run
  flag `--experimental-fixes` (valid only with `--fix`) binds the fixer to the existing detector. KB maturity stays
  `DETECT_ONLY`; no certification record, no `auto-cert:`, no change to `fix_row_trusted`, `promote`, import or
  activation. Without the flag nothing changes.
* **AD-2 Fixers are deterministic span-edit functions** `(document, ctx, **params) -> edits`, built on
  `transformers/xml.py` and `transformers/modifiers.py` (no regex over raw text). A fixer either returns edits or
  returns nothing with a reason; it never guesses. A second application returns no edits.
* **AD-3 Reuse existing safety scaffolding**: `--dry-run`, `--backup`, `rollback`, `resume`, per-file atomic writes,
  validators L1 to L3. Nothing new is built for recovery.
* **AD-4 Reporting.** Each edit and each finding carries `fix_class` in {`certified`, `legacy`, `experimental`}. The
  summary gains an `experimental` block: rules enabled, edits applied, elements refused with reason. Refused elements
  stay open findings for the developer.
* **AD-5 Bug fix first.** The legacy XML fixer is gated by the target version (T0). This changes `--fix` output for
  targets below 18 and is a defect fix, not a trust-model change.
* **AD-6 Semantics policy for attrs (T2).** Start with the strict subset (below). Widen only from measured refusal
  data and only by owner decision; do not use the `falsy` shortcut or the `(existing) or (new)` combination silently.

## 3. Strict subset for attrs / states (T2, slice 1)

Convert only when all hold: the element is in a plain `<form>` view (not inside a nested list/kanban/search); keys
are `invisible`, `readonly`, `required`; every leaf is `(field, op, literal)` with op in `=`, `!=`, `in`, `not in`
and a non-falsy literal (not `False`, `None`, `0`, `''`) or a list of them; operators `&`, `|`, `!` only;
the field is a bare identifier (no `parent.x`, no context names); the element has no existing modifier attribute of
the same key. `states="a,b"` becomes `invisible="state not in ['a','b']"` only when the element has no `invisible`
and no `attrs`. Everything else: no edit, a refusal reason in the report.

## 4. Prioritized tasks (dependency order)

* **T0** Version-gate the legacy XML fixer (`<tree>`/`<list>`, view_mode, chatter by `to_version >= 18`); pass
  `to_version` through `legacy_adapter`. Keep the `to_version=19` default so existing callers and tests are unchanged.
* **T1** Experimental plumbing: `--experimental-fixes`, run param, `rules/experimental/` registry, binder extension,
  report fields. Default-off equivalence tests. No fixer yet beyond a test double.
* **T2** attrs/states experimental fixer on the strict subset, registered for the two shipped rule ids.
* **T3** Corpus runner and differential evaluator (measure conversion, refusals, evaluator mismatches, idempotence).
* **T4** mail.channel family fixer limited to model-name positions (`model=`, `_inherit`, `env[...]`, `res_model`,
  `comodel_name`, ACL external ids `model_mail_channel*`).
* **T5** `<act_window>`/`<report>` tag conversion, only if a corpus shows real use.

First bounded slice for this run: **T0, T1, T2** (T3 acceptance checks inside T2's tests; the full corpus run is a
follow-up).

## 5. Acceptance criteria for the first slice

* AC-0 `migrate --fix --dry-run` 16 -> 17 on a module with `<tree>`, `view_mode` `tree,form` and a chatter block plans
  no `<list>` and no chatter edit; 17 -> 18 and 18 -> 19 behaviour is unchanged (existing regression and golden tests
  pass).
* AC-1 Without `--experimental-fixes`, every existing test passes and a fixture run is byte-identical to the baseline.
* AC-2 `--experimental-fixes` without `--fix` is refused with a clear message.
* AC-3 With both flags, supported `attrs`/`states` elements are converted; the report shows `fix_class=experimental`,
  rule id, before and after for each; unsupported elements are untouched and listed with a reason.
* AC-4 A second pass applies 0 edits and leaves the tree byte-identical.
* AC-5 Certified status unchanged: KB rows keep `DETECT_ONLY`; `knowledge status` FIX_ENABLED count unchanged.
* AC-6 Converted output contains no `@attrs` and no `@states` on converted elements (the 17.0 `_check_xml` rule), and a
  differential check of old domain vs new expression over a small value universe shows 0 mismatches for the subset.
* AC-7 Refusal tests for each excluded case (falsy literal, dotted field, context name, existing modifier, nested list).

## 6. Safety boundaries that must not change

Provenance and pinned revisions; `fix_row_trusted` and the `auto-cert:` contract; human-only `promote`; fail-closed
KB import and activation; certified-only behaviour of plain `--fix`; confidentiality of Enterprise-derived output; no AI
in fixers; deterministic output; no edits for `DETECT_ONLY` rules without the explicit experimental flag.

## 7. Measured coverage definition (to be filled by T3, not estimated)

Corpus: a fixed list of official 16.0 modules copied from the cached snapshot plus `kbi_demo` fixtures. For each rule
family: instances detected, instances auto-fixed correctly, instances refused (with reason), developer-required.
Coverage = auto-fixed correctly / detected, per family and overall, reported separately for certified and experimental
fixes. Where the official 17.0 module migrates the same element, compare semantically as an upstream oracle.
