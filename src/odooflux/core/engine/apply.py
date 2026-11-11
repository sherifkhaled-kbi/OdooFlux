"""Span edits: diff two texts into edits, apply them with ``before`` checks and overlap resolution."""

import difflib
from dataclasses import dataclass, field

from odooflux.core.contracts.records import Edit


@dataclass
class FileEdit:
    """Planned change to one module file. Written only after its text passed validation. ``fixed`` is the text the
    file keeps: the full fix, the valid stages of it when a later stage was refused (``rejection`` names the refused
    stage), or the original text (nothing kept, nothing written)."""

    path: object  # Path of the file as it is in the source module
    dest: object  # Path after the change (differs only for the manifest rename)
    original: str
    fixed: str
    issues: list
    resolved: list = field(default_factory=list)
    rejection: str = ""
    edits: list = field(default_factory=list)
    validation: object = None  # FileVerdict of the fixed text (AD-05); None when the file had no transform


def _line_offsets(text: str):
    offsets, pos = [0], 0
    for line in text.splitlines(keepends=True):
        pos += len(line)
        offsets.append(pos)
    return offsets


def diff_to_edits(path: str, before: str, after: str) -> list:
    """Line-granular span edits that turn *before* into *after* (fine spans come in P4)."""
    a_lines = before.splitlines(keepends=True)
    b_lines = after.splitlines(keepends=True)
    a_off, b_off = _line_offsets(before), _line_offsets(after)
    edits = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a_lines, b_lines, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        start, end = a_off[i1], a_off[i2]
        edits.append(Edit(path=path, start=start, end=end,
                          before=before[start:end], after=after[b_off[j1]:b_off[j2]]))
    return edits


def apply_edits(text: str, edits: list):
    """
    Apply *edits* to *text*. Overlaps: the higher precedence wins; equal precedence rejects both.
    An edit whose ``before`` differs from the current slice is rejected. Returns
    (new_text, applied, rejected); edit statuses are updated in place.
    """
    candidates = sorted(edits, key=lambda e: (e.start, -e.precedence, e.end))
    accepted, rejected = [], []
    for edit in candidates:
        if not (0 <= edit.start <= edit.end <= len(text)):
            edit.status, edit.rejection_reason = "REJECTED", "span outside the text"
            rejected.append(edit)
            continue
        clashes = [a for a in accepted if edit.start < a.end and a.start < edit.end]
        if not clashes:
            accepted.append(edit)
            continue
        if all(edit.precedence > a.precedence for a in clashes):
            for a in clashes:
                a.status, a.rejection_reason = "REJECTED", "overlapped by a higher-precedence edit"
                accepted.remove(a)
                rejected.append(a)
            accepted.append(edit)
        else:
            edit.status = "REJECTED"
            edit.rejection_reason = "overlaps another edit of equal precedence"
            rejected.append(edit)
            for a in clashes:
                if a.precedence == edit.precedence:
                    a.status, a.rejection_reason = "REJECTED", "overlaps another edit of equal precedence"
                    accepted.remove(a)
                    rejected.append(a)
    applied = []
    for edit in sorted(accepted, key=lambda e: e.start):
        if text[edit.start:edit.end] != edit.before:
            edit.status, edit.rejection_reason = "REJECTED", "before text does not match the file"
            rejected.append(edit)
        else:
            applied.append(edit)
    out = text
    for edit in sorted(applied, key=lambda e: e.start, reverse=True):
        out = out[:edit.start] + edit.after + out[edit.end:]
        edit.status = "APPLIED"
    return out, applied, rejected
