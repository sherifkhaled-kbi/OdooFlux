"""Byte-preserving rule file store for compatibility/<step>.rules.json (feature 011, REQ-KAP-019).

Committed rule files mix compact and expanded arrays, so re-serialising a whole file would rewrite untouched rows.
Instead the store slices the top-level array into element spans, keeps every untouched element's exact source bytes,
renders only replaced or appended rows, and writes the result atomically. Everything is validated before the write:
schema (rule_metadata), id uniqueness, and a re-parse of the new text. Any failure leaves the file untouched.
"""

import json
from pathlib import Path

from odooflux.knowledge import validator
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.utils.atomic import atomic_write_bytes

_WHITESPACE = " \t\r\n"


class RuleStoreError(ValueError):
    """The rule file or a requested change is invalid; nothing was written."""


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in _WHITESPACE:
        pos += 1
    return pos


def split_elements(text: str):
    """Return (spans, open_index, close_index) for the top-level JSON array of `text`.

    `spans` holds (start, end) offsets of each element's exact source text, without surrounding whitespace."""
    open_index = _skip_ws(text, 0)
    if open_index >= len(text) or text[open_index] != "[":
        raise RuleStoreError("rules file must be a JSON array")
    decoder = json.JSONDecoder()
    spans = []
    pos = _skip_ws(text, open_index + 1)
    if pos < len(text) and text[pos] == "]":
        return spans, open_index, pos
    while True:
        try:
            _, end = decoder.raw_decode(text, pos)
        except ValueError as exc:
            raise RuleStoreError(f"unparsable rule element: {exc}") from None
        spans.append((pos, end))
        pos = _skip_ws(text, end)
        if pos >= len(text):
            raise RuleStoreError("unterminated rules array")
        if text[pos] == ",":
            pos = _skip_ws(text, pos + 1)
            continue
        if text[pos] == "]":
            return spans, open_index, pos
        raise RuleStoreError("expected ',' or ']' between rules")


def read_rule_file(path) -> list:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise RuleStoreError("rules file must hold a list of objects")
    return rows


def _schema() -> dict:
    return json.loads((KNOWLEDGE_ROOT / "schemas" / "rule_metadata.schema.json").read_text(encoding="utf-8"))


def _render(row: dict) -> str:
    """One array element in the repo's expanded layout (two-space indent, one level deep)."""
    try:
        body = json.dumps(row, indent=2)
    except (TypeError, ValueError) as exc:
        raise RuleStoreError(f"rule cannot be serialised: {exc}") from None
    return "  " + body.replace("\n", "\n  ")


def update_rule_file(path, *, replace: dict = None, append=()) -> None:
    """Replace rules by id (`replace` maps id to the new row) and append new rows, atomically.

    Replacement rows keep their id. Ids stay unique. Raises RuleStoreError before writing on any problem."""
    path = Path(path)
    replace = dict(replace or {})
    append = list(append)
    text = path.read_bytes().decode("utf-8")
    if not replace and not append:
        return
    rows = json.loads(text)
    spans, open_index, close_index = split_elements(text)
    if len(spans) != len(rows):
        raise RuleStoreError("element spans do not match the parsed rules")

    ids = [row.get("id") for row in rows]
    for rule_id, new in replace.items():
        if rule_id not in ids:
            raise RuleStoreError(f"no rule {rule_id} to replace")
        if not isinstance(new, dict) or new.get("id") != rule_id:
            raise RuleStoreError(f"replacement for {rule_id} must keep its id")
    for new in append:
        if not isinstance(new, dict):
            raise RuleStoreError("appended rule must be an object")
    final_ids = ids + [row.get("id") for row in append]
    if len(set(final_ids)) != len(final_ids):
        raise RuleStoreError("duplicate rule id")

    expected = [replace[row["id"]] if row["id"] in replace else row for row in rows] + append
    problems = validator.check(expected, _schema())
    if problems:
        pointer, message = problems[0]
        raise RuleStoreError(f"schema: {pointer or '/'} {message}")

    if not spans:
        pieces = [text[: open_index + 1], "\n", ",\n".join(_render(r) for r in append), text[close_index:]]
    else:
        pieces = []
        cursor = 0
        for index, (start, end) in enumerate(spans):
            pieces.append(text[cursor:start])
            rule_id = rows[index]["id"]
            pieces.append(_render(replace[rule_id]) if rule_id in replace else text[start:end])
            cursor = end
        if append:
            pieces.append(",\n" + ",\n".join(_render(r) for r in append))
        pieces.append(text[cursor:])
    new_text = "".join(pieces)

    try:
        reparsed = json.loads(new_text)
    except ValueError as exc:
        raise RuleStoreError(f"internal: new text does not parse: {exc}") from None
    if reparsed != expected:
        raise RuleStoreError("internal: new text does not match the validated rules")
    atomic_write_bytes(path, new_text.encode("utf-8"))
