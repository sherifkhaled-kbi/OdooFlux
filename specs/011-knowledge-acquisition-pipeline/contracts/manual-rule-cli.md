# Contract: Manual Rule CLI

Module: `src/odooflux/knowledge/authoring/` and `src/odooflux/cli/kap_rule.py` (REQ-KAP-018..021, 031).

Operates on a **working tree**: `--path` (a release staging tree or any knowledge tree). It never edits the built-in package tree unless `--path` points at it explicitly, and then prints a warning (maintainer use). Installed releases are immutable: edits go to a new staging tree that is built into a new release.

## Verbs (`odooflux knowledge rule ...`)

| Verb | Key options | Effect |
|---|---|---|
| create | `--from-file rule.json` or flags (`--id --step --category --detector-ref --params`), `--evidence EV-..` | validates, writes rule row with `origin MANUAL`, `maturity DRAFT` (DETECT_ONLY if tests supplied and pass), history `create` |
| edit | `--id`, `--set key=value` or `--from-file` | new revision; `maturity` cannot be raised to FIX_ENABLED here |
| disable / enable | `--id --reason` | toggles `DRAFT`-equivalent skip via `maturity` DRAFT with recorded previous maturity |
| retire | `--id --reason [--superseded-by ID]` | maturity RETIRED, `retired_reason` set |
| inspect | `--id [--json]` | rule row, linked evidence status, history head, validation status |
| validate | `[--id]` | schema + checks; exit 1 on errors |
| history | `--id` | list revisions, verify chain |
| link-evidence | `--id --evidence EV-..` | adds ref (evidence must exist); records change |
| add-test | `--id --kind positive|negative|idempotence --fixture path` | registers test ref; fixture copied under `fixtures/` with sha256 |
| promote | `--id --to FIX_ENABLED --approval REF` | runs gates (below); the only path to FIX_ENABLED (REQ-KAP-018) |

## Same schema and validator

Every verb ends by running `validate_knowledge` (existing `knowledge/validator.py` + `checks.py`) and the authoring checks on the resulting tree; the write is rolled back on ERROR (write to temp then atomic rename).

## Duplicate and conflict checks (authoring/checks.py)

| Code | Condition |
|---|---|
| A001 | duplicate rule id |
| A002 | same step + `detector_ref` + canonical `params` as another active rule |
| A003 | `conflicts_with` / `depends_on` references an unknown rule |
| A004 | `depends_on` cycle |
| A005 | two active rules with same step and overlapping `file_kinds` and same `detector_ref` target (potential double edit) |
| A006 | rule references unknown evidence |
All are errors in non-built-in trees. On the built-in tree they run only with `--strict-builtin` (REQ-KAP-005, OD-K11).

## Promotion gates (`promote`)

1. Linked evidence exists, none `UNVERIFIED` or `CONFLICTING`, at least one `official` record, not sole `AI`/unofficial.
2. Applicability fields present (`step`, source/target versions in evidence).
3. Positive, negative and idempotence tests registered and pass.
4. No A001..A006 error; `conflicts_with` targets not FIX_ENABLED simultaneously.
5. `fixer_ref` set, `review_required` false (SC-005).
6. `--approval` references a non-empty owner approval id (recorded, not verified; ADR-018/019: certification stays human).
Failure prints the failing gates and changes nothing.

## Preservation (REQ-KAP-021)

History sidecar `history/rules/<id>.json` keeps `created_by`, `created_at` fixed from the first entry. `edit` appends; no verb rewrites or deletes entries. Author identity: `--author` or `git config user.name` read once, else `unknown`; never network.

## Generated/manual conflicts

When a build finds a generated candidate colliding (A001/A002/A005) with a MANUAL rule, the manual rule is kept, candidate status `CONFLICT`, listed in `conflicts.json` of the build; resolution verb `knowledge rule resolve --candidate CR-.. --keep manual|candidate|both-renamed`, recorded in history.

## Tests

`test_create_validates`, `test_duplicate_id_rejected`, `test_duplicate_scope_rejected`, `test_edit_preserves_creator`, `test_history_chain`, `test_retire_sets_reason`, `test_promote_gates` (one case per gate), `test_edit_cannot_set_fix_enabled`, `test_add_test_hashes_fixture`, `test_failed_validation_rolls_back`, `test_conflict_manual_wins`.
