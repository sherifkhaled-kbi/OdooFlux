"""View-time confidentiality for Enterprise-derived release records (feature 012 Wave 3d).

A unified internal release may hold evidence and rules derived from Enterprise sources. Such content must not reach
any rendered or serialised output. Enterprise-derived status is decided only from the release's verified provenance
index (`release/safety.load_provenance_index`): a source is Enterprise when its entry kind satisfies
`sources.is_enterprise_kind`. A record's own `confidentiality` field is never read.

- evidence row: Enterprise when its `source_id` is an Enterprise source id of the index;
- rule row: Enterprise when any evidence id it cites is an Enterprise evidence row (release evidence index);
- ledger change: Enterprise when a location's `snapshot_id` is the snapshot of an Enterprise index entry.

Only a view changes. Stored release, evidence, ledger and package bytes are never modified here. Callers pass the
index-derived id sets in; public records (no Enterprise id) come back as the same object, so their output stays
byte for byte as before.
"""

import json
from dataclasses import replace
from pathlib import Path as _Path

from odooflux.knowledge.acquisition.sources import is_enterprise_kind

__all__ = ["WITHHELD_MESSAGE", "WITHHELD_PATH", "enterprise_source_ids", "enterprise_snapshot_ids",
           "is_enterprise_record", "is_enterprise_location", "redact_evidence_view", "redact_change_record",
           "redact_refresh_report", "redact_findings", "redact_kb_findings", "enterprise_evidence_files",
           "active_enterprise_snapshot_ids", "strict_provenance_index", "view_enterprise_source_ids"]

WITHHELD_MESSAGE = "message withheld: the record is Enterprise-derived"
WITHHELD_PATH = "<enterprise location withheld>"
_ENTERPRISE = "enterprise"


def _enterprise_entries(index):
    if not isinstance(index, dict):
        return []
    return [entry for entry in index.values() if isinstance(entry, dict) and is_enterprise_kind(entry.get("kind"))]


def enterprise_source_ids(index) -> frozenset:
    """Source ids whose verified provenance entry has an Enterprise kind. None (provenance unknown) gives none."""
    return frozenset(entry["source_id"] for entry in _enterprise_entries(index)
                     if isinstance(entry.get("source_id"), str))


def enterprise_snapshot_ids(index) -> frozenset:
    """Snapshot ids of the Enterprise entries of the verified provenance index."""
    return frozenset(entry["snapshot_id"] for entry in _enterprise_entries(index)
                     if isinstance(entry.get("snapshot_id"), str))


def is_enterprise_record(record, enterprise_ids, evidence=None) -> bool:
    """True for an Enterprise-derived evidence row (by `source_id`) or rule row (by an Enterprise evidence id).

    `evidence` maps evidence id to evidence row (the release evidence index); it is needed only for rule rows.
    The record's own `confidentiality` field is ignored."""
    if not isinstance(record, dict) or not enterprise_ids:
        return False
    if "source_id" not in record and isinstance(record.get("evidence"), list):  # a rule row
        cited = (evidence or {}).get
        return any(isinstance(ref, str) and isinstance(cited(ref), dict)
                   and is_enterprise_record(cited(ref), enterprise_ids) for ref in record["evidence"])
    source_id = record.get("source_id")
    return isinstance(source_id, str) and source_id in enterprise_ids


def redact_evidence_view(record, enterprise_ids):
    """Enterprise evidence row -> stub {id, source_id, revision, confidentiality}: no locations, match text, paths or
    urls. A public row comes back unchanged (the same object)."""
    if not is_enterprise_record(record, enterprise_ids):
        return record
    return {"id": record.get("id"), "source_id": record.get("source_id"), "revision": record.get("revision"),
            "confidentiality": _ENTERPRISE}


def is_enterprise_location(location, enterprise_snapshot_ids_) -> bool:
    return isinstance(location, dict) and location.get("snapshot_id") in enterprise_snapshot_ids_


def redact_change_record(record: dict, enterprise_snapshot_ids_) -> dict:
    """A ledger change with an Enterprise location: that location keeps its snapshot id only, and `detail` (attribute
    values read from the snapshot) is withheld. A change with no Enterprise location comes back unchanged."""
    locations = record.get("locations") or []
    if not enterprise_snapshot_ids_ or not any(is_enterprise_location(loc, enterprise_snapshot_ids_)
                                               for loc in locations):
        return record
    view = dict(record)
    view["locations"] = [{"snapshot_id": loc.get("snapshot_id"), "path": WITHHELD_PATH, "line": None, "sha256": None}
                         if is_enterprise_location(loc, enterprise_snapshot_ids_) else loc for loc in locations]
    view["detail"] = {"withheld": _ENTERPRISE}
    return view


