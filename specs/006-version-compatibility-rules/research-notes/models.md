# Renamed-model research (T065, T066, T067)

Date 2026-11-07. Evidence records EV-500..EV-515 (all `DOCUMENTED_NOT_TESTED`, verified location by location with `tools/verify_evidence.py`: 82 locations, 0 failures). Companion of EV-450.

## Method (T065)

1. For each pinned SHA of odoo/odoo 15.0 to 19.0 (`official_sources/revisions.json`), list files with the GitHub tree API (`git/trees/<sha>:addons?recursive=1`, none truncated; plus `odoo/addons/base`). No clone.
2. Fetch every `addons/*/{models,wizard,wizards}/*.py` and `odoo/addons/base/{models,wizard}/*.py` from `raw.githubusercontent.com` at the SHA (10,507 addon blobs, deduplicated by blob id, plus the base addon files) and extract single-line `_name = '<literal>'` declarations.
3. Per step, list names removed and added, then compare files (same file now declaring another name, file replaced by a similarly named file). Each accepted rename was then re-fetched by `tools/verify_evidence.py`.

Scope limits (do not read absence of a candidate as proof): Community repository only; single-line literal `_name` only; no `controllers/`, `report/`, `tests/` model files outside `models/` and `wizard(s)/`; no Enterprise. Test-only models (`mail.test.*`, `export.*`, `import.*`) are noise. The earlier statement "only payment.acquirer verified" was incomplete: the scan finds the renames below.

## Candidate table

Accepted = `_name` present at the old SHA, absent from the whole scanned tree at the new SHA (path 404 or no line match), present at the new SHA under the successor name in the continuing file; ACL model external id changes in step. Bound = a DETECT_ONLY rule exists.

| Step | Old model | New model | Evidence | Bound |
|---|---|---|---|---|
| 15-16 | payment.acquirer | payment.provider | EV-450 | yes |
| 15-16 | payment.acquirer.onboarding.wizard | payment.provider.onboarding.wizard | EV-500 | yes |
| 15-16 | sale.payment.acquirer.onboarding.wizard | sale.payment.provider.onboarding.wizard | EV-501 | yes |
| 15-16 | stock.location.route | stock.route | EV-502 | yes |
| 15-16 | stock.production.lot | stock.lot | EV-503 | yes |
| 15-16 | mail.channel.partner | mail.channel.member | EV-504 | yes |
| 16-17 | mail.channel | discuss.channel | EV-505 | yes |
| 16-17 | mail.channel.member | discuss.channel.member | EV-506 | yes |
| 16-17 | mail.channel.rtc.session | discuss.channel.rtc.session | EV-507 | yes |
| 17-18 | mail.shortcode | mail.canned.response | EV-508 | yes |
| 17-18 | mail.partner.device | mail.push.device | EV-509 | yes |
| 18-19 | stock.quant.package | stock.package | EV-510 | yes |

Seen in the scan but NOT accepted (name pair suggested by the removed/added lists only; purpose and fields were not compared, so no evidence record and no rule): 15-16 `website.sale.payment.acquirer.onboarding.wizard` (no successor name added), `coupon.*` and `gift.card` (loyalty.* added), `account.analytic.default`/`group`/`tag`, `account.tax.report*`; 17-18 `mail.notification.web.push` (mail.push added), `pos.combo*` (product.combo* added); 18-19 `hr.attendance.overtime`, `procurement.group`, `hr.contract`, `product.packaging`. Some removals have no added successor in the lists at all (for example `account.account.type`, `uom.category`, `res.partner.title`) and were not examined further. Each needs its own evidence before a rule (gap for T078).

## Follow-ons of payment.acquirer (T066)

| Follow-on | Mapping | Evidence | Status |
|---|---|---|---|
| Model name in Python and XML | payment.acquirer to payment.provider | EV-450 | rule |
| Model external id (ACL `model_id:id`, XML `ref`) | payment.model_payment_acquirer to payment.model_payment_provider | EV-511, EV-515 | rule (qualified form only) |
| Wizard model and its ACL id | see EV-500 | EV-500 | rule |
| View id | payment.payment_acquirer_form to payment.payment_provider_form | EV-450, EV-513 | rule (this id only) |
| Fields | acquirer_id to provider_id; provider to provider_code (payment.transaction, payment.token) | EV-512 | evidenced, no rule: a bare `acquirer_id` also occurs on custom models and needs model context |
| ACL row id `payment_acquirer_system`, ir.rule record id `payment_acquirer_company_rule` | to `payment_provider_*` | EV-511 | unmapped: ids defined by the payment module, not references from custom code |
| Other payment/website_payment view, menu and data ids | not researched | none | unmapped |
| Database table | payment_acquirer to payment_provider | EV-514 (derivation from `_name`) | unmapped: no file maps data; raw SQL strings are not rewritten |
| Unqualified `model_payment_acquirer` | depends on the declaring module | none | not flagged (see T067) |

EV-515 shows the model external id is `<module>.model_<_name with underscores>` at 15.0 through 19.0, which is what lets every instance map its qualified id.

## False-positive and ambiguity decision (T067)

Decision: all renamed-model rules are DETECT_ONLY with `review_required: true`; no AUTO_TRANSFORM, in line with D-A5 (not approved). No safe mapping was shown:

- A custom model may be named like the old one (`my.payment.acquirer`, `payment.acquirer.custom`, `x_payment.acquirer`). Detectors match whole names only (tested); a custom module that really declares `_name = 'payment.acquirer'` is still reported, which is intended (it collides with the upgrade) but would be wrongly rewritten.
- A model name appears in strings that are not references (log text, labels, domains on a `model` field). Detection is limited to `_name`/`_inherit`/`_inherits`, `env[...]`, relational field comodel arguments, XML `model`/`res_model`, and ids from the evidence maps; a name held in a variable is missed.
- A rewrite of the model name alone would leave `acquirer_id`, `provider`, ACL row ids, unqualified ids and tables (EV-512, EV-511, EV-514) inconsistent, and which of them apply depends on the model of the field.
- Renames occur together with restructuring (file moves, new fields); successor semantics were not compared, so "same model, new name" is not proven for field-level code.
- Multi-step runs: each rule is bound to its own step, so a 15 to 19 run reports a reference once at the step where the rename happens; later steps flag only their own old names.

Recommendation: keep DETECT_ONLY. Revisit only with a new task after D-A5, limited to Python string literals in the exact forms the detector reports, with the follow-ons above reviewed by a human.
