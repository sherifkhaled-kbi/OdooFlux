# Independent review package for golden expected outputs (spec 006 T035 / T044)

Status: **NOTHING HERE IS AUTHORITATIVE UNTIL APPROVED.** Every case is `PENDING_INDEPENDENT_REVIEW`.
Proposals in `cases/*.json` were written by reading the pinned source and the rule evidence. OdooFlux was
never run to produce them, and no tool output was copied. They must not be copied into
`tests/golden_fixtures/**/expected` until approved.

## Layout
- `INDEX.md`: table of the 42 cases (12 modules x later targets) with source file hashes.
- `cases/<src>__<module>__to_<tgt>.json`: one record per case.

## Reviewer checklist (qualified Odoo migration engineer, not the author of the rules or proposals)
1. Fetch inputs (`tools/fetch_golden_corpus.py`) and verify each file sha256 and the pinned revision.
2. Read the source files yourself; do not run OdooFlux first.
3. For each case, confirm against official Odoo source/release notes of every step in `steps`:
   - the rules listed in `applicable_rule_ids` really apply, and no unlisted rule should apply;
   - for FIX_ENABLED rules, the proposed diff is exactly what a correct migration does;
   - for DETECT_ONLY/DRAFT/partial evidence, expected is report-only (no edits) with the stated finding(s);
   - `unresolved_ambiguities` are resolved (record the decision in `reviewer_notes`) or the case stays pending/rejected.
4. Check gaps with no rule (e.g. payment.acquirer rename, manifest version prefix, dependency/xpath anchors in later series) and decide the expected behaviour explicitly.
5. Confirm byte-level expectations (whitespace, encoding, line endings) are stated for any edit.

## Approving
Set in the case JSON: `review_status` to `APPROVED` (or `REJECTED`), `reviewer` (name), `review_date` (YYYY-MM-DD),
`reviewer_qualification`, and `reviewer_notes`. Approval must be a separate commit by the reviewer. Only then may
expected trees be generated from the approved description. The unit test `tests/unit/test_golden_review_package.py`
enforces PENDING status while the package is unreviewed; update it as part of the approval change.
