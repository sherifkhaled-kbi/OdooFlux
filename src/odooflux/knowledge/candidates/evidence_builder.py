"""Evidence records for ledger changes (feature 011, REQ-KAP-015, REQ-KAP-008; contract candidate-rule-generation).

One EvidenceRecord per supported change. Each location carries the file's `content_sha256` and the `snapshot_ref` of
the snapshot it was read from, both taken from the ledger. Status is always DOCUMENTED_NOT_TESTED and origin
KAP_DETERMINISTIC: nothing here runs a test or invents a location. Evidence from an unofficial source keeps
`official: false` so the generator can mark the rule supplementary.

Ids follow the existing schema pattern `EV-NNN` (the contract's `EV-K<nnnnn>` is not accepted by
`schemas/evidence.schema.json`). A new id is always above every id seen in the tree or referenced by the ledger, so
ids are never reused. Pure stdlib; the record is checked against the evidence schema before it is returned.
"""

import json
import re
from pathlib import Path

from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

__all__ = ["EvidenceError", "SourceIdentityError", "KNOWLEDGE_ROOT", "CATEGORY_BY_DOMAIN", "build_evidence",
           "next_evidence_id", "used_evidence_ids", "resolve_source", "repository_slug"]

SCHEMA_PATH = KNOWLEDGE_ROOT / "schemas" / "evidence.schema.json"
ORIGIN = "KAP_DETERMINISTIC"
STATUS = "DOCUMENTED_NOT_TESTED"
CHECKER = "odooflux.kap.generator"
_MAX_EVIDENCE_NUMBER = 999_999  # ids are `EV-` plus at least three digits; a real Odoo pair exceeds 999 rows
_EV_ID = re.compile(r"^EV-(\d{3,})$")
_STEP = re.compile(r"^(\d{2})-(\d{2})$")
# Ledger domain -> evidence category enum (schemas/evidence.schema.json).
CATEGORY_BY_DOMAIN = {
    "python_orm": "orm", "xml_view": "views", "xml_data": "data_files", "security": "security",
    "manifest": "manifest", "js_owl": "javascript", "assets": "assets", "data": "data_files",
    "report_controller": "controllers", "migration_script": "python_runtime", "docs": "documentation",
}


class EvidenceError(ValueError):
    """The change cannot support an evidence record, or the record does not match the schema."""


class SourceIdentityError(EvidenceError):
    """The source has no usable repository identity (`org/name`), so no evidence can name its repository."""


REPOSITORY = re.compile(r"^[a-z0-9-]+/[a-z0-9._-]+$")
_SCP_LIKE = re.compile(r"^(?:ssh://)?[^@/:]+@([^:/]+)[:/](.+)$")
_HTTPS = re.compile(r"^https://([^/]+)(/.*)?$", re.IGNORECASE)
_LOCAL = "local:"
_IDENTITY_HINT = ("give `repository` as org/name (for example odoo/odoo), or use an official source with "
                  "`expected_origin` (the https URL its verified clone's origin remote must match)")


def _origin_parts(origin: str):
    """(https origin without trailing `/` or `.git`, path) of an https or ssh/scp git URL; None when unrecognised."""
    text = origin.strip()
    scp = _SCP_LIKE.match(text)
    if scp:
        host, path = scp.group(1).lower(), scp.group(2)
    else:
        match = _HTTPS.match(text)
        if not match:
            return None
        host, path = match.group(1).lower(), match.group(2) or ""
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-len(".git")]
    path = path.rstrip("/")
    return f"https://{host}{path}", path.lstrip("/")


def repository_slug(origin) -> str | None:
    """The lower-cased `org/name` of an origin URL (host stripped), or None when it is not exactly two segments."""
    parts = _origin_parts(origin) if isinstance(origin, str) else None
    if parts is None:
        return None
    slug = parts[1].lower()
    return slug if REPOSITORY.match(slug) else None