def redact_refresh_report(report: dict, evidence: dict, enterprise_ids) -> dict:
    """`knowledge refresh` report with the candidate paths of Enterprise evidence removed (they are paths in the
    Enterprise repository). Public items are unchanged. Returns a new dict; the input is not modified."""
    if not enterprise_ids:
        return report
    results = []
    for item in report.get("results", []):
        if item.get("candidates") and is_enterprise_record(evidence.get(item.get("id")), enterprise_ids):
            item = {**item, "candidates": []}
        results.append(item)
    return {**report, "results": results}


def enterprise_evidence_files(evidence: dict, evidence_files: dict, enterprise_ids) -> frozenset:
    """Relative files of the Enterprise evidence rows of a loaded knowledge tree."""
    return frozenset(evidence_files[eid] for eid, row in evidence.items()
                     if eid in evidence_files and is_enterprise_record(row, enterprise_ids))


def strict_provenance_index(tree_root):
    """The provenance index of a knowledge tree, failing closed for a release.

    Knowledge with no release (no `release.json` beside the tree, e.g. the built-in tree) returns None, as before.
    For an installed release (`<release>/release.json` next to `<release>/knowledge`) the index must be readable, a
    list (or {"sources": list}) of entries that each carry a string `source_id`, and each `source_id` must appear once.
    Anything else raises KnowledgeReleaseError: no Enterprise status can be decided, so none may be shown.
    """
    from odooflux.knowledge.release.manifest import MANIFEST_NAME
    from odooflux.knowledge.release.model import KnowledgeReleaseError
    from odooflux.knowledge.release.safety import PROVENANCE_RELPATH

    release_root = _Path(tree_root).resolve().parent
    if not (release_root / MANIFEST_NAME).is_file():
        return None
    where = "/".join(PROVENANCE_RELPATH)
    try:
        raw = json.loads((release_root.joinpath(*PROVENANCE_RELPATH)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise KnowledgeReleaseError(f"release provenance index is missing or unreadable ({where}); "
                                    "Enterprise status cannot be decided, so the view is refused") from None
    entries = raw.get("sources") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise KnowledgeReleaseError(f"release provenance index is not a list of sources ({where}); "
                                    "the view is refused")
    index, seen = {}, set()
    for entry in entries:
        sid = entry.get("source_id") if isinstance(entry, dict) else None
        if not isinstance(sid, str):
            raise KnowledgeReleaseError(f"release provenance index has an entry without a source_id ({where}); "
                                        "the view is refused")
        if sid in seen:
            raise KnowledgeReleaseError(f"release provenance index lists source {sid!r} more than once ({where}); "
                                        "the view is refused")
        seen.add(sid)
        index[sid] = entry
    return index


def view_enterprise_source_ids(tree_root) -> frozenset:
    """Enterprise source ids for a knowledge tree's view: `strict_provenance_index` decides, so a release with an
    unusable index raises KnowledgeReleaseError instead of showing everything as public."""
    return enterprise_source_ids(strict_provenance_index(tree_root))


def redact_kb_findings(kb, findings, index) -> list:
    """Validation findings of a loaded tree with the messages of its Enterprise evidence files withheld. `index` is the
    tree's verified provenance index (`load_provenance_index`); None leaves every finding as it is. For an installed
    release whose index is unusable every finding message is withheld (every source is treated as Enterprise)."""
    from odooflux.knowledge.release.model import KnowledgeReleaseError
    try:
        release_index = strict_provenance_index(kb.root) if getattr(kb, "root", None) is not None else None
    except KnowledgeReleaseError:
        return [replace(f, message=WITHHELD_MESSAGE) for f in findings]
    ids = enterprise_source_ids(release_index if release_index is not None else index)
    if not ids:
        return findings
    return redact_findings(findings, enterprise_evidence_files(kb.evidence, kb.evidence_files, ids))


def redact_findings(findings, withheld_files) -> list:
    """Validation findings of a withheld file keep their code, file and pointer; only the message is replaced, because
    schema messages echo the offending value."""
    return [replace(f, message=WITHHELD_MESSAGE) if f.file in withheld_files else f for f in findings]


def active_enterprise_snapshot_ids(kb_home=None) -> frozenset:
    """Enterprise snapshot ids of the active release's verified provenance (none for built-in knowledge).

    Raises KnowledgeReleaseError when the active release cannot be resolved or its provenance index is unusable; a
    caller that cannot tell whether a location is Enterprise must refuse to print it."""
    from odooflux.knowledge.loader import RELEASE_TREE
    from odooflux.knowledge.release.model import KnowledgeReleaseError
    from odooflux.knowledge.release.resolver import resolve_knowledge
    handle = resolve_knowledge(kb_home)
    if handle.builtin:
        return frozenset()
    index = strict_provenance_index(_Path(handle.root) / RELEASE_TREE)
    if index is None:  # an installed release always has its manifest; without it the release cannot be checked
        raise KnowledgeReleaseError(f"release {handle.release_id}: cannot verify its provenance index")
    return enterprise_snapshot_ids(index)
