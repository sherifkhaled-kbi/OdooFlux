# Contract: Change Ledger

Module: `src/odooflux/knowledge/ledger/` (REQ-KAP-014, 030, 031). Data model: ChangeRecord.

## API

```
Ledger.create(step, from_snapshot, to_snapshot, drafts) -> Ledger     # assigns ids, UNRESOLVED
Ledger.load(path) / save(path)                                        # canonical JSON, atomic write
Ledger.get(change_id) -> ChangeRecord
Ledger.set_disposition(change_id, disposition, *, actor, rationale=None, rule_ids=(), evidence_ids=())
Ledger.confirm(change_id, *, actor)                                    # only for rename/replacement candidates
Ledger.merge(previous_ledger) -> MergeReport                           # incremental builds
Ledger.unresolved() -> list
Ledger.verify() -> list[Finding]                                       # invariants, history chain
```

## Rules

1. Ids come from `ids.py` (research R2) and never change; drafts that map to an existing id keep prior disposition and history (merge).
2. Initial disposition is `UNRESOLVED`. Setting `NO_CUSTOM_MODULE_IMPACT` or `HUMAN_REVIEW` requires non-empty `rationale`. Setting `RULE_CREATED`/`EXISTING_RULE_LINKED` requires at least one existing `rule_id` present in the tree being built. `DETECTION_ONLY` requires a DETECT_ONLY rule id.
3. Every mutation appends a history entry with `prev_hash` (sha256 of previous entry canonical JSON). Removing or editing a past entry fails `verify`.
4. `confirm` is refused for classes other than RENAMED_CANDIDATE and REPLACEMENT_CANDIDATE, and refused when actor is `AI`.
5. A change present in the previous ledger and absent from the new one is carried as `STALE` in the merge report; it is never deleted. Disposition of unchanged ids is preserved byte for byte (REQ-KAP-030).
6. Manual versus automatic: a disposition set by `MANUAL` is not overwritten by `DETERMINISTIC` merge; the proposed alternative goes to `conflicts` in the merge report (REQ-KAP-031).
7. Sorted by `change_id`; `ledger_digest` covers entries except `history` timestamps? No: history is included; timestamps come from a supplied clock (`SOURCE_DATE_EPOCH` for builds).
8. Unresolved changes are always listed in the coverage manifest; omitting them is a G-DISP failure.

## Files

`<release>/ledger/<step>.ledger.json`; schema `change_ledger.schema.json`.

## Tests

`test_ids_stable`, `test_unresolved_default`, `test_rationale_required`, `test_disposition_requires_rule`, `test_history_chain_tamper`, `test_confirm_refused_for_ai`, `test_merge_preserves_manual`, `test_stale_never_deleted`.
