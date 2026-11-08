"""Fact diff and classification (REQ-KAP-012, REQ-KAP-011; diff-extractor contract, Classification table).

Input: structural facts of the two sides of a pair, each `{domain, path, subject_key, kind, attrs, body_digest, line,
sha256}`, plus parse failures. A subject is identified like a change: `(domain, kind, subject_key)`. Output: change
drafts for `Ledger.create` (`{domain, kind, subject_key, class, detail, locations, proposed_by}`), sorted by id.

Rules, in order: a subject present on one side only is ADDED or REMOVED; present on both at one path, a newly
present deprecation is DEPRECATED, a differing signature key is SIGNATURE_CHANGED, a differing body digest or other
attribute is BEHAVIOUR_CHANGED. The same identical fact at another path is MOVED. Anything ambiguous (several
locations for one subject on one side, a move that also changed, a parse failure) is UNKNOWN with every location
kept. Thresholds, signature keys and the class stages live in `extract/config.json`.

Nothing here executes target code: facts are plain data supplied by the domain extractors.
"""

import copy
import json
from pathlib import Path

__all__ = ["ClassifyError", "classify_pair", "load_config", "file_reason", "CONFIG_PATH"]

CONFIG_PATH = Path(__file__).with_name("config.json")


class ClassifyError(ValueError):
    """Input that cannot be classified (bad fact shape)."""


def load_config(path=None) -> dict:
    return json.loads((Path(path) if path else CONFIG_PATH).read_text(encoding="utf-8"))


def file_reason(size: int, config: dict):
    """`TOO_LARGE` when a file is over the configured cap, else None."""
    return "TOO_LARGE" if size > config["max_file_bytes"] else None


def _signature(fact: dict, config: dict) -> dict:
    keys = config["signature_keys"].get(fact["kind"])
    skip = set(config["deprecation_keys"])
    return {k: v for k, v in fact["attrs"].items() if k not in skip and (keys is None or k in keys)}


def _other_attrs(fact: dict, config: dict) -> dict:
    skip = set(config["deprecation_keys"])
    sig = set(_signature(fact, config))
    return {k: v for k, v in fact["attrs"].items() if k not in skip and k not in sig}


def _deprecated(fact: dict, config: dict):
    for key in config["deprecation_keys"]:
        if fact["attrs"].get(key):
            return fact["attrs"][key]
    return None


def _location(fact: dict, snapshot_id: str) -> dict:
    return {"snapshot_id": snapshot_id, "path": fact["path"], "line": fact.get("line"), "sha256": fact["sha256"]}


def _draft(sid, cls: str, detail: dict, locations: list) -> dict:
    domain, kind, subject_key = sid
    return {"domain": domain, "kind": kind, "subject_key": subject_key, "class": cls, "detail": detail,
            "locations": sorted(locations, key=lambda loc: (loc["snapshot_id"], loc["path"], loc["line"] or 0)),
            "proposed_by": "DETERMINISTIC"}


def _unknown(sid, reason: str, locations: list, detail: str = "") -> dict:
    return _draft(sid, "UNKNOWN", {"reason": reason, "detail": detail}, locations)


def _check_fact(fact: dict) -> None:
    required = ("domain", "path", "subject_key", "kind", "attrs", "body_digest", "sha256")
    missing = [k for k in required if k not in fact]
    if missing:
        raise ClassifyError(f"fact is missing {missing}")
    if not isinstance(fact["attrs"], dict):
        raise ClassifyError("fact attrs must be a mapping")


