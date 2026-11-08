"""Edit engine: validate, reject stale spans, resolve overlaps, splice, verify preservation.

Normative algorithm: specs/005-structured-transformations/contracts/edit-engine.md (REQ-TRF-001..004).
Edits are never applied to the caller's objects: results are new ``Edit`` values.
"""

import dataclasses
from dataclasses import dataclass
from typing import Sequence

from odooflux.core.contracts.records import SEVERITIES
from odooflux.core.engine.documents import Document


@dataclass(frozen=True)
class Edit:
    """One span replacement. Missing required fields are reported at apply time, not at construction.

    ``severity`` is one of ``SEVERITIES``; ``validation`` is the list of validator IDs to run after the
    edit. ``status`` is ``PLANNED`` on input and ``APPLIED`` or ``REJECTED`` on output.
    """

    id: str = ""
    rule_id: str = ""
    path: str = ""
    start: int | None = None
    end: int | None = None
    before: str | None = None
    after: str | None = None
    severity: str = ""
    step: str = ""
    validation: tuple | None = None
    finding_ids: tuple = ()
    status: str = "PLANNED"
    rejection_reason: str = ""


@dataclass(frozen=True)
class EditBatchResult:
    applied: tuple
    rejected: tuple
    text: str
    preserved_ok: bool


def _is_offset(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _field_error(edit: Edit, document: Document):
    """Return ``invalid-edit:<field>`` for the first missing or malformed required field, else None."""
    checks = (
        ("id", isinstance(edit.id, str) and edit.id != ""),
        ("rule_id", isinstance(edit.rule_id, str) and edit.rule_id != ""),
        ("step", isinstance(edit.step, str) and edit.step != ""),
        ("path", edit.path == document.path),
        ("severity", edit.severity in SEVERITIES),
        ("validation", isinstance(edit.validation, (list, tuple))),
        ("start", _is_offset(edit.start)),
        ("end", _is_offset(edit.end)),
        ("before", isinstance(edit.before, str)),
        ("after", isinstance(edit.after, str)),
    )
    for field, ok in checks:
        if not ok:
            return f"invalid-edit:{field}"
    if edit.start > edit.end:
        return "invalid-edit:start"
    if edit.end > len(document.text):
        return "invalid-edit:end"
    try:
        edit.after.encode(document.encoding, errors="surrogateescape")
    except UnicodeEncodeError:
        return "invalid-edit:after"
    return None


def _rejected(edit: Edit, reason: str) -> Edit:
    return dataclasses.replace(edit, status="REJECTED", rejection_reason=reason)


def _overlaps(a: Edit, b: Edit) -> bool:
    return a.start < b.end and b.start < a.end


def _sort_key(edit: Edit, rank: dict):
    return (edit.start, edit.end, rank.get(edit.rule_id, len(rank)), edit.id)


def _resolution_key(edit: Edit, rank: dict):
    return (SEVERITIES.index(edit.severity), rank.get(edit.rule_id, len(rank)))


def _overlap_groups(edits: Sequence[Edit], indices: list, rank: dict) -> list:
    """Connected components of the overlap relation. Sorted by start, so the inner loop can stop early."""
    parent = {i: i for i in indices}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ordered = sorted(indices, key=lambda i: _sort_key(edits[i], rank))
    for pos, i in enumerate(ordered):
        for j in ordered[pos + 1:]:
            if edits[j].start >= edits[i].end:
                break
            if _overlaps(edits[i], edits[j]):
                parent[find(j)] = find(i)
    groups = {}
    for i in ordered:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _resolve_overlaps(edits: Sequence[Edit], valid: list, rank: dict):
    """Return (kept indices, {rejected index: reason})."""
    kept, rejected = [], {}
    for group in _overlap_groups(edits, valid, rank):
        if len(group) == 1:
            kept.append(group[0])
            continue
        best = min(_resolution_key(edits[i], rank) for i in group)
        winners = [i for i in group if _resolution_key(edits[i], rank) == best]
        if len(winners) > 1:
            reason = "conflict:" + ",".join(sorted(edits[i].id for i in group))
            rejected.update({i: reason for i in group})
            continue
        winner = winners[0]
        kept.append(winner)
        rejected.update({i: f"conflict:{edits[winner].id}" for i in group if i != winner})
    return kept, rejected


def _splice(text: str, ordered: list) -> str:
    """Build the output from the input segments outside the spans and the ``after`` texts."""
    pieces, pos = [], 0
    for edit in ordered:
        pieces.append(text[pos:edit.start])
        pieces.append(edit.after)
        pos = edit.end
    pieces.append(text[pos:])
    return "".join(pieces)


def _reference_splice(text: str, ordered: list) -> str:
    """Independent second computation (right-to-left replacement) used by the preservation check."""
    out = text
    for edit in reversed(ordered):
        out = out[:edit.start] + edit.after + out[edit.end:]
    return out


def _preserved(document: Document, text: str, ordered: list) -> bool:
    if _reference_splice(document.text, ordered) != text:
        return False
    body = text.encode(document.encoding, errors="surrogateescape")
    return body.decode(document.encoding, errors="surrogateescape") == text


def apply_edits(document: Document, edits: Sequence[Edit], *, precedence: Sequence[str]) -> EditBatchResult:
    """Apply a batch of edits to ``document``.

    ``precedence`` lists rule IDs in ``depends_on`` order (earliest first). Rules not listed rank after
    all listed rules. Overlap winners are chosen by severity, then precedence; a tie rejects the group.
    """
    edits = list(edits)
    results = [None] * len(edits)
    valid = []
    for i, edit in enumerate(edits):
        reason = _field_error(edit, document)
        if reason is None and document.text[edit.start:edit.end] != edit.before:
            reason = "stale-span"
        if reason is None:
            valid.append(i)
        else:
            results[i] = _rejected(edit, reason)

    rank = {}
    for rule_id in precedence:
        rank.setdefault(rule_id, len(rank))

    kept, conflicts = _resolve_overlaps(edits, valid, rank)
    for i, reason in conflicts.items():
        results[i] = _rejected(edits[i], reason)

    ordered = [edits[i] for i in sorted(kept, key=lambda i: _sort_key(edits[i], rank))]
    text = _splice(document.text, ordered)
    if not _preserved(document, text, ordered):
        failed = tuple(_rejected(edit, "internal-preservation-failure") for edit in edits)
        return EditBatchResult(applied=(), rejected=failed, text=document.text, preserved_ok=False)

    kept_set = set(kept)
    for i in kept_set:
        results[i] = dataclasses.replace(edits[i], status="APPLIED")
    applied = tuple(r for r in results if r.status == "APPLIED")
    rejected = tuple(r for r in results if r.status == "REJECTED")
    return EditBatchResult(applied=applied, rejected=rejected, text=text, preserved_ok=True)


def propose_edits(rules, document: Document, context) -> list:
    """Run detect then fix for every rule. Rules are objects with ``rule_id``, ``detect`` and ``fix``."""
    proposals = []
    for rule in rules:
        for finding in rule.detect(document, context):
            proposals.extend(rule.fix(document, finding, context))
    return proposals


def idempotence_check(rules, document: Document, context) -> list:
    """Apply the rules to ``document``, re-run them on the result, and return the second-pass edits.

    An idempotent rule set returns an empty list (REQ-TRF-003).
    """
    rules = list(rules)
    first = apply_edits(document, propose_edits(rules, document, context),
                        precedence=[rule.rule_id for rule in rules])
    return propose_edits(rules, document.with_text(first.text), context)
