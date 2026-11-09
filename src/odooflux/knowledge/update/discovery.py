"""Version discovery and the read-only update check (feature 012, T04; plan Addendum B4/B6).

`read_installed_state(kb_home)` describes the active release from its `release.json` `sources` list. Any problem with the
local state (unreadable or corrupt active release, malformed sources list) is reported as `valid=False` with a short
scrubbed problem. It is never treated as an empty installation.

`check(catalog, installed, ...)` compares the catalog with what the official remotes advertise. It makes exactly one
`ls-remote` call per distinct repository (never per catalog entry), and none at all when offline or when the Enterprise
token is missing. It writes nothing. New upstream versions are reported from the remote data only: no version number is
written in this module. A discovered version is never a supported migration target (`TRANSITION_NOT_YET_SUPPORTED`).

Overall statuses (`model.OVERALL_STATUSES`) may coexist. `NO_UPDATE` is only claimed when every Community source was read
and matches, no new version exists, and no installed Enterprise source is unreadable. Freshness is only `FRESH` after a
successful read.
"""

import json
import re
from collections import OrderedDict

from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.resolver import resolve_knowledge
from odooflux.knowledge.update import remote_git as _rg
from odooflux.knowledge.update.model import (OVERALL_STATUSES, CheckReport, InstalledState, NewVersion, SourceCheck,
                                             transition_label)
from odooflux.utils.redaction import scrub

__all__ = ["SCHEMA", "ENTERPRISE_PREFIX", "read_installed_state", "check"]

SCHEMA = "odooflux.knowledge-check/1"
ENTERPRISE_PREFIX = "odoo-enterprise-"
_COMMUNITY = "community"
_ENTERPRISE = "enterprise"
_RELEASE_JSON = "release.json"
_REVISION = re.compile(r"[0-9a-f]{40}")
_SNAPSHOT_DIGEST = re.compile(r"[0-9a-f]{64}")
_BRANCH_VERSION = re.compile(r"[0-9]+\.0")  # a numeric major release branch; `saas-*`, `master` never match
_MAX_DETAIL = 200


def _detail(text, secrets=()) -> str:
    """A short, scrubbed description. Secret values and credential-shaped strings never leave this function."""
    return scrub(str(text), secrets)[:_MAX_DETAIL]


def _invalid(problem: str) -> InstalledState:
    return InstalledState(valid=False, problem=_detail(problem))


def read_installed_state(kb_home=None) -> InstalledState:
    """What the active release says is installed. Read-only: no directory is created and nothing is written.

    `kb_home` None means the resolver default (`ODOOFLUX_KB_HOME`, else the XDG path). A kb-home without an active
    pointer is the built-in knowledge: `InstalledState(release_id=None, revisions={})`.

    `snapshot_digests` comes from each source's `snapshot_digest` in the same list. A source without that key gets no
    digest; a key that is present but is not 64 lowercase hex (including null) makes the state invalid.
    """
    try:
        handle = resolve_knowledge(kb_home)
    except (KnowledgeReleaseError, OSError, ValueError) as exc:
        return _invalid(f"active release cannot be used: {exc}")
    if handle.builtin:
        return InstalledState()
    try:
        document = _read_json(handle.root / _RELEASE_JSON)
    except (OSError, ValueError):
        return _invalid("installed release manifest is unreadable")
    sources = document.get("sources") if isinstance(document, dict) else None
    if not isinstance(sources, list):
        return _invalid("installed release manifest has no sources list")
    revisions, snapshot_digests = {}, {}
    for entry in sources:
        if not isinstance(entry, dict):
            return _invalid("installed release manifest has a malformed source entry")
        source_id, revision = entry.get("source_id"), entry.get("revision")
        if not isinstance(source_id, str) or not isinstance(revision, str) or not _REVISION.fullmatch(revision):
            return _invalid("installed release manifest has a malformed source entry")
        if source_id in revisions:
            return _invalid("installed release manifest lists a source twice")
        revisions[source_id] = revision
        if "snapshot_digest" in entry:
            digest = entry["snapshot_digest"]
            if not isinstance(digest, str) or not _SNAPSHOT_DIGEST.fullmatch(digest):
                return _invalid("installed release manifest has a malformed snapshot digest")
            snapshot_digests[source_id] = digest
    return InstalledState(release_id=handle.release_id, digest=handle.digest, revisions=revisions,
                          snapshot_digests=snapshot_digests)


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _major(version: str) -> int:
    return int(str(version).split(".")[0])


