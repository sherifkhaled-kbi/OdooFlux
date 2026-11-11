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

Scale. Thousands of subjects of a real tree share identical attributes (plain fields), so every pair of them can
qualify and the candidate relation is quadratic. Subjects with the same (domain, kind, body digest, attribute set)
score identically, so the relation is evaluated per such class, never per pair, and counts are exact. An ambiguous
subject lists its candidates in full up to MAX_CANDIDATES; beyond that it lists the MAX_CANDIDATES smallest names and
records the exact total in `detail.candidate_count`. The class, the pairing and the one-to-one rule are unchanged.
"""

import heapq
import itertools
import json
import math

from odooflux.knowledge.extract import classify as c

__all__ = ["refine_candidates", "score", "HINT_SOURCES", "MAX_CANDIDATES"]

HINT_SOURCES = ("docs", "migration")
MAX_CANDIDATES = 10  # candidates listed on one ambiguous subject; the exact total is recorded beyond this


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


def _class_key(sid, fact) -> tuple:
    """Subjects with the same key score identically against any other subject (domain, kind, body digest, items)."""
    return (sid[0], sid[1], fact["body_digest"], frozenset(_items(fact["attrs"])))


def _candidate_pairs(removed_keys, added_keys, threshold) -> list:
    """(removed key, added key) class pairs that can reach `threshold`, in input order. Never a false negative: the
    score is `0.5 * jaccard + 0.5 * (body digests equal)`, so above 0.5 a pair needs equal body digests and a jaccard
    of at least `2 * threshold - 1`; a prefix filter over the attribute items (a standard exact filter for set
    similarity, items ranked rare first, conservative `floor`) then finds every added class that can reach it. The
    caller still decides each pair with `score`. At or below 0.5 the digest does not decide, so every same-kind pair
    is a candidate. Keys are `_class_key` tuples."""
    if threshold <= 0.5:
        return [(r, a) for r in removed_keys for a in added_keys if a[:2] == r[:2]]
    t = max(0.0, 2.0 * threshold - 1.0)
    buckets = {}
    for a in added_keys:
        buckets.setdefault(a[:3], []).append(a)
    removed_by = {}
    for r in removed_keys:
        removed_by.setdefault(r[:3], []).append(r)
    out = []
    for key, members in buckets.items():
        freq = {}
        for a in members:
            for item in a[3]:
                freq[item] = freq.get(item, 0) + 1
        rank = lambda item: (freq.get(item, 0), item)  # noqa: E731 - one total order for both sides
        postings = {}
        for a in members:
            ordered = sorted(a[3], key=rank)
            keep = max(len(ordered) - math.floor(t * len(ordered)) + 1, 1) if ordered else 0
            for item in ordered[:keep] if ordered else [None]:
                postings.setdefault(item, []).append(a)
        for r in removed_by.get(key, ()):
            ordered = sorted(r[3], key=rank)
            keep = max(len(ordered) - math.floor(t * len(ordered)) + 1, 1) if ordered else 0
            seen = {}
            for item in ordered[:keep] if ordered else [None]:
                for a in postings.get(item, ()):
                    seen[a] = True
            out.extend((r, a) for a in members if a in seen)
    return out


def _name(sid) -> str:
    return sid[2]


def _unknown_with(draft: dict, reason: str, candidates: list, extra_locations: list, total=None) -> dict:
    unique = {json.dumps(loc, sort_keys=True): loc for loc in draft["locations"] + extra_locations}
    locations = sorted(unique.values(), key=lambda loc: (loc["snapshot_id"], loc["path"], loc["line"] or 0))
    detail = {"reason": reason, "detail": "several candidates or a shared candidate", "candidates": sorted(candidates)}
    if total is not None and total > len(candidates):
        detail["candidate_count"] = total
    return {**draft, "class": "UNKNOWN", "locations": locations, "detail": detail}


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
    unhinted = [r_sid for r_sid in removed if r_sid not in hinted]
    r_classes, a_classes = {}, {}
    for sid in unhinted:
        r_classes.setdefault(_class_key(sid, before_by[sid][0]), []).append(sid)
    for sid in added:
        a_classes.setdefault(_class_key(sid, after_by[sid][0]), []).append(sid)
    partners_r, partners_a, class_value = {}, {}, {}  # class key -> partner class keys
    for rk, ak in _candidate_pairs(list(r_classes), list(a_classes), threshold):
        value = score(before_by[r_classes[rk][0]][0], after_by[a_classes[ak][0]][0])
        if value >= threshold:
            partners_r.setdefault(rk, []).append(ak)
            partners_a.setdefault(ak, []).append(rk)
            class_value[(rk, ak)] = value
    hint_r, hint_a = {}, {}  # explicit hint pairs, per subject
    for pair in pairs:
        hint_r.setdefault(pair[0], []).append(pair)
        hint_a.setdefault(pair[1], []).append(pair)

    def count_r(sid):
        rk = _class_key(sid, before_by[sid][0])
        return (sum(len(a_classes[ak]) for ak in partners_r.get(rk, ())) if sid not in hinted else 0) \
            + len(hint_r.get(sid, ()))

    def count_a(sid):
        ak = _class_key(sid, after_by[sid][0])
        return sum(len(r_classes[rk]) for rk in partners_a.get(ak, ())) + len(hint_a.get(sid, ()))

    resolved = [p for p in pairs if len(hint_r[p[0]]) == 1 and len(hint_a[p[1]]) == 1
                and count_r(p[0]) == 1 and count_a(p[1]) == 1]
    for rk, aks in partners_r.items():  # a class pair resolves only as one subject on each side with no other partner
        if len(aks) == 1 and len(r_classes[rk]) == 1 and len(a_classes[aks[0]]) == 1:
            r_sid, a_sid = r_classes[rk][0], a_classes[aks[0]][0]
            if count_r(r_sid) == 1 and count_a(a_sid) == 1:
                resolved.append((r_sid, a_sid, "RENAMED_CANDIDATE",
                                 {"score_milli": int(round(class_value[(rk, aks[0])] * 1000)),
                                  "basis": "attrs_jaccard+body_digest"}))
    resolved_r = {p[0] for p in resolved}
    resolved_a = {p[1] for p in resolved}

    def smallest(groups, hint_sids):
        """The MAX_CANDIDATES smallest sids (by subject name) over class member lists (each already name-ordered)
        and explicit hint partners."""
        pool = itertools.chain(itertools.chain.from_iterable(g[:MAX_CANDIDATES] for g in groups), hint_sids)
        return heapq.nsmallest(MAX_CANDIDATES, pool, key=lambda sid: (_name(sid), sid))

    def ambiguous(sid, key, classes, partners, partner_classes, hints, total, out_key):
        groups = [partner_classes[k] for k in partners.get(key, ())] if sid not in hinted or out_key == "a" else []
        picked = smallest(groups, [p[1 if out_key == "r" else 0] for p in hints.get(sid, ())])
        extra = [loc for other in picked for loc in out[other]["locations"]]
        return _unknown_with(out[sid], "AMBIGUOUS_RENAME", [_name(o) for o in picked], extra, total)

    for r_sid in sorted(set(r_sid for rk in partners_r for r_sid in r_classes[rk]) | set(hint_r)):
        if r_sid in resolved_r:
            continue
        rk = _class_key(r_sid, before_by[r_sid][0])
        out[r_sid] = ambiguous(r_sid, rk, r_classes, partners_r, a_classes, hint_r, count_r(r_sid), "r")
    for a_sid in sorted(set(a_sid for ak in partners_a for a_sid in a_classes[ak]) | set(hint_a)):
        if a_sid in resolved_a:
            continue
        ak = _class_key(a_sid, after_by[a_sid][0])
        out[a_sid] = ambiguous(a_sid, ak, a_classes, partners_a, r_classes, hint_a, count_a(a_sid), "a")

    for r_sid, a_sid, cls, extra in resolved:
        locations = out[r_sid]["locations"] + out[a_sid]["locations"]
        locations = sorted(locations, key=lambda loc: (loc["snapshot_id"], loc["path"], loc["line"] or 0))
        out[r_sid] = {"domain": r_sid[0], "kind": r_sid[1], "subject_key": r_sid[2], "class": cls,
                      "detail": {"from": _name(r_sid), "to": _name(a_sid), **extra},
                      "locations": locations, "proposed_by": "DETERMINISTIC", "confirmed": False}
        del out[a_sid]
    return [out[sid] for sid in sorted(out)]
