"""File accounting for one snapshot pair (REQ-KAP-013; diff-extractor contract, pipeline steps 1 and 5; data model
FileAccounting).

Every changed file (added, removed or modified by blob sha256) gets exactly one state: PENDING while the pipeline
runs, then ANALYZED, EXCLUDED, UNSUPPORTED or FAILED. EXCLUDED, UNSUPPORTED and FAILED carry a closed
`reason_code` (OTHER needs free text). `finalize` refuses while any file is PENDING and checks the invariant
`sum(totals) == len(files) == independent_count`. The independent count comes from `changed_paths`, a path and
digest comparison that does not use the extractor's fact diff, so the two can disagree and the mismatch is reported.

`renamed_file` is accepted by the schema for paired renames; `changed_paths` lists path-level changes only.
"""

import copy
import json

from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

__all__ = ["AccountingError", "FileAccounting", "changed_paths", "check_document", "STATES", "REASON_CODES"]

STATES = ("PENDING", "ANALYZED", "EXCLUDED", "UNSUPPORTED", "FAILED")
TERMINAL_WITH_REASON = ("EXCLUDED", "UNSUPPORTED", "FAILED")
REASON_CODES = ("OUT_OF_SCOPE_GLOB", "GENERATED_FILE", "BINARY", "TOO_LARGE", "NO_PARSER", "NO_JS_ADAPTER",
                "PARSE_ERROR", "ENCODING_ERROR", "TIMEOUT", "OTHER")
_SCHEMA_PATH = KNOWLEDGE_ROOT / "schemas" / "file_accounting.schema.json"


class AccountingError(ValueError):
    """A state change or a finalize was refused."""


def changed_paths(from_entries, to_entries) -> dict:
    """path -> `added` | `removed` | `modified`, from snapshot entries alone (sha256 comparison, sorted)."""
    before = {e["path"]: e["sha256"] for e in from_entries}
    after = {e["path"]: e["sha256"] for e in to_entries}
    out = {}
    for path in sorted(set(before) | set(after)):
        if path not in before:
            out[path] = "added"
        elif path not in after:
            out[path] = "removed"
        elif before[path] != after[path]:
            out[path] = "modified"
    return out


def _empty_totals() -> dict:
    return {state: 0 for state in STATES}


class FileAccounting:
    def __init__(self, step: str, from_snapshot_id: str, to_snapshot_id: str, changed: dict, *,
                 independent_count=None):
        self.step = step
        self.from_snapshot_id = from_snapshot_id
        self.to_snapshot_id = to_snapshot_id
        self._files = {
            path: {"path": path, "change_kind": kind, "state": "PENDING", "reason_code": None, "domain": None,
                   "parser": None, "error": None}
            for path, kind in changed.items()
        }
        self.independent_count = len(changed) if independent_count is None else independent_count

    @classmethod
    def for_pair(cls, step: str, from_snapshot: dict, to_snapshot: dict, *, independent_count=None):
        changed = changed_paths(from_snapshot["entries"], to_snapshot["entries"])
        return cls(step, from_snapshot["snapshot_id"], to_snapshot["snapshot_id"], changed,
                   independent_count=independent_count)

    def set_state(self, path: str, state: str, *, reason_code=None, domain=None, parser=None, error=None) -> None:
        if path not in self._files:
            raise AccountingError(f"{path!r} is not a changed file of this pair")
        if state not in STATES or state == "PENDING":
            raise AccountingError(f"state must be one of {STATES[1:]}, got {state!r}")
        record = self._files[path]
        if record["state"] != "PENDING":
            raise AccountingError(f"{path!r} already has terminal state {record['state']}")
        if state in TERMINAL_WITH_REASON:
            if reason_code not in REASON_CODES:
                raise AccountingError(f"{state} needs a reason_code from the closed list, got {reason_code!r}")
        elif reason_code is not None:
            raise AccountingError("ANALYZED files carry no reason_code")
        if reason_code == "OTHER" and not (error and str(error).strip()):
            raise AccountingError("reason_code OTHER needs free text in error")
        record.update({"state": state, "reason_code": reason_code})
        if domain is not None:
            record["domain"] = domain
        if parser is not None:
            record["parser"] = parser
        if error is not None:
            record["error"] = error

    def pending(self) -> list:
        return [p for p in sorted(self._files) if self._files[p]["state"] == "PENDING"]

    def document(self) -> dict:
        files = [copy.deepcopy(self._files[p]) for p in sorted(self._files)]
        totals = _empty_totals()
        for item in files:
            totals[item["state"]] += 1
        return {
            "pair": {"from_snapshot": self.from_snapshot_id, "to_snapshot": self.to_snapshot_id,
                     "step": self.step},
            "files": files,
            "totals": totals,
            "independent_count": self.independent_count,
        }

    def finalize(self) -> dict:
        pending = self.pending()
        if pending:
            raise AccountingError(f"{len(pending)} files are still PENDING, first: {pending[0]!r}")
        doc = self.document()
        problems = check_document(doc)
        if problems:
            raise AccountingError(f"accounting invariant broken: {problems[:3]}")
        return doc


def check_document(doc: dict) -> list:
    """Problems with a file_accounting document (empty when it holds). Covers the schema, the totals against the
    files, the independent count, PENDING, and the reason rules."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    problems = [f"{p or '/'}: {m}" for p, m in v.check(doc, schema)]
    files = doc.get("files", [])
    totals = doc.get("totals", {})
    counts = _empty_totals()
    for item in files:
        if item.get("state") in counts:
            counts[item["state"]] += 1
    if sum(totals.get(s, 0) for s in STATES) != len(files):
        problems.append("sum of totals differs from len(files)")
    if counts != {s: totals.get(s) for s in STATES}:
        problems.append("totals differ from the per-file states")
    if len(files) != doc.get("independent_count"):
        problems.append("len(files) differs from the independent count")
    if counts["PENDING"]:
        problems.append("PENDING files remain")
    for item in files:
        if item.get("state") in TERMINAL_WITH_REASON and item.get("reason_code") not in REASON_CODES:
            problems.append(f"{item.get('path')}: {item.get('state')} without a reason_code")
        if item.get("reason_code") == "OTHER" and not str(item.get("error") or "").strip():
            problems.append(f"{item.get('path')}: OTHER without free text")
    return problems
