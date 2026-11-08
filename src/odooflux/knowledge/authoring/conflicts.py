"""Generated-versus-manual conflicts (contract manual-rule-cli, feature 011, REQ-KAP-031, REQ-KAP-020).

A generated candidate that collides with an active MANUAL rule (A001 same id, A002 same step, detector and params,
A005 same step and detector with overlapping file kinds) is recorded with status CONFLICT. The manual rule is kept and
never modified by a build. Each build writes `conflicts.json`. `resolve` records a human decision (manual, candidate or
both-renamed) in `conflicts.json` and in the history of the manual rule. Acceptance of candidates is owned by T059.
"""

import json
from pathlib import Path

from odooflux.knowledge.authoring import ops
from odooflux.knowledge.release.canonical import write_json_file

KEEP_CHOICES = ("manual", "candidate", "both-renamed")
OPEN_STATUSES = ("PROPOSED", "CONFLICT")
CONFLICTS_FILE = "conflicts.json"


class ConflictError(ValueError):
    """The conflict or the requested resolution is invalid; nothing was recorded."""


def _params_key(params) -> str:
    return json.dumps(params or {}, sort_keys=True, separators=(",", ":"))


def _overlap(a: dict, b: dict) -> bool:
    ka = set(a["file_kinds"]) if a.get("file_kinds") else None
    kb = set(b["file_kinds"]) if b.get("file_kinds") else None
    return ka is None or kb is None or bool(ka & kb)


def detect(manual_rules: list, candidate_rule: dict) -> list:
    """Conflicts of one candidate rule against the active MANUAL rules: list of {kind, with}."""
    found = []
    for manual in manual_rules:
        if manual.get("origin") != "MANUAL" or manual.get("maturity") == "RETIRED":
            continue
        if manual.get("id") == candidate_rule.get("id"):
            found.append({"kind": "A001", "with": manual["id"]})
            continue
        if not candidate_rule.get("detector_ref") or manual.get("step") != candidate_rule.get("step"):
            continue
        if manual.get("detector_ref") != candidate_rule.get("detector_ref"):
            continue
        if _params_key(manual.get("params")) == _params_key(candidate_rule.get("params")):
            found.append({"kind": "A002", "with": manual["id"]})
        elif _overlap(manual, candidate_rule):
            found.append({"kind": "A005", "with": manual["id"]})
    return found


def plan_build(manual_rules: list, candidates: list) -> dict:
    """Manual wins by default. Returns {candidates, conflicts, manual_kept}; inputs are not modified."""
    out_candidates = []
    conflicts = []
    kept = set()
    for candidate in candidates:
        item = dict(candidate)
        found = detect(manual_rules, candidate["rule"]) if candidate.get("status") in OPEN_STATUSES else []
        if found:
            item["status"] = "CONFLICT"
            item["conflicts"] = [dict(f) for f in found]
            for f in found:
                kept.add(f["with"])
                conflicts.append({"candidate_id": candidate["candidate_id"], "kind": f["kind"], "with": f["with"],
                                  "keep": "manual", "resolved": False})
        out_candidates.append(item)
    conflicts.sort(key=lambda c: (c["candidate_id"], c["kind"], c["with"]))
    return {"candidates": out_candidates, "conflicts": conflicts, "manual_kept": sorted(kept)}


def write_conflicts(build_dir, conflicts: list) -> Path:
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    path = build_dir / CONFLICTS_FILE
    write_json_file(path, {"conflicts": sorted(conflicts, key=lambda c: (c["candidate_id"], c["kind"], c["with"]))})
    return path


def read_conflicts(build_dir) -> dict:
    return json.loads((Path(build_dir) / CONFLICTS_FILE).read_text(encoding="utf-8"))


def resolve(build_dir, *, tree, candidate_id: str, keep: str, author=None, at=None) -> dict:
    """Record the decision for one candidate. History of each manual rule involved gets an `edit` entry."""
    if keep not in KEEP_CHOICES:
        raise ConflictError(f"keep must be one of {KEEP_CHOICES}, not {keep!r}")
    doc = read_conflicts(build_dir)
    entries = [c for c in doc["conflicts"] if c["candidate_id"] == candidate_id]
    if not entries:
        raise ConflictError(f"no conflict recorded for {candidate_id}")
    if any(c["resolved"] for c in entries):
        raise ConflictError(f"{candidate_id} is already resolved")
    author = ops.resolve_author(author)
    at = at or ops._now()
    for manual_id in sorted({c["with"] for c in entries}):
        ops._revise(
            Path(tree), manual_id, action="edit",
            change=lambda row, _doc, _cid=candidate_id, _keep=keep: (
                row, {"conflict_resolution": {"candidate_id": _cid, "keep": _keep}}),
            summary=f"conflict with {candidate_id} resolved: keep {keep}", author=author, at=at)
    for entry in entries:
        entry.update({"keep": keep, "resolved": True, "resolved_by": author, "resolved_at": at})
    write_conflicts(build_dir, doc["conflicts"])
    return {"candidate_id": candidate_id, "keep": keep, "manual_rules": sorted({c["with"] for c in entries})}
