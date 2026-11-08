"""ACL CSV scanner (REQ-ACL-001, research R-8): ``ir.model.access.csv`` structure.

``parse_acl`` yields the data rows with their line numbers. ``flag_acl_issues`` is detect-only and reports a
header without the required columns, a short row, a permission that is not 0 or 1, a duplicate ``id`` and a
``model_id:id`` that is not a ``model_*`` XML ID. Renamed field names inside ACL files are found by
``security.field_refs.flag_field_reference``.
"""

import csv
import io
from dataclasses import dataclass

from odooflux.core.engine.documents import Span
from odooflux.rules.shared.emit import finding

REQUIRED_COLUMNS = ("id", "name", "model_id:id", "perm_read", "perm_write", "perm_create", "perm_unlink")
PERM_COLUMNS = ("perm_read", "perm_write", "perm_create", "perm_unlink")


@dataclass(frozen=True)
class AclRow:
    line: int
    offset: int       # character offset of the row start
    values: dict      # column -> raw value; missing trailing columns are absent


def _rows(text: str):
    """(header, [(line, offset, cells)]) for the non-blank records."""
    reader = csv.reader(io.StringIO(text, newline=""))
    records, offsets = [], []
    line_starts = [0]
    for index, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(index + 1)
    for cells in reader:
        line = reader.line_num
        # reader.line_num is the last physical line of the record; quoted newlines are rare in ACL files
        records.append((line, line_starts[min(line - 1, len(line_starts) - 1)], cells))
    records = [r for r in records if any(c.strip() for c in r[2])]
    return (records[0][2], records[1:]) if records else ([], [])


def parse_acl(document) -> list:
    header, records = _rows(document.text)
    header = [h.strip() for h in header]
    return [AclRow(line, offset, {h: c for h, c in zip(header, cells)}) for line, offset, cells in records]


def flag_acl_issues(document, ctx):
    text = document.text
    header, records = _rows(text)
    if not header:
        return []
    cols = [h.strip() for h in header]
    found = []
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        found.append(finding(document, ctx, Span(0, len(text.split("\n", 1)[0]))))
    seen = set()
    for line, offset, cells in records:
        span = Span(offset, offset + len(text[offset:].split("\n", 1)[0].rstrip("\r")))
        row = dict(zip(cols, cells))
        problem = len(cells) < len(cols)
        if not missing:
            problem = problem or any(row.get(p, "").strip() not in ("0", "1") for p in PERM_COLUMNS)
            model = row.get("model_id:id", "").strip()
            problem = problem or (model and "." not in model and not model.startswith("model_"))
            problem = problem or (model and "." in model and not model.split(".", 1)[1].startswith("model_"))
            rid = row.get("id", "").strip()
            problem = problem or rid in seen
            seen.add(rid)
        if problem:
            found.append(finding(document, ctx, span))
    return found
