"""Evidence refresh (REQ-EVD-005, R-4). Reads each location at a revision with ``git show`` from
a local clone and classifies it: unchanged, moved, missing, or unavailable. Dry-run by default;
``apply`` updates line numbers, demotes missing records to CONFLICTING and updates checked_on/by.
"""

import json
import subprocess
from pathlib import Path

WINDOW = 50
UNAVAILABLE = "unavailable"


def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace")


def _show(repo: Path, rev: str, path: str):
    proc = _git(repo, "show", f"{rev}:{path}")
    return proc.stdout if proc.returncode == 0 else None


_LOCAL_COMMITS: dict = {}


def _local_commits(repo: Path) -> set:
    """All commit ids present locally, read once per clone. A per-revision ``cat-file -e`` costs
    seconds on a missing object (git searches every pack), so membership is checked in memory."""
    key = str(repo)
    if key not in _LOCAL_COMMITS:
        proc = _git(repo, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)")
        _LOCAL_COMMITS[key] = {line.split()[0] for line in proc.stdout.splitlines()
                               if line.endswith(" commit")} if proc.returncode == 0 else set()
    return _LOCAL_COMMITS[key]


def _commit_exists(repo: Path, rev: str) -> bool:
    """Available only if the commit is already local: a missing commit is 'unavailable', never fetched."""
    return rev in _local_commits(repo)


def classify_location(repo: Path, loc: dict, rev: str, search_candidates: bool = False) -> dict:
    """Classify one location at *rev*. Returns {result, new_line, candidates}. Candidate paths for a
    missing match come from a whole-tree search, which is slow on partial clones, so it is opt-in."""
    if not repo or not _commit_exists(repo, rev):
        return {"result": UNAVAILABLE, "new_line": None, "candidates": []}
    if loc["kind"] == "absent":
        scope = loc.get("search_scope") or loc["path"]
        text = _show(repo, rev, scope)
        present = text is not None and loc["match"] in text
        return {"result": "missing" if present else "unchanged", "new_line": None, "candidates": []}
    if loc.get("line") is None:  # path-presence location: no line, so check that the path exists
        listing = _git(repo, "ls-tree", "-r", "--name-only", rev, "--", loc["path"]).stdout
        present = bool(listing.strip()) or _show(repo, rev, loc["path"]) is not None
        return {"result": "unchanged" if present else "missing", "new_line": None, "candidates": []}
    text = _show(repo, rev, loc["path"])
    if text is None:
        return {"result": "missing", "new_line": None, "candidates": []}
    lines = text.splitlines()
    line = loc["line"]
    if 1 <= line <= len(lines) and loc["match"] in lines[line - 1]:
        return {"result": "unchanged", "new_line": line, "candidates": []}
    lo, hi = max(1, line - WINDOW), min(len(lines), line + WINDOW)
    hits = [n for n in range(lo, hi + 1) if loc["match"] in lines[n - 1]]
    if hits:
        nearest = min(hits, key=lambda n: abs(n - line))
        return {"result": "moved", "new_line": nearest, "candidates": hits}
    if not search_candidates:
        return {"result": "missing", "new_line": None, "candidates": []}
    # Path renamed or match gone elsewhere: search the whole revision for the match text.
    found = _git(repo, "grep", "-l", "-F", loc["match"], rev, "--", loc["path"].rsplit("/", 1)[-1]).stdout
    candidates = sorted({line.split(":", 2)[1] for line in found.splitlines() if line.count(":") >= 2})
    return {"result": "missing", "new_line": None, "candidates": candidates[:10]}


def refresh(kb, repos: dict, revisions: dict, search_candidates: bool = False) -> dict:
    """Classify every location. *repos* maps repository -> clone path; *revisions* maps branch -> sha."""
    results, demoted = [], set()
    for rid in sorted(kb.evidence):
        record = kb.evidence[rid]
        for index, loc in enumerate(record.get("locations", [])):
            rev = revisions.get(loc["branch"], loc["revision"])
            verdict = classify_location(repos.get(record["repository"]), loc, rev, search_candidates)
            results.append({"id": rid, "location_index": index, "result": verdict["result"],
                            "old_line": loc.get("line"), "new_line": verdict["new_line"],
                            "candidates": verdict["candidates"]})
            if verdict["result"] == "missing":
                demoted.add(rid)
    rule_demotions = sorted(r["id"] for r in kb.rules if any(e in demoted for e in r.get("evidence", [])))
    return {"checked": len(results), "results": results, "demoted_evidence": sorted(demoted),
            "demoted_rules": rule_demotions}


def apply_report(kb, report: dict, today: str, by: str = "refresh-job") -> list:
    """Write moved line numbers and CONFLICTING status to the evidence files. Returns changed files."""
    changed = {}
    for item in report["results"]:
        rid = item["id"]
        record = changed.setdefault(rid, json.loads(json.dumps(kb.evidence[rid])))
        loc = record["locations"][item["location_index"]]
        if item["result"] == "moved" and item["new_line"] is not None:
            loc["line"] = item["new_line"]
    for rid in report["demoted_evidence"]:
        record = changed.setdefault(rid, json.loads(json.dumps(kb.evidence[rid])))
        record["status"] = "CONFLICTING"
        record["notes"] = (record.get("notes", "") + " Refresh: matched text missing at the new revision.").strip()
    written = []
    for rid, record in changed.items():
        record["checked_on"] = today
        record["checked_by"] = by
        path = kb.root / kb.evidence_files[rid]
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(kb.evidence_files[rid])
    return sorted(written)
