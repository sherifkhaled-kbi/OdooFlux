"""Rule history sidecar `<tree>/history/rules/<rule-id>.json` (feature 011, REQ-KAP-021).

Preservation rules (contract manual-rule-cli): `created_by` and `created_at` are fixed from the first entry; entries
are only appended, never rewritten or deleted; each entry's `prev_hash` is the canonical digest of the entry before
it (null for the first). Every read verifies the whole chain, so tampering fails closed.
"""

import json
import re
from pathlib import Path

from odooflux.knowledge import validator
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.canonical import digest_obj, write_json_file

RULE_ID_RE = re.compile(r"^(\d+-\d+|\*)\.[a-z_]+\.[a-z0-9-]+$")
_SCHEMA_NAME = "rule_history"


class HistoryError(ValueError):
    """History is missing, malformed, tampered with, or an operation would rewrite it."""


def history_path(tree_root, rule_id: str) -> Path:
    if not isinstance(rule_id, str) or not RULE_ID_RE.match(rule_id):
        raise HistoryError(f"invalid rule id {rule_id!r}")
    return Path(tree_root) / "history" / "rules" / f"{rule_id}.json"


def entry_hash(entry: dict) -> str:
    """Chain link: canonical digest of one history entry (includes its own prev_hash)."""
    return digest_obj(entry)


def _schema() -> dict:
    return json.loads((KNOWLEDGE_ROOT / "schemas" / f"{_SCHEMA_NAME}.schema.json").read_text(encoding="utf-8"))


def verify_history(doc: dict, rule_id: str = None) -> dict:
    """Check schema, creator fields, revision sequence and hash chain. Returns `doc` or raises HistoryError."""
    problems = validator.check(doc, _schema())
    if problems:
        pointer, message = problems[0]
        raise HistoryError(f"schema: {pointer or '/'} {message}")
    if rule_id is not None and doc["rule_id"] != rule_id:
        raise HistoryError("history rule_id does not match the requested rule")
    entries = doc["entries"]
    if doc["created_by"] != entries[0]["actor"] or doc["created_at"] != entries[0]["at"]:
        raise HistoryError("created_by/created_at do not match the first entry")
    previous = None
    for number, entry in enumerate(entries, start=1):
        if entry["rev"] != number:
            raise HistoryError(f"entry {number}: rev is {entry['rev']}, expected {number}")
        if entry["prev_hash"] != previous:
            raise HistoryError(f"entry {number}: prev_hash does not match the previous entry")
        previous = entry_hash(entry)
    return doc


def load_history(tree_root, rule_id: str) -> dict:
    path = history_path(tree_root, rule_id)
    if not path.is_file():
        raise HistoryError(f"no history for {rule_id}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HistoryError(f"history is not valid JSON: {exc}") from None
    return verify_history(doc, rule_id)


def _entry(rev: int, *, actor, at, action, rule_sha256, summary, validation_status, provenance, prev_hash) -> dict:
    return {
        "rev": rev,
        "at": at,
        "actor": actor,
        "action": action,
        "summary": summary,
        "rule_sha256": rule_sha256,
        "provenance": dict(provenance or {}),
        "validation_status": validation_status,
        "prev_hash": prev_hash,
    }


def create_history(tree_root, rule_id: str, *, actor, at, rule_sha256, summary="created",
                   validation_status="NOT_RUN", provenance=None) -> dict:
    """Start a sidecar with its `create` entry. Refuses to overwrite an existing history."""
    path = history_path(tree_root, rule_id)
    if path.exists():
        raise HistoryError(f"history already exists for {rule_id}; use append_entry")
    entry = _entry(1, actor=actor, at=at, action="create", rule_sha256=rule_sha256, summary=summary,
                   validation_status=validation_status, provenance=provenance, prev_hash=None)
    doc = verify_history({"rule_id": rule_id, "created_by": actor, "created_at": at, "entries": [entry]}, rule_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_file(path, doc)
    return doc


def append_entry(tree_root, rule_id: str, *, actor, at, action, rule_sha256, summary,
                 validation_status="NOT_RUN", provenance=None) -> dict:
    """Append one revision. The existing chain is verified first; a tampered history is never extended."""
    if action == "create":
        raise HistoryError("create is only written by create_history")
    doc = load_history(tree_root, rule_id)
    last = doc["entries"][-1]
    entry = _entry(last["rev"] + 1, actor=actor, at=at, action=action, rule_sha256=rule_sha256, summary=summary,
                   validation_status=validation_status, provenance=provenance, prev_hash=entry_hash(last))
    doc["entries"].append(entry)
    verify_history(doc, rule_id)
    write_json_file(history_path(tree_root, rule_id), doc)
    return entry
