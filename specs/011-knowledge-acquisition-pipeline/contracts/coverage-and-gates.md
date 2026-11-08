# Contract: Coverage, Cross-checks and Gates

Module: `src/odooflux/knowledge/coverage/` (REQ-KAP-032..035). Data: CoverageManifest, ReleaseGateResult.

## Metrics

Definitions and denominators: data-model.md table M1..M8. Output form, one line each and in JSON:

```
M2 file_scan  1180/1204  (analyzed / in-scope changed files)  excluded=11 unsupported=9 failed=2 pending=2
```

Rules: denominator 0 gives `NOT_APPLICABLE` (never 100 percent); no combined score; percentages are display only and always printed with the fraction.

## Cross-checks

| Id | Source of independence | Pass condition | Recall reporting |
|---|---|---|---|
| XC-UPGRADE | Odoo `migrations/` scripts between the two revisions: models/fields they rename or drop | each referenced rename/removal appears as a ledger change (any class) | recall = found/referenced, benchmark_id `upgrade-scripts:<step>`, size = referenced count |
| XC-INDEP | tool-independent file listing (`git diff --name-status` equivalent via plain directory walk in the test harness, or `git` plumbing when a clone exists) | file counts equal `FileAccounting.independent_count` per state group | none |
| XC-KB | existing KB rules for the step | each existing rule's subject is either seen in the ledger or listed as `NOT_OBSERVED` with reason | none |
| XC-REGR | `tests/regression` known-regression list (named file) | every listed regression id has a ledger or rule link | named `regression:<file>` |
| XC-BENCH | named benchmark sets (golden corpus 42 cases, synthetic set) | benchmark expected changes found | recall only here, `benchmark_id` and size mandatory |

A cross-check not run is `NOT_RUN`, a recall without named benchmark is `NOT_MEASURED`; both are printed (no silence). The writer refuses to emit a `recall` key without `benchmark_id`.

## Gates

| Gate | Blocking | Fails when |
|---|---|---|
| G-SRC | yes | a `required` source not `VERIFIED` |
| G-FILES | yes | any `PENDING`; invariant INV-3 violated; `FAILED` or `UNSUPPORTED` count above zero (these two may be allowed in `PARTIAL` when listed in `limits`) |
| G-CLASS | yes | classification failures hidden: `FAILED` files without an `UNKNOWN`/`UNRESOLVED` ledger entry |
| G-DISP | yes | `UNRESOLVED` changes missing from the manifest, or ledger count differs from manifest; `UNRESOLVED` present is allowed in `PARTIAL` only with limits |
| G-EVID | yes | change needing evidence has none, or evidence cites unofficial-only source for FIX_ENABLED |
| G-MANIFEST | yes | digests, counts, step lists across release, coverage, ledger, accounting, package disagree |
| G-RULES | yes | schema errors, A001..A006 errors, rules failing tests |
| G-SAFE | yes | INV-5 violated; FIX_ENABLED without gates |
| G-XCHECK | no (WARN) | cross-check FAIL; becomes blocking with `--strict-xcheck` |
| G-SECRETS | yes | redaction scan finding |

## Completeness decision

```
if any blocking gate FAIL not in allowed_partial -> FAILED
elif any blocking gate FAIL (allowed_partial)    -> PARTIAL, limits must name each (non-empty)
else                                             -> COMPLETE
```
`allowed_partial = {G-SRC (optional source only), G-FILES (UNSUPPORTED/FAILED only), G-DISP (UNRESOLVED only)}`. `required` sources are never partial-able. Marketing words "complete" are only emitted for COMPLETE. `COMPLETE` is technical; certification is separate (`PENDING_HUMAN_REVIEW`, ADR-019).

## CLI

`knowledge coverage show --release ID|--path P [--json]`, `knowledge coverage gates`, exit code 1 when FAILED, 0 otherwise (PARTIAL prints limits).

## Tests

`test_metric_<m1..m8>`, `test_zero_denominator_not_applicable`, `test_no_blended_score`, `test_recall_requires_benchmark`, `test_gate_<each>`, `test_partial_requires_limits`, `test_complete_blocked_on_unaccounted_file`, `test_manifest_inconsistency_detected`, `test_xc_upgrade_recall`.

## Open question (M8)

M8 (version transition coverage, data-model.md) is a metric only. No gate covers it: the gate table above has ten gates and none reads declared transitions. The completeness rule ("Completeness decision") is defined only by blocking gates, and REQ-KAP-034's list of blocked claims does not mention transition coverage. This contract therefore does not say whether a declared transition whose steps are not COMPLETE must downgrade a release from COMPLETE.

Current behaviour: M8 is reported as `numerator/denominator` and is recomputed by `check_consistency`, so a stored M8 that disagrees with the ledger and accounting is an inconsistency. A COMPLETE manifest with an incomplete declared transition is not blocked.

Proposed rule, awaiting an owner decision (not implemented): release completeness is the weakest of its declared `steps_covered` entries. `decide` returns PARTIAL, with the incomplete step named in `limits`, when any declared step is not COMPLETE. `check_consistency` fails when the manifest says COMPLETE but a declared step is not. This needs a gate code that the contract does not yet name.
