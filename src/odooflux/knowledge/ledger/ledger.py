"""Change ledger core (REQ-KAP-014; change-ledger contract rules 1, 3, 4, 7, 8 and the create/load/save/get/
unresolved/verify API). Data: `schemas/change_ledger.schema.json`.

A ledger holds one entry per change, keyed by `change_id`. Every mutation goes through `mutate`, which builds the new
record in a copy, appends a history entry chained by `prev_hash` (sha256 of the previous entry's canonical JSON),
checks the whole document against the schema, and only then commits. `verify` recomputes the chain and the digest.

Disposition rules (rationale, rule links, confirm) belong to `ledger/dispositions.py` (T043). This module only
provides the storage and integrity primitives.
"""

import copy
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from odooflux.knowledge import validator as v
from odooflux.knowledge.ledger.ids import change_id
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.canonical import digest_obj, write_json_file

__all__ = ["Ledger", "LedgerError", "SCHEMA_ID", "ZERO_HASH", "INITIAL_DISPOSITION"]

SCHEMA_ID = "odooflux.change_ledger/1"
ZERO_HASH = "0" * 64
INITIAL_DISPOSITION = "UNRESOLVED"
_SCHEMA_PATH = KNOWLEDGE_ROOT / "schemas" / "change_ledger.schema.json"
_STEP = re.compile(r"^\d{2}-\d{2}$")
DRAFT_REQUIRED = ("domain", "kind", "subject_key", "class", "detail", "locations", "proposed_by")
# Fields no mutation may change: identity, history and the class that the detector assigned.
IMMUTABLE = ("change_id", "step", "domain", "kind", "subject_key", "class", "history")
_SCHEMA_CACHE: dict = {}


class LedgerError(ValueError):
    """The ledger refused an input, a mutation, or a file that does not match the schema."""


