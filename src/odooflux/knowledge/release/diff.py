"""Release diff and destructive-change detection (REQ-KAP-030; contracts/release-lifecycle.md "Incremental update rules").

`diff_releases(a, b)` compares two intact release trees and returns a `ReleaseDiff`. It reads only; both trees must pass
`require_intact` first, so a tampered release is refused rather than diffed.

Families:
- `rules`: records of `compatibility/*.rules.json` (arrays), keyed by `id`.
- `evidence`: records of `evidence/*.json` (one object per file), keyed by `id`.
- every other manifest file is one file-level family whose key is its path.

Record entries compare canonical JSON, so key order does not matter. A removed rule, and a removed evidence record whose
status is VERIFIED, is `destructive`: the build refuses it unless listed in `--supersede` (T017 wires the flag).
Unchanged files and records are counted but not listed.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.knowledge.release.manifest import MANIFEST_NAME, STATE_NAME, require_intact
from odooflux.knowledge.release.model import KnowledgeReleaseError

RECORD_FAMILIES = ("rules", "evidence")
DESTRUCTIVE_EVIDENCE_STATUS = "VERIFIED"
_BUCKET = {"ADDED": "added", "REMOVED": "removed", "CHANGED": "changed"}


@dataclass
class ReleaseDiff:
    entries: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    unchanged: int = 0

    @property
    def has_destructive(self) -> bool:
        return any(entry["destructive"] for entry in self.entries)

    def destructive_entries(self) -> list:
        return [entry for entry in self.entries if entry["destructive"]]


def _family(path: str):
    # A release manifest lists paths as they sit in the release (`knowledge/compatibility/...`); accept the bare form too.
    if path.startswith("knowledge/"):
        path = path[len("knowledge/"):]
    if path.startswith("compatibility/") and path.endswith(".rules.json"):
        return "rules"
    if path.startswith("evidence/") and path.endswith(".json") and path.count("/") == 1:
        return "evidence"
    return None


def _load(root: Path, rel: str):
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KnowledgeReleaseError(f"{rel}: unreadable release record file ({type(exc).__name__})") from None


def _records(root: Path, files: dict, family: str) -> dict:
    """id -> record for one record family, over every manifest file of that family."""
    out = {}
    for rel in sorted(files):
        if _family(rel) != family:
            continue
        data = _load(root, rel)
        items = data if family == "rules" else [data]
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise KnowledgeReleaseError(f"{rel}: expected records as JSON objects")
        for item in items:
            rid = item.get("id") or Path(rel).stem
            if rid in out:
                raise KnowledgeReleaseError(f"duplicate {family} record id {rid} in release")
            out[rid] = item
    return out


def _manifest_files(root: Path) -> dict:
    manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    return {entry["path"]: entry["sha256"] for entry in manifest["files"]
            if entry["path"] not in (MANIFEST_NAME, STATE_NAME)}


def _canonical(record) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def diff_releases(a, b) -> ReleaseDiff:
    root_a, root_b = Path(a), Path(b)
    require_intact(root_a)
    require_intact(root_b)
    files_a, files_b = _manifest_files(root_a), _manifest_files(root_b)
    result = ReleaseDiff()

    for family in RECORD_FAMILIES:
        before, after = _records(root_a, files_a, family), _records(root_b, files_b, family)
        for rid in sorted(set(before) | set(after)):
            if rid not in after:
                destructive = family == "rules" or before[rid].get("status") == DESTRUCTIVE_EVIDENCE_STATUS
                change = "REMOVED"
            elif rid not in before:
                destructive, change = False, "ADDED"
            elif _canonical(before[rid]) == _canonical(after[rid]):
                result.unchanged += 1
                continue
            else:
                destructive, change = False, "CHANGED"
            result.entries.append({"kind": "record", "family": family, "id": rid, "change": change,
                                   "destructive": destructive})

    for path in sorted(set(files_a) | set(files_b)):
        if _family(path) in RECORD_FAMILIES:
            continue
        if path not in files_b:
            change = "REMOVED"
        elif path not in files_a:
            change = "ADDED"
        elif files_a[path] == files_b[path]:
            result.unchanged += 1
            continue
        else:
            change = "CHANGED"
        result.entries.append({"kind": "file", "family": path, "id": path, "change": change, "destructive": False})

    result.entries.sort(key=lambda e: (e["kind"], e["family"], e["id"]))
    for entry in result.entries:
        bucket = result.counts.setdefault(entry["family"], {"added": 0, "removed": 0, "changed": 0})
        bucket[_BUCKET[entry["change"]]] += 1
    return result
