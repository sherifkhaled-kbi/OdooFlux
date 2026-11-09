"""Internal-release confidentiality gate (Feature 012 W3-Y; owner-approved trust model).

A release is INTERNAL when `release.json` carries `confidentiality: "internal"`, and any release that holds
Enterprise-derived material is refused the same way. Internal releases never leave the machine: export refuses them
(EXPORT_REFUSED), the importer refuses an internal package before anything is staged (P12, INTERNAL_RELEASE_REFUSED),
and `package validate` reports P12 too.

The gate is evaluated from the release tree bytes, never from the manifest alone, and it fails closed: a record that
cannot be read as public is a refusal, not a pass. There is deliberately no filter that strips metadata out of an
internal release. Refusal text carries reason labels and counts only, never Enterprise paths or content.

Refusal reasons (`assess`):
  - release.json `confidentiality` is present and not "public" (for example "internal")
  - a `release.json` `sources[]` item or `provenance/sources.json` entry is Enterprise-marked: kind GIT_ENTERPRISE or
    ENTERPRISE_LOCAL, `confidentiality` other than "public", or a legacy `enterprise_derived` value other than false
  - a JSON record in the tree (outside release.json, provenance and snapshots/) names an Enterprise source in its
    `source_id` or `source` key
  - a `snapshots/` manifest belongs to an Enterprise source, or cannot be read as a public manifest
  - release metadata that cannot be read as an object
"""

import json
from pathlib import Path

ENTERPRISE_KINDS = frozenset({"GIT_ENTERPRISE", "ENTERPRISE_LOCAL"})
# Source ids in the Enterprise namespace (knowledge/update/discovery.py ENTERPRISE_PREFIX) count as Enterprise even when
# no provenance record defines them: a reference to such an id is refused.
ENTERPRISE_ID_PREFIX = "odoo-enterprise-"
PUBLIC = "public"
INTERNAL = "internal"
RELEASE_NAME = "release.json"
PROVENANCE_NAME = "provenance/sources.json"
SNAPSHOT_DIR = "snapshots"
REFERENCE_KEYS = ("source_id", "source")


class _Unreadable:
    """Sentinel: a file that is missing, not UTF-8 JSON, or not parseable."""


_UNREADABLE = _Unreadable()


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _UNREADABLE


def _provenance_records(data):
    """The source records of provenance/sources.json: the release writer's list of entries, or a `{"sources": [...]}`
    object. Anything else is None (unreadable, refused)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("sources", []), list):
        return data.get("sources", [])
    return None


def _enterprise_marked(item) -> bool:
    """True when a source record cannot be shown public."""
    if not isinstance(item, dict):
        return True
    if item.get("kind") in ENTERPRISE_KINDS:
        return True
    if item.get("enterprise_derived") not in (None, False):
        return True
    confidentiality = item.get("confidentiality")
    return confidentiality is not None and confidentiality != PUBLIC


def _ids_of(record) -> set:
    if not isinstance(record, dict):
        return set()
    return {record[key] for key in REFERENCE_KEYS if isinstance(record.get(key), str)}


def _names_enterprise(record, enterprise_ids: set) -> bool:
    """True when a record's `source_id` or `source` is a known Enterprise id or in the Enterprise namespace."""
    return any(value in enterprise_ids or value.startswith(ENTERPRISE_ID_PREFIX)
               for value in (record.get(key) for key in REFERENCE_KEYS) if isinstance(value, str))


def _raw_names_enterprise(path: Path, enterprise_ids: set) -> bool:
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return True
    return ENTERPRISE_ID_PREFIX in text or any(sid and sid in text for sid in enterprise_ids)


def _reference_count(node, enterprise_ids: set) -> int:
    """Number of JSON objects under `node` whose `source_id` or `source` names an Enterprise source."""
    count = 0
    if isinstance(node, dict):
        if _names_enterprise(node, enterprise_ids):
            count += 1
        for value in node.values():
            count += _reference_count(value, enterprise_ids)
    elif isinstance(node, list):
        for value in node:
            count += _reference_count(value, enterprise_ids)
    return count


def assess(root) -> list:
    """Refusal reasons for the release tree at `root`. An empty list means the tree is public.

    Reasons are fixed labels with counts. They never name a file, a source record, or any content."""
    root = Path(root)
    release = _load(root / RELEASE_NAME)
    if not isinstance(release, dict):
        return ["release.json is not a readable object"]
    reasons = []
    confidentiality = release.get("confidentiality")
    if confidentiality is not None and confidentiality != PUBLIC:
        reasons.append("release is internal" if confidentiality == INTERNAL
                       else "release confidentiality is not public")

    release_sources = release.get("sources", [])
    if not isinstance(release_sources, list):
        return reasons + ["release sources is not a list"]
    provenance = []
    if (root / PROVENANCE_NAME).exists():
        provenance = _provenance_records(_load(root / PROVENANCE_NAME))
        if provenance is None:
            return reasons + ["provenance/sources.json is not readable"]

    marked = [item for item in release_sources + provenance if _enterprise_marked(item)]
    if marked:
        reasons.append(f"{len(marked)} Enterprise-derived source record(s)")
    enterprise_ids = set()
    for item in marked:
        enterprise_ids |= _ids_of(item)

    enterprise_snapshots = 0
    unverifiable_snapshots = 0
    snapshot_dir = root / SNAPSHOT_DIR
    if snapshot_dir.is_dir():
        for path in sorted(p for p in snapshot_dir.rglob("*") if p.is_file()):
            data = _load(path)
            if data is _UNREADABLE:
                unverifiable_snapshots += 1
            elif _enterprise_marked(data) and not isinstance(data, dict):
                unverifiable_snapshots += 1
            elif _enterprise_marked(data) or _names_enterprise(data, enterprise_ids):
                enterprise_snapshots += 1
    if enterprise_snapshots:
        reasons.append(f"{enterprise_snapshots} snapshot manifest(s) of an Enterprise source")
    if unverifiable_snapshots:
        reasons.append(f"{unverifiable_snapshots} snapshot manifest(s) that cannot be verified as public")

    refs = 0
    for path in sorted(root.rglob("*.json")):
        rel = path.relative_to(root).as_posix()
        if rel in (RELEASE_NAME, PROVENANCE_NAME) or rel.startswith(SNAPSHOT_DIR + "/") or not path.is_file():
            continue
        data = _load(path)
        if data is not _UNREADABLE:
            refs += _reference_count(data, enterprise_ids)
        elif _raw_names_enterprise(path, enterprise_ids):
            refs += 1  # not parseable: the raw bytes must not name an Enterprise source either
    if refs:
        reasons.append(f"{refs} record(s) reference an Enterprise source")
    return reasons


def refusal_text(reasons: list) -> str:
    return "; ".join(reasons)


def declares_enterprise(manifest: dict) -> bool:
    """True when package.json declares Enterprise-derived content (legacy packages may set the flag)."""
    return manifest.get("contains_enterprise_derived") is True
