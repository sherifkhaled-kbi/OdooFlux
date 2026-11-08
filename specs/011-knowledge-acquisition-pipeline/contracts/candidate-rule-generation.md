# Contract: Candidate Rule Generation

Module: `src/odooflux/knowledge/candidates/` (REQ-KAP-015..018, 002, 016).

## Inputs and outputs

In: a Ledger, snapshots (for evidence locations), templates from `knowledge/extraction_templates/*.json`, the tree under construction (existing rules and evidence).
Out: `EvidenceRecord`s (new ids `EV-K<nnnnn>` allocated above the current max, never reusing ids), `CandidateRule`s, ledger dispositions.

## Template (data, not code)

```
{ "template_id": "py-remove-decorator", "match": {"domain": "python_orm", "class": "REMOVED", "kind": "decorator"},
  "rule": {"category": "...", "detector_ref": "python.generic.flag_decorator", "fixer_ref": null,
           "params_from": ["subject.name"], "risk": "MEDIUM", "review_required": true},
  "confidence": "MEDIUM", "tests": {"generate_skeleton": true} }
```

`detector_ref` must name an existing generic detector (feature 006 `rules/*/generic.py`); unknown refs are a template error. Adding a version pair or a new change shape needs only new template data, or a new generic detector in `rules/`, never edits to the generator (REQ-KAP-016).

## Generation steps

1. For each ledger change not yet `RULE_CREATED`/`EXISTING_RULE_LINKED`: find templates by `match` (most specific wins; ties are a template error).
2. If an existing rule has the same step and equivalent (detector_ref, params): set `EXISTING_RULE_LINKED` and link evidence; no new rule.
3. Else build an EvidenceRecord (official source, pinned revision, locations with `content_sha256`, status `DOCUMENTED_NOT_TESTED`, `origin KAP_DETERMINISTIC`) and a CandidateRule with maturity `DETECT_ONLY` when test skeletons exist and pass positive and negative, else `DRAFT`.
4. Candidates never carry `fixer_ref`; `FIX_ENABLED` is unreachable here (REQ-KAP-016 AC2).
5. Classes `RENAMED_CANDIDATE`, `REPLACEMENT_CANDIDATE`, `UNKNOWN` unconfirmed: candidate allowed only as `DETECT_ONLY` with `review_required: true` and wording "candidate"; ledger disposition `HUMAN_REVIEW`.
6. Evidence from `official=false` sources sets rule `review_required: true`, label in `message`, and counts as supplementary only.
7. Output ordering and ids deterministic; two runs byte-identical.
8. Acceptance (`PROPOSED -> ACCEPTED`) runs: schema, dup/conflict (authoring checks), rule tests; failure leaves `PROPOSED` with reasons.

## AI proposer (optional)

`ai_proposer.py`: builds a minimised request of `evidence_excerpt` category only, calls the existing gateway after `authorization` grant check, expects a closed JSON schema reply (`proposed_template_id`, `rationale`), stores items with `origin AI_PROPOSED` under `candidates/ai/`. Forbidden: setting evidence, status, maturity, `confirmed`, ledger disposition other than `HUMAN_REVIEW`. No grant or kill switch: returns `[]` with an INFO event. Provenance of the call (provider, model, category, token counts, no prompt text) goes to the audit log.

## Tests

`test_generation_deterministic`, `test_no_fix_enabled_candidates`, `test_existing_rule_linked`, `test_new_version_pair_no_code`, `test_unofficial_evidence_review_required`, `test_rename_candidate_detect_only`, `test_ai_off_identical_output`, `test_ai_cannot_confirm_or_create_evidence`, `test_ai_no_grant_skips`, `test_template_unknown_detector_ref_error`.