def _default_clock() -> str:
    """UTC timestamp. `SOURCE_DATE_EPOCH` pins it for reproducible builds."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    try:
        moment = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    except ValueError as exc:
        raise LedgerError(f"SOURCE_DATE_EPOCH is not an integer: {epoch!r}") from exc
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _schema() -> dict:
    if "change_ledger" not in _SCHEMA_CACHE:
        _SCHEMA_CACHE["change_ledger"] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE["change_ledger"]


def _schema_problems(doc: dict) -> list:
    return v.check(doc, _schema())


def _body(step, from_id, to_id, entries_map: dict) -> dict:
    return {"schema": SCHEMA_ID, "step": step, "from": from_id, "to": to_id,
            "entries": [copy.deepcopy(entries_map[k]) for k in sorted(entries_map)]}


def _finding(change_id_value, code: str, detail: str) -> dict:
    return {"change_id": change_id_value, "code": code, "detail": detail}


class Ledger:
    def __init__(self, step: str, from_id: str, to_id: str, entries: dict, *, clock=None):
        self.step = step
        self.from_id = from_id
        self.to_id = to_id
        self._entries = entries
        self.clock = clock or _default_clock
        self.digest_on_disk = None  # set by load and save; None for a ledger never written

    # ----- construction -------------------------------------------------------------------------------

    @classmethod
    def create(cls, step: str, from_snapshot: dict, to_snapshot: dict, drafts, *, clock=None) -> "Ledger":
        """Assign ids and create one UNRESOLVED entry per draft. Drafts are never dropped: two drafts with the
        same id are refused, and so is any draft that arrives already confirmed."""
        if not _STEP.match(step or ""):
            raise LedgerError(f"step must look like NN-NN, got {step!r}")
        clk = clock or _default_clock
        at = clk()
        entries: dict = {}
        for draft in drafts:
            missing = [k for k in DRAFT_REQUIRED if k not in draft]
            if missing:
                raise LedgerError(f"draft is missing {missing}")
            if draft.get("confirmed"):
                raise LedgerError("drafts cannot be confirmed; confirmation is an action on the ledger")
            cid = change_id(from_snapshot["snapshot_digest"], to_snapshot["snapshot_digest"], draft["domain"],
                            draft["kind"], draft["subject_key"])
            if cid in entries:
                raise LedgerError(f"duplicate change {cid} for {draft['subject_key']!r}")
            entries[cid] = {
                "change_id": cid,
                "step": step,
                "domain": draft["domain"],
                "kind": draft["kind"],
                "subject_key": draft["subject_key"],
                "class": draft["class"],
                "detail": copy.deepcopy(dict(draft["detail"])),
                "confirmed": False,
                "locations": [copy.deepcopy(dict(loc)) for loc in draft["locations"]],
                "disposition": INITIAL_DISPOSITION,
                "disposition_data": {"rule_ids": [], "evidence_ids": [], "rationale": None, "reviewer": None,
                                     "decided_at": None},
                "proposed_by": draft["proposed_by"],
                "history": [{"seq": 1, "at": at, "actor": draft["proposed_by"], "action": "create", "from": None,
                             "to": INITIAL_DISPOSITION, "prev_hash": ZERO_HASH}],
            }
        ledger = cls(step, from_snapshot["snapshot_id"], to_snapshot["snapshot_id"], entries, clock=clk)
        problems = _schema_problems(ledger.to_dict())
        if problems:
            raise LedgerError(f"ledger does not match the schema: {problems[:3]}")
        return ledger

    @classmethod
    def load(cls, path) -> "Ledger":
        """Read and schema-check a ledger file. Integrity (chain, digest) is checked by `verify`."""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LedgerError(f"cannot read ledger {path}: {exc}") from exc
        problems = _schema_problems(raw)
        if problems:
            raise LedgerError(f"ledger file does not match the schema: {problems[:3]}")
        entries = {e["change_id"]: e for e in raw["entries"]}
        if len(entries) != len(raw["entries"]):
            raise LedgerError("ledger file holds a duplicate change_id; refusing to drop either entry")
        ledger = cls(raw["step"], raw["from"], raw["to"], entries)
        ledger.digest_on_disk = raw["ledger_digest"]
        return ledger

    # ----- reads --------------------------------------------------------------------------------------

    def _require(self, cid: str) -> dict:
        if cid not in self._entries:
            raise LedgerError(f"unknown change {cid!r}")
        return self._entries[cid]

    def get(self, cid: str) -> dict:
        return copy.deepcopy(self._require(cid))

    def records(self) -> list:
        return [copy.deepcopy(self._entries[k]) for k in sorted(self._entries)]

    def unresolved(self) -> list:
        return [k for k in sorted(self._entries) if self._entries[k]["disposition"] == INITIAL_DISPOSITION]

    def to_dict(self) -> dict:
        body = _body(self.step, self.from_id, self.to_id, self._entries)
        return {**body, "ledger_digest": digest_obj(body)}

    # ----- writes -------------------------------------------------------------------------------------

    def mutate(self, cid: str, *, actor: str, action: str, from_value, to_value, update=None) -> dict:
        """Apply `update` (field -> value) to one entry and append a chained history entry, atomically.

        Refused (and nothing changes) if the result breaks the schema or touches an immutable field.
        Returns a copy of the appended history entry.
        """
        current = self._require(cid)
        bad = [k for k in (update or {}) if k in IMMUTABLE]
        if bad:
            raise LedgerError(f"fields {bad} cannot be changed")
        new = copy.deepcopy(current)
        for key, value in (update or {}).items():
            new[key] = copy.deepcopy(value)
        entry = {"seq": len(current["history"]) + 1, "at": self.clock(), "actor": actor, "action": action,
                 "from": from_value, "to": to_value, "prev_hash": digest_obj(current["history"][-1])}
        new["history"] = copy.deepcopy(current["history"]) + [entry]
        candidate = dict(self._entries)
        candidate[cid] = new
        body = _body(self.step, self.from_id, self.to_id, candidate)
        problems = _schema_problems({**body, "ledger_digest": digest_obj(body)})
        if problems:
            raise LedgerError(f"mutation of {cid} refused: {problems[:3]}")
        self._entries[cid] = new
        return copy.deepcopy(entry)

    def append_history(self, cid: str, *, actor: str, action: str, from_value, to_value) -> dict:
        """Append a history entry without changing the record (for example a note)."""
        return self.mutate(cid, actor=actor, action=action, from_value=from_value, to_value=to_value)

    def save(self, path) -> None:
        doc = self.to_dict()
        problems = _schema_problems(doc)
        if problems:
            raise LedgerError(f"refusing to save a ledger that does not match the schema: {problems[:3]}")
        write_json_file(path, doc)
        self.digest_on_disk = doc["ledger_digest"]

    # ----- integrity ----------------------------------------------------------------------------------

    def verify(self) -> list:
        """Findings (empty when clean): chain and sequence per entry, schema, and the digest of a loaded file."""
        findings = []
        for cid in sorted(self._entries):
            history = self._entries[cid]["history"]
            if not history:
                findings.append(_finding(cid, "HISTORY_EMPTY", "entry has no history"))
                continue
            prev = ZERO_HASH
            for index, item in enumerate(history, start=1):
                if item.get("seq") != index:
                    findings.append(_finding(cid, "HISTORY_SEQ", f"entry {index} has seq {item.get('seq')}"))
                if item.get("prev_hash") != prev:
                    findings.append(_finding(cid, "HISTORY_CHAIN_BROKEN",
                                             f"entry {index} prev_hash does not match entry {index - 1}"))
                prev = digest_obj(item)
        doc = self.to_dict()
        for pointer, message in _schema_problems(doc):
            findings.append(_finding(None, "SCHEMA", f"{pointer}: {message}"))
        if self.digest_on_disk is not None and self.digest_on_disk != doc["ledger_digest"]:
            findings.append(_finding(None, "LEDGER_DIGEST_MISMATCH", "stored ledger_digest differs from content"))
        return findings