def _group_by_repository(entries) -> "OrderedDict[str, list]":
    groups = OrderedDict()
    for entry in entries:
        groups.setdefault(entry.repository, []).append(entry)
    return groups


def _read_repository(repository, entries, lister, *, online, token, credential_problem, secrets):
    """One `ls-remote` for one repository. Returns (heads or None, status, detail). Never raises."""
    if not online:
        return None, "SKIPPED_OFFLINE", "network access is disabled"
    credentials = None
    if entries[0].requires_credentials:
        if credential_problem is not None:
            return None, "AUTH_FAILED", f"Enterprise credential configuration is invalid ({credential_problem})"
        if token is None:
            return None, "SKIPPED_NO_CREDENTIALS", "no Enterprise token is configured"
        credentials = token
    try:
        heads = lister(repository, offline=False, credentials=credentials)
    except _rg.NetworkDisabled:
        return None, "SKIPPED_OFFLINE", "network access is disabled"
    except SourceError as exc:
        code = getattr(exc, "code", None)
        if code == "AUTH_FAILED":
            return None, "AUTH_FAILED", "the remote rejected the credentials"
        if code == "AUTH_REQUIRED":
            return None, "SKIPPED_NO_CREDENTIALS", "the remote requires credentials"
        message = _detail(getattr(exc, "message", exc), secrets)
        return None, "UNAVAILABLE", f"{code or 'remote error'}: {message}"
    except Exception as exc:  # a diagnostic check reports the failure instead of crashing
        return None, "UNAVAILABLE", f"remote check failed ({type(exc).__name__})"
    if not isinstance(heads, dict):
        return None, "UNAVAILABLE", "the remote returned no branch list"
    return heads, "OK", ""


def _label_pairs(pairs) -> tuple:
    """Unique transition labels from (from_version, to_version) pairs, in numeric order."""
    unique = sorted({(_major(a), _major(b), a, b) for a, b in pairs})
    labels = []
    for _, _, a, b in unique:
        label = transition_label(a, b)
        if label not in labels:
            labels.append(label)
    return tuple(labels)


def _enterprise_freshness(installed: InstalledState, checks_by_id: dict) -> str:
    installed_enterprise = [sid for sid in installed.revisions if sid.startswith(ENTERPRISE_PREFIX)]
    if not installed_enterprise:
        return "NOT_INSTALLED"
    checks = [checks_by_id.get(sid) for sid in installed_enterprise]
    if any(c is not None and c.status == "OK" and c.changed() for c in checks):
        return "OUTDATED"
    if all(c is not None and c.status == "OK" for c in checks):
        return "FRESH"
    return "UNKNOWN"