def resolve_source(source: dict) -> dict:
    """The source with its evidence identity resolved (pure: the input is not changed).

    `repository`: an explicit spec `repository` must match `org/name` (else SourceIdentityError, no fallback); without
    one, the slug of `expected_origin`; without either, SourceIdentityError. The url never falls back to the spec url.
    `url`: a `local:` url is never written into evidence. With `expected_origin` it becomes `<origin>/tree/<revision>`,
    otherwise the path-free token `source:<source_id>@<revision>`. A remote url is kept as given.
    """
    explicit = source.get("repository")
    if explicit is not None:
        if not isinstance(explicit, str) or not REPOSITORY.match(explicit):
            raise SourceIdentityError(f"source repository {explicit!r} is not org/name; {_IDENTITY_HINT}")
        repository = explicit
    else:
        repository = repository_slug(source.get("expected_origin"))
        if repository is None:
            raise SourceIdentityError(f"source {source.get('source_id')!r} has no repository: {_IDENTITY_HINT}")
    url = source.get("url")
    if isinstance(url, str) and url.startswith(_LOCAL):
        parts = _origin_parts(source["expected_origin"]) if source.get("expected_origin") else None
        url = (f"{parts[0]}/tree/{source['revision']}" if parts
               else f"source:{source['source_id']}@{source['revision']}")
    return {**source, "repository": repository, "url": url}


def used_evidence_ids(tree_root, records) -> set:
    """Every EV id already in the tree (file names) or referenced by ledger records. Ids are never reused."""
    used = set()
    evidence_dir = Path(tree_root) / "evidence"
    if evidence_dir.is_dir():
        for path in evidence_dir.glob("EV-*.json"):
            if _EV_ID.match(path.stem):
                used.add(path.stem)
    for record in records:
        for ev_id in (record.get("disposition_data") or {}).get("evidence_ids", []):
            used.add(ev_id)
    return used


def next_evidence_id(used) -> str:
    """The next `EV-NNN[N...]` above every id in `used` (or EV-001 when none)."""
    numbers = []
    for ev_id in used:
        match = _EV_ID.match(ev_id)
        if match:
            numbers.append(int(match.group(1)))
    nxt = max(numbers, default=0) + 1
    if nxt > _MAX_EVIDENCE_NUMBER:
        raise EvidenceError(f"evidence id space exhausted (EV-{_MAX_EVIDENCE_NUMBER})")
    return f"EV-{nxt:03d}"


def _applicability(step: str) -> dict:
    match = _STEP.match(step or "")
    if not match:
        raise EvidenceError(f"step must look like NN-NN, got {step!r}")
    return {"from": f"{int(match.group(1))}.0", "to": f"{int(match.group(2))}.0"}


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def build_evidence(change: dict, *, evidence_id: str, rule_ids, source: dict, risk: str, detection_method: str,
                   proposed_transformation: str, checked_on: str, checked_by: str = CHECKER) -> dict:
    """One EvidenceRecord for `change` (a ledger record). `source` carries source_id, official, url, repository,
    revision and branch. Raises EvidenceError when the change has no location or the record fails the schema."""
    source = resolve_source(source)
    domain = change.get("domain")
    if domain not in CATEGORY_BY_DOMAIN:
        raise EvidenceError(f"no evidence category for domain {domain!r}")
    locations = change.get("locations") or []
    if not locations:
        raise EvidenceError(f"{change.get('change_id')} has no location; no evidence is invented")
    applicability = _applicability(change["step"])
    record = {
        "id": evidence_id,
        "origin": ORIGIN,
        "source_id": source["source_id"],
        "change_ids": [change["change_id"]],
        "official": bool(source["official"]),
        "rule_ids": list(rule_ids),
        "category": CATEGORY_BY_DOMAIN[domain],
        "source_applicability": applicability,
        "target_applicability": {"from": applicability["to"], "to": None},
        "description": f"{change['class']} {change['kind']} {change['subject_key']} between {change['step']}"[:300],
        "url": source["url"],
        "repository": source["repository"],
        "revision": source["revision"],
        "locations": [{
            "branch": source["branch"],
            "revision": source["revision"],
            "path": loc["path"],
            "line": loc.get("line"),
            "match": f"{change['subject_key']} ({change['class']})",
            "kind": "present",
            "content_sha256": loc["sha256"],
            "snapshot_ref": loc["snapshot_id"],
        } for loc in locations],
        "detection_method": detection_method,
        "proposed_transformation": proposed_transformation,
        "risk": risk,
        "required_validation": [],
        "status": STATUS,
        "checked_on": checked_on,
        "checked_by": checked_by,
    }
    problems = v.check(record, _schema())
    if problems:
        raise EvidenceError(f"evidence for {change['change_id']} fails the schema: {problems[:3]}")
    return record
