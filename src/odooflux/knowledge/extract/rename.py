"""Rename and replacement candidate pairing (REQ-KAP-012; diff-extractor contract, pipeline step 4, Classification
table: RENAMED_CANDIDATE and REPLACEMENT_CANDIDATE are `confirmed:false` always).

`refine_candidates` takes the drafts from `classify.classify_pair` and the raw facts of both sides. Each removed
subject is compared with each added subject of the same domain and kind:

- a documentation or migration hint naming the pair makes a REPLACEMENT_CANDIDATE;
- otherwise a score at or above `rename_threshold` (from `extract/config.json`) makes a RENAMED_CANDIDATE. The score
  is `0.5 * jaccard(attrs) + 0.5 * (body digests equal)`, kept as an integer per mille in the detail.

Pairing is one-to-one. A pair is kept only when both of its subjects have exactly one candidate partner. Anything
else becomes UNKNOWN on every involved subject, with the candidates listed; no candidate is silently dropped. The
absorbed added subject disappears from the output, and the removed subject carries both locations.
"""

import json

from odooflux.knowledge.extract import classify as c

__all__ = ["refine_candidates", "score", "HINT_SOURCES"]

HINT_SOURCES = ("docs", "migration")


def _items(attrs: dict) -> set:
    return {json.dumps([k, v], sort_keys=True) for k, v in attrs.items()}


def score(old: dict, new: dict) -> float:
    """Similarity of two facts in [0, 1]. Different domain or kind is never a rename."""
    if old["domain"] != new["domain"] or old["kind"] != new["kind"]:
        return 0.0
    a, b = _items(old["attrs"]), _items(new["attrs"])
    jaccard = 1.0 if not (a | b) else len(a & b) / len(a | b)
    body = 1.0 if old["body_digest"] == new["body_digest"] else 0.0
    return 0.5 * jaccard + 0.5 * body


def _name(sid) -> str:
    return sid[2]


def _unknown_with(draft: dict, reason: str, candidates: list, extra_locations: list) -> dict:
    unique = {json.dumps(loc, sort_keys=True): loc for loc in draft["locations"] + extra_locations}
    locations = sorted(unique.values(), key=lambda loc: (loc["snapshot_id"], loc["path"], loc["line"] or 0))
    return {**draft, "class": "UNKNOWN", "locations": locations,
            "detail": {"reason": reason, "detail": "several candidates or a shared candidate",
                       "candidates": sorted(candidates)}}


def refine_candidates(drafts, before, after, *, config=None, hints=()) -> list:
    """Replace paired ADDED/REMOVED drafts with candidate drafts. `hints` are
    `{from: subject_key, to: subject_key, source: docs|migration}` from the documentation or migration extractors."""
    config = config or c.load_config()
    threshold = float(config["rename_threshold"])
    out = {(d["domain"], d["kind"], d["subject_key"]): d for d in drafts}
    removed = [sid for sid, d in out.items() if d["class"] == "REMOVED"]
    added = [sid for sid, d in out.items() if d["class"] == "ADDED"]
    before_by, after_by = {}, {}
    for f in before:
        before_by.setdefault((f["domain"], f["kind"], f["subject_key"]), []).append(f)
    for f in after:
        after_by.setdefault((f["domain"], f["kind"], f["subject_key"]), []).append(f)

    pairs = []  # (removed sid, added sid, class, detail extras)
    hinted = set()
    for hint in hints:
        if hint.get("source") not in HINT_SOURCES:
            raise ValueError(f"hint source must be one of {HINT_SOURCES}, got {hint.get('source')!r}")
        for r_sid in removed:
            if _name(r_sid) != hint["from"]:
                continue
            for a_sid in added:
                if _name(a_sid) == hint["to"] and a_sid[:2] == r_sid[:2]:
                    pairs.append((r_sid, a_sid, "REPLACEMENT_CANDIDATE",
                                  {"source": hint["source"], "basis": "hint"}))
                    hinted.add(r_sid)
    for r_sid in removed:
        if r_sid in hinted:
            continue
        for a_sid in added:
            if a_sid[:2] != r_sid[:2]:
                continue
            value = score(before_by[r_sid][0], after_by[a_sid][0])
            if value >= threshold:
                pairs.append((r_sid, a_sid, "RENAMED_CANDIDATE",
                              {"score_milli": int(round(value * 1000)), "basis": "attrs_jaccard+body_digest"}))

    by_r, by_a = {}, {}
    for pair in pairs:
        by_r.setdefault(pair[0], []).append(pair)
        by_a.setdefault(pair[1], []).append(pair)
    resolved = [p for p in pairs if len(by_r[p[0]]) == 1 and len(by_a[p[1]]) == 1]
    resolved_r = {p[0] for p in resolved}
    resolved_a = {p[1] for p in resolved}

    for r_sid in sorted(by_r):
        if r_sid in resolved_r:
            continue
        candidates = [_name(p[1]) for p in by_r[r_sid]]
        extra = [loc for p in by_r[r_sid] for loc in out[p[1]]["locations"]]
        out[r_sid] = _unknown_with(out[r_sid], "AMBIGUOUS_RENAME", candidates, extra)
    for a_sid in sorted(by_a):
        if a_sid in resolved_a:
            continue
        candidates = [_name(p[0]) for p in by_a[a_sid]]
        extra = [loc for p in by_a[a_sid] for loc in out[p[0]]["locations"]]
        out[a_sid] = _unknown_with(out[a_sid], "AMBIGUOUS_RENAME", candidates, extra)

    for r_sid, a_sid, cls, extra in resolved:
        locations = out[r_sid]["locations"] + out[a_sid]["locations"]
        locations = sorted(locations, key=lambda loc: (loc["snapshot_id"], loc["path"], loc["line"] or 0))
        out[r_sid] = {"domain": r_sid[0], "kind": r_sid[1], "subject_key": r_sid[2], "class": cls,
                      "detail": {"from": _name(r_sid), "to": _name(a_sid), **extra},
                      "locations": locations, "proposed_by": "DETERMINISTIC", "confirmed": False}
        del out[a_sid]
    return [out[sid] for sid in sorted(out)]