def check(catalog, installed: InstalledState, *, offline: bool = False, token=None, ls_remote=None, now=None,
          credential_problem=None) -> CheckReport:
    """Compare the catalog with the remotes. Read-only; see the module docstring for the status rules.

    `token` is a `credentials.Token` or None. `ls_remote` is an injectable callable with the signature of
    `remote_git.ls_remote_heads` (default: that function, resolved at call time). `credential_problem` is a
    CredentialError code when the configured Enterprise credentials are unusable: Enterprise sources are then reported
    AUTH_FAILED without any call. `now` is accepted for interface stability; the report carries no timestamp.
    """
    lister = ls_remote if ls_remote is not None else _rg.ls_remote_heads
    online = _rg.network_allowed(offline)
    if not installed.valid:
        return CheckReport(schema=SCHEMA, statuses=("LOCAL_STATE_INVALID",), sources=(), new_versions=(),
                           affected_transitions=(), enterprise_freshness="UNKNOWN", catalog_digest=catalog.digest,
                           offline=not online, installed_release=installed.release_id)

    secrets = (token,) if token is not None else ()
    groups = _group_by_repository(catalog.entries)
    results = {}  # repository -> (heads or None, status, detail); one read per distinct repository
    for repository, entries in groups.items():
        results[repository] = _read_repository(repository, entries, lister, online=online, token=token,
                                               credential_problem=credential_problem, secrets=secrets)

    checks = []
    for entry in catalog.entries:  # catalog order
        heads, status, detail = results[entry.repository]
        remote_sha = None
        if status == "OK":
            candidate = heads.get(entry.branch)
            if isinstance(candidate, str) and _REVISION.fullmatch(candidate):
                remote_sha = candidate
            else:
                status, detail = "UNAVAILABLE", "branch not found on the remote"
        source_id = catalog.source_id(entry)
        checks.append(SourceCheck(source_id=source_id, edition=entry.edition, version=entry.version,
                                  remote_sha=remote_sha, installed_sha=installed.revisions.get(source_id),
                                  status=status, detail=detail))

    new_versions = []
    for repository, entries in groups.items():
        heads = results[repository][0]
        if heads is None:
            continue
        known_branches = {entry.branch for entry in entries}
        numeric = [b for b in heads if _BRANCH_VERSION.fullmatch(b) and b not in known_branches]
        for branch in sorted(numeric, key=lambda b: (_major(b), b)):
            sha = heads[branch]
            if isinstance(sha, str) and _REVISION.fullmatch(sha):
                new_versions.append(NewVersion(edition=entries[0].edition, version=branch, branch=branch,
                                               remote_sha=sha))
    new_versions = tuple(new_versions)

    changed_ids = {c.source_id for c in checks if c.changed()}
    pairs = []
    for edition in catalog.editions():
        for low, high in catalog.pairs(edition):
            ids = {catalog.source_id(catalog.entry_for(low, edition)),
                   catalog.source_id(catalog.entry_for(high, edition))}
            if ids & changed_ids:
                pairs.append((low, high))
    for nv in new_versions:
        versions = catalog.versions(nv.edition)
        if versions and _major(nv.version) > _major(versions[-1]):
            pairs.append((versions[-1], nv.version))
    affected = _label_pairs(pairs)

    community_ok = any(c.edition == _COMMUNITY and c.status == "OK" for c in checks)
    any_changed = any(c.changed() for c in checks)
    checks_by_id = {c.source_id: c for c in checks}
    unverified_enterprise = any(
        sid.startswith(ENTERPRISE_PREFIX) and (sid not in checks_by_id or checks_by_id[sid].status != "OK")
        for sid in installed.revisions)
    unverified_community = any(c.edition == _COMMUNITY and c.status != "OK" for c in checks)

    found = set()
    if not community_ok:
        found.add("CHECK_UNAVAILABLE")
    if new_versions:
        found.update(("NEW_VERSION_DISCOVERED", "TRANSITION_NOT_YET_SUPPORTED"))
    if any_changed:
        found.add("SOURCE_REVISION_AVAILABLE")
        # Installed release or fresh install (no release installed): both are a knowledge update.
        found.add("KNOWLEDGE_UPDATE_AVAILABLE")
    if community_ok and not any_changed and not new_versions and not unverified_community and not unverified_enterprise:
        found.add("NO_UPDATE")
    statuses = tuple(status for status in OVERALL_STATUSES if status in found)

    return CheckReport(schema=SCHEMA, statuses=statuses, sources=tuple(checks), new_versions=new_versions,
                       affected_transitions=affected,
                       enterprise_freshness=_enterprise_freshness(installed, checks_by_id),
                       catalog_digest=catalog.digest, offline=not online,
                       installed_release=installed.release_id)
