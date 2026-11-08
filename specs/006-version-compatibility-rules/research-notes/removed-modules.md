# Removed core modules and successors (T068, 2026-11-07)

Scope: `core_modules.json` list diffs for consecutive pinned SHAs (12.0..19.0): 236 modules removed over 7 steps.
Rule: a successor is recorded only with an official file at the pinned SHA that supports it. Otherwise "none found".

## Method

1. Diff `modules` of each version against the next (step 12-13 to 18-19).
2. Fetch each removed module's `__manifest__.py` at the SOURCE SHA via raw.githubusercontent.com (236 of 236 fetched) and grep for
   replac|deprecat|merged|moved|renam|successor|obsolete|superseded|instead|migrat.
3. For the three named modules also compare the data files and the target version's replacement candidates by hand.

Limit: this does not read release notes, commit history or migration scripts. "None found" means no official evidence located by
this method, not proof that no successor exists.

## Successors with evidence (recorded as `replaced_by`)

| Step | Removed | Successor | Evidence | Basis |
|---|---|---|---|---|
| 15-16 | payment_transfer | payment_custom | EV-520 | Same record moves: 15.0 `payment.payment_acquirer_transfer` (payment_transfer data, L4) becomes 16.0 `payment.payment_provider_transfer` (payment_custom data, L4, `custom_mode` wire_transfer L9; payment data `module_id` -> `base.module_payment_custom` L249). Derived from the record move, not an explicit statement: review required. |
| 14-15 | l10n_be_invoice_bba | l10n_be | EV-521 | 14.0 manifest L7: "This module is empty. It is merged whith l10n_be ..." (explicit). |

## No successor found

- payment_test (15-16): 16.0 has payment_demo, but the 15.0 record (`payment_acquirer_test`, provider `test`) and the 16.0 record
  (`payment_provider_demo`, name "Demo") differ in id and name and no official file links them. Not accepted without a statement.
- sale_coupon (15-16): 15.0 depends on `coupon`, `sale`; 16.0 has `loyalty` and `sale_loyalty`, but no manifest or comment states
  a replacement. Not accepted. (Same for coupon, sale_coupon_delivery, website_sale_coupon*, pos_coupon, *gift_card.)
- test_pylint (12-13): manifest says "Deprecated empty module in favor of test-lint". `test-lint` is not a module technical name
  (`test_lint` exists); mapping would need a hyphen/underscore inference, so not accepted.
- Deprecated without a named successor: odoo_referral_portal, payment_alipay, payment_ogone, payment_payulatam, payment_payumoney.
- Keyword false positives, no successor: payment_adyen_paybylink, base_address_city, website_sale_picking, l10n_id_efaktur.
- All other removed modules (no matching text in their manifest): none found.

## Consequence

`replaced_by` is populated for 2 entries only (EV-520 at 16.0, EV-521 at 15.0). Every other removed module stays "no successor known".
