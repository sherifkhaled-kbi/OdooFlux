# Contract: Edit engine (`src/odooflux/core/engine/edits.py`)

## `apply_edits(document, edits, *, precedence) -> EditBatchResult`

Preconditions:
- Every edit has the required fields (CONTRACTS.md §Edit), `edit.path == document.path`, and
  `0 ≤ start ≤ end ≤ len(text)`. Otherwise the edit is rejected with `invalid-edit:<field>`.

Algorithm (normative):
1. Reject stale edits: `text[start:end] != before` → `stale-span`.
2. Sort the remaining edits by `(start, end, rule_order, id)`.
3. Overlap detection: two edits overlap iff `a.start < b.end and b.start < a.end`. A zero-length
   insertion overlaps a non-empty edit iff `a.start < ins.start < a.end`. Adjacent spans do not
   overlap.
4. Resolve each overlap group: keep the edit with the highest `severity`, then earliest in
   `depends_on` order. If still tied, reject all edits in the group with
   `conflict:<ids>`.
5. Apply the kept edits from the highest `start` to the lowest.
6. Byte-preservation check: rebuild the expected output from the input segments outside spans
   and the edit `after` texts. Compare with the produced text, and encode with the original
   encoding/BOM/newline (`preserved_ok`).
7. Return `EditBatchResult`. The input document is never mutated.

Postconditions:
- `applied ∪ rejected` = input edits.
- Every rejected edit has a `rejection_reason`.
- `preserved_ok` is true unless an internal error occurred; false aborts the batch (all edits
  rejected with `internal-preservation-failure`).

## `idempotence_check(rules, document, context) -> list[Edit]`

Runs detect+fix on `document`, applies, runs detect+fix again on the result, and returns the
second-pass edits (must be empty).

## Errors

The engine never raises for edit-level problems; it rejects edits. It raises only on programming
errors (wrong types), which tests cover.