def _compare_same_path(sid, old: dict, new: dict, config: dict, from_id: str, to_id: str):
    """Class for one subject at one path on both sides, or None when nothing changed."""
    locs = [_location(new, to_id)]
    if _deprecated(new, config) and not _deprecated(old, config):
        return _draft(sid, "DEPRECATED", {"value": _deprecated(new, config), "added": True}, locs)
    sig_old, sig_new = _signature(old, config), _signature(new, config)
    if sig_old != sig_new:
        changed = sorted(k for k in set(sig_old) | set(sig_new) if sig_old.get(k) != sig_new.get(k))
        return _draft(sid, "SIGNATURE_CHANGED",
                      {"changed": changed, "from": {k: sig_old[k] for k in changed if k in sig_old},
                       "to": {k: sig_new[k] for k in changed if k in sig_new}}, locs)
    body_changed = old["body_digest"] != new["body_digest"]
    attrs_changed = _other_attrs(old, config) != _other_attrs(new, config)
    if body_changed or attrs_changed:
        basis = "body_digest" if body_changed else "attrs"
        return _draft(sid, "BEHAVIOUR_CHANGED", {"basis": basis, "from_body": old["body_digest"],
                                                  "to_body": new["body_digest"]}, locs)
    return None


def classify_pair(before, after, *, from_snapshot_id: str, to_snapshot_id: str, failures=(), config=None) -> list:
    """Change drafts for one pair. `failures` are `{domain, path, sha256, detail, side?}` parse failures (side
    defaults to `to`); each becomes an UNKNOWN change on the file, never a silent skip."""
    config = config or load_config()
    by_from, by_to = {}, {}
    for fact in before:
        _check_fact(fact)
        by_from.setdefault((fact["domain"], fact["kind"], fact["subject_key"]), []).append(fact)
    for fact in after:
        _check_fact(fact)
        by_to.setdefault((fact["domain"], fact["kind"], fact["subject_key"]), []).append(fact)

    drafts = {}
    for sid in sorted(set(by_from) | set(by_to)):
        old_list, new_list = by_from.get(sid, []), by_to.get(sid, [])
        locations = [_location(f, from_snapshot_id) for f in old_list] + [
            _location(f, to_snapshot_id) for f in new_list]
        if len(old_list) > 1 or len(new_list) > 1:
            drafts[sid] = _unknown(sid, "AMBIGUOUS_SUBJECT", locations, "several locations for one subject")
        elif old_list and not new_list:
            drafts[sid] = _draft(sid, "REMOVED", {}, [_location(old_list[0], from_snapshot_id)])
        elif new_list and not old_list:
            drafts[sid] = _draft(sid, "ADDED", {}, [_location(new_list[0], to_snapshot_id)])
        else:
            old, new = old_list[0], new_list[0]
            if old["path"] == new["path"]:
                result = _compare_same_path(sid, old, new, config, from_snapshot_id, to_snapshot_id)
                if result is not None:
                    drafts[sid] = result
            elif (_signature(old, config) == _signature(new, config)
                  and _other_attrs(old, config) == _other_attrs(new, config)
                  and old["body_digest"] == new["body_digest"]
                  and _deprecated(old, config) == _deprecated(new, config)):
                drafts[sid] = _draft(sid, "MOVED", {"from_path": old["path"], "to_path": new["path"]},
                                     [_location(new, to_snapshot_id)])
            else:
                drafts[sid] = _unknown(sid, "AMBIGUOUS_MOVE", locations, "moved and changed at once")

    for failure in failures:
        side = failure.get("side", "to")
        snap = from_snapshot_id if side == "from" else to_snapshot_id
        sid = (failure["domain"], "file", failure["path"])
        location = {"snapshot_id": snap, "path": failure["path"], "line": None, "sha256": failure["sha256"]}
        new_draft = _unknown(sid, "PARSE_FAILURE", [location], failure.get("detail", ""))
        if sid in drafts:
            # keep both causes and every location: merge into one UNKNOWN for the file
            merged = copy.deepcopy(drafts[sid])
            merged["locations"] = sorted(merged["locations"] + new_draft["locations"],
                                         key=lambda loc: (loc["snapshot_id"], loc["path"], loc["line"] or 0))
            merged["detail"] = {"reason": "MULTIPLE", "detail": "several causes for one file"}
            drafts[sid] = merged
        else:
            drafts[sid] = new_draft

    return [drafts[sid] for sid in sorted(drafts)]

