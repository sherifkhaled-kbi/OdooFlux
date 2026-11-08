# Amendment review (006, 2026-11-07)

For the owner. The amendment is spec-only; nothing is implemented.

## Decisions needing sign-off

- D-A1: Accept the `bind_rule(meta, modules, run_params=None)` interface change (FR-017; backward compatible, tested by T060).
- D-A2: Bind `*.manifest.version-prefix` per run as DETECT_ONLY/review_required (FR-019).
- D-A3: Whether the version-prefix fixer may ever become FIX_ENABLED (REQ-MAN-002 opt-out). Recommendation: not now.
- D-A4: Accept the renamed-model DETECT_ONLY family and the proposed IDs (Group D).
- D-A5: AUTO_TRANSFORM for any renamed-model rule. Recommendation: no, DETECT_ONLY, until T066/T067 show a mechanical, ambiguity-free mapping.
- D-A6: Schema change adding `replaced_by` to core-module lists (FR-020).
- D-A7: Adding a view-index data set and `tools/extract_view_index.py` (FR-021), including its size budget.
- Decision rule for AUTO_TRANSFORM vs DETECT_ONLY (spec.md amendment): confirm.

## Unchanged and pending human review

- T025 peer review (T025-review-packet.md), T035/T044 golden-case review, T059 quickstart run. This amendment does not alter, satisfy or bypass them.

## Startable now (no owner decision)

Tests: T060..T064 (write failing tests; synthetic data only). Research: T065..T070 (read-only, produce notes/candidate evidence; creating real evidence records still follows the normal review).

## Needs acceptance first

T071 (D-A1), T072 (D-A2, T071), T073/T074 (D-A4), T075 (D-A6), T076 (D-A7), T077, T078; any fixer or FIX_ENABLED promotion (D-A3, D-A5).

## Owner decisions recorded (2026-11-07, ADR-018)

| ID | Decision |
|---|---|
| D-A1 | APPROVED: `bind_rule(meta, modules, run_params=None)`; backward compatible, validated, conflicts rejected, missing inputs -> INFO gap, non-regression tests for all existing rules |
| D-A2 | APPROVED: version-prefix rule DETECT_ONLY using per-run parameters |
| D-A3 | NOT APPROVED for now: no automatic version-prefix rewriting (reconsider after evidence, ambiguity analysis, golden tests) |
| D-A4 | APPROVED: renamed-model DETECT_ONLY family with evidence refs and review-required diagnostics |
| D-A5 | NOT APPROVED for now: no automatic renamed-model transformation; detection should cover related fields, XML refs, ACLs where evidence supports |
| D-A6 | APPROVED: optional `replaced_by` on removed-module records; never inferred without authoritative evidence |
| D-A7 | APPROVED: version-pinned view index and `tools/extract_view_index.py`; unavailable index is not proof of XPath compatibility |

T025, T035, T044 remain pending independent human review.
