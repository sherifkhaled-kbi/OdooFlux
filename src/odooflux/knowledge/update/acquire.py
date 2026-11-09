"""Update acquisition (feature 012, plan Addendum B4 and C1): turns an `UpdatePlan` into verified local clones in the
managed cache plus the registry specs that a build needs.

A BLOCKED plan is refused with ValueError before anything runs.

Per planned source, in plan order:
- ACQUIRE: fetched BY SHA through `remote_git.fetch_commit` (or the injected `fetch`), which verifies the commit. The
  result is a spec whose `url` is `local:<repo_path>` inside the managed cache. Community fetches never receive
  credentials. An Enterprise source without a token is SKIPPED_NO_CREDENTIALS and nothing is contacted.
- ACQUIRE that fails and is NOT required, but has an `installed_sha`: it becomes a carried participant. Its failure
  status and detail stay in `results`, and its plan spec at the installed revision is added to `specs` and its id to
  `carried_source_ids`. Without an installed revision it is left out.
- CARRY_FORWARD: no fetch. The plan spec is used as emitted, with `revision` set to `installed_sha`, and the source is
  listed in `carried_source_ids` for the RetainedSnapshotAdapter (C1). A carried source without a valid installed
  revision is UNAVAILABLE.
- SKIP: not part of this build.

Offline (the argument or ODOOFLUX_OFFLINE) means no fetch call at all: every ACQUIRE source is SKIPPED_OFFLINE, and the
token is not read. Carried sources need no network and are still reported.

A required source that ends up neither ACQUIRED nor CARRIED sets `blocking` to (source_id, status) and stops further
processing. Every plan source after it gets a NOT_ATTEMPTED row with no detail, so silence is never inferred. Failure details pass through
`utils.redaction.scrub`, with the token value as a secret whenever a token is attached to the call.

Nothing is written here. Every filesystem write happens inside `fetch_commit`, under `cache_dir`. kb-home is never touched.
"""

import copy
import os
import re
import urllib.parse
from dataclasses import dataclass

from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.acquisition.sources import normalize_origin
from odooflux.knowledge.update import remote_git as rg
from odooflux.knowledge.update.credentials import Token
from odooflux.utils.redaction import scrub

__all__ = ["STATUSES", "SourceAcquisition", "AcquireResult", "acquire"]

ACQUIRED = "ACQUIRED"
CARRIED = "CARRIED"
SKIPPED_NO_CREDENTIALS = "SKIPPED_NO_CREDENTIALS"
SKIPPED_OFFLINE = "SKIPPED_OFFLINE"
AUTH_FAILED = "AUTH_FAILED"
UNAVAILABLE = "UNAVAILABLE"
REVISION_UNAVAILABLE = "REVISION_UNAVAILABLE"
NOT_REQUIRED = "NOT_REQUIRED"
NOT_ATTEMPTED = "NOT_ATTEMPTED"
STATUSES = (ACQUIRED, CARRIED, SKIPPED_NO_CREDENTIALS, SKIPPED_OFFLINE, AUTH_FAILED, UNAVAILABLE,
            REVISION_UNAVAILABLE, NOT_REQUIRED, NOT_ATTEMPTED)
_OK = (ACQUIRED, CARRIED)
# Failures of a non-required ACQUIRE that fall back to the installed revision when one is known.
_FALLBACK = (SKIPPED_NO_CREDENTIALS, SKIPPED_OFFLINE, AUTH_FAILED, UNAVAILABLE, REVISION_UNAVAILABLE)

_HEX40 = re.compile(r"[0-9a-f]{40}")
_REPOSITORY = re.compile(r"[a-z0-9-]+/[a-z0-9._-]+")  # owner/name, the source_meta pattern
_DETAIL_LIMIT = 200
# Remote failure codes that keep their meaning in the status. Anything else (IO_ERROR, NOT_ALLOWLISTED, ...) is
# reported as UNAVAILABLE with the code in the detail.
_REMOTE_STATUS = {
    "AUTH_REQUIRED": SKIPPED_NO_CREDENTIALS,
    "AUTH_FAILED": AUTH_FAILED,
    "UNAVAILABLE": UNAVAILABLE,
    "REVISION_UNAVAILABLE": REVISION_UNAVAILABLE,
}


@dataclass(frozen=True)
class SourceAcquisition:
    source_id: str
    status: str
    repo_path: object = None  # absolute managed-cache path, ACQUIRED only
    revision: object = None  # 40-hex: the verified fetched SHA, or the installed SHA when CARRIED
    detail: str = ""  # short and scrubbed

    def to_dict(self) -> dict:
        return {"source_id": self.source_id, "status": self.status, "repo_path": self.repo_path,
                "revision": self.revision, "detail": self.detail}


@dataclass(frozen=True)
class AcquireResult:
    results: list  # one SourceAcquisition per plan source, in plan order (NOT_ATTEMPTED after a blocking source)
    specs: list  # registry spec dicts for every participating source that has one, in plan order
    carried_source_ids: list  # CARRIED participants (including fallbacks), in plan order
    source_meta: dict  # {source_id: {"repository": "owner/name"}}
    blocking: object = None  # (source_id, status) of the first required source that is not ACQUIRED or CARRIED

    def to_dict(self) -> dict:
        return {"results": [r.to_dict() for r in self.results], "specs": copy.deepcopy(self.specs),
                "carried_source_ids": list(self.carried_source_ids), "source_meta": copy.deepcopy(self.source_meta),
                "blocking": None if self.blocking is None else list(self.blocking)}


@dataclass(frozen=True)
class _Outcome:
    result: SourceAcquisition
    spec: object = None
    meta: object = None
    carried: bool = False


def acquire(plan, *, cache_dir, token=None, offline=False, fetch=None, transport_for=None) -> AcquireResult:
    """Acquire every ACQUIRE source of `plan` into `cache_dir` and report every CARRY_FORWARD source.

    `token` is a `credentials.Token` (the caller resolves it, for example with `resolve_enterprise_token`). It is
    attached only to Enterprise fetches. `fetch` defaults to `remote_git.fetch_commit` and must accept the same keyword
    arguments. `transport_for(source_id)` returns a local transport path; it is a test seam only and is passed as
    `transport_url`.
    """
    if getattr(plan, "decision", None) == "BLOCKED":
        raise ValueError("plan is BLOCKED; nothing is acquired from a blocked plan")
    if token is not None and not isinstance(token, Token):
        raise TypeError("token must be a credentials.Token or None")
    fetch = rg.fetch_commit if fetch is None else fetch
    network = rg.network_allowed(offline)
    results, specs, carried, meta = [], [], [], {}
    blocking = None
    for index, src in enumerate(plan.sources):
        outcome = _process(src, token=token, network=network, fetch=fetch, transport_for=transport_for,
                           cache_dir=cache_dir)
        sid = src.source_id
        results.append(outcome.result)
        if outcome.spec is not None:
            specs.append(outcome.spec)
            if outcome.meta is not None:
                meta[sid] = outcome.meta
        if outcome.carried:
            carried.append(sid)
        if src.required and outcome.result.status not in _OK:
            blocking = (sid, outcome.result.status)
            results.extend(SourceAcquisition(rest.source_id, NOT_ATTEMPTED)
                           for rest in plan.sources[index + 1:])
            break
    return AcquireResult(results=results, specs=specs, carried_source_ids=carried, source_meta=meta, blocking=blocking)


def _process(src, *, token, network, fetch, transport_for, cache_dir) -> _Outcome:
    if src.action == "CARRY_FORWARD":
        return _carried(src)
    if src.action == "ACQUIRE":
        outcome = _acquire_one(src, token=token, network=network, fetch=fetch, transport_for=transport_for,
                               cache_dir=cache_dir)
        if outcome.result.status in _FALLBACK and not src.required:
            return _fall_back(src, outcome)
        return outcome
    return _skipped(src, token)


def _carried(src) -> _Outcome:
    """A CARRY_FORWARD source: the plan spec as emitted, at the installed revision. No fetch."""
    sid = src.source_id
    revision = _valid_sha(src.installed_sha)
    if revision is None:
        return _Outcome(SourceAcquisition(sid, UNAVAILABLE, None, None,
                                          "installed revision missing; cannot carry forward"))
    spec, meta = _spec_at(src, revision)
    return _Outcome(SourceAcquisition(sid, CARRIED, None, revision, "carried forward from the installed release"),
                    spec, meta, carried=True)


def _fall_back(src, outcome) -> _Outcome:
    """A failed non-required ACQUIRE with a known installed revision participates as carried. The failure row is kept."""
    revision = _valid_sha(src.installed_sha)
    if revision is None:
        return outcome
    spec, meta = _spec_at(src, revision)
    return _Outcome(outcome.result, spec, meta, carried=True)


def _skipped(src, token) -> _Outcome:
    """A SKIP source is not part of the build. A required one is reported as UNAVAILABLE, which blocks the run."""
    if src.edition == "enterprise" and token is None:
        status, detail = SKIPPED_NO_CREDENTIALS, "Enterprise token not supplied; not contacted"
    elif src.required:
        status, detail = UNAVAILABLE, "required source was not planned for acquisition"
    else:
        status, detail = NOT_REQUIRED, "not part of this build"
    return _Outcome(SourceAcquisition(src.source_id, status, None, None, detail))


def _acquire_one(src, *, token, network, fetch, transport_for, cache_dir) -> _Outcome:
    sid = src.source_id
    spec = src.spec or {}
    origin = _declared_origin(spec)
    owner = _owner_repo(origin) if origin else None
    url = spec.get("url")
    if owner is None or not isinstance(url, str) or normalize_origin(url) != origin:
        return _failed(sid, UNAVAILABLE, "plan carries no consistent declared origin")
    enterprise = _is_enterprise(src, origin)
    if not network:  # the token is not read on this path
        return _failed(sid, SKIPPED_OFFLINE, "network disabled; not contacted")
    if enterprise and token is None:
        return _failed(sid, SKIPPED_NO_CREDENTIALS, "Enterprise token not supplied; not contacted")
    sha = src.target_sha
    if not isinstance(sha, str) or _HEX40.fullmatch(sha) is None:
        return _failed(sid, REVISION_UNAVAILABLE, "planned revision is not a full 40-hex commit")
    transport = transport_for(sid) if transport_for is not None else None
    try:
        path = fetch(url, branch=spec.get("branch"), expected_sha=sha, cache_dir=cache_dir, offline=False,
                     transport_url=transport, credentials=token if enterprise else None)
    except rg.NetworkDisabled:
        return _failed(sid, SKIPPED_OFFLINE, "network disabled; not contacted")
    except SourceError as exc:
        code = getattr(exc, "code", None)
        message = getattr(exc, "message", None) or str(exc)
        return _failed(sid, _REMOTE_STATUS.get(code, UNAVAILABLE), f"{code or 'ERROR'}: {message}", token=token)
    repo = _contained(path, cache_dir, sha)
    if repo is None:
        return _failed(sid, UNAVAILABLE, "fetch returned a path outside the managed cache", token=token)
    out = copy.deepcopy(spec)
    out["url"] = f"local:{repo}"
    out["revision"] = sha
    result = SourceAcquisition(sid, ACQUIRED, repo, sha, "verified commit cached")
    return _Outcome(result, out, {"repository": owner})


def _spec_at(src, revision):
    """(spec, meta): the plan's own spec with `revision` set. Nothing is rebuilt. No spec when the plan has none."""
    if not src.spec:
        return None, None
    spec = copy.deepcopy(src.spec)
    spec["revision"] = revision
    origin = _declared_origin(spec)
    owner = _owner_repo(origin) if origin else None
    return spec, ({"repository": owner} if owner else None)


def _valid_sha(value):
    return value if isinstance(value, str) and _HEX40.fullmatch(value) else None


def _failed(sid, status, detail, *, token=None, revision=None) -> _Outcome:
    return _Outcome(SourceAcquisition(sid, status, None, revision, _detail(detail, token)))


def _detail(text, token) -> str:
    """Short text with the token value and credential-shaped strings removed. The token is revealed only here, and only
    when a token was attached to the call that produced the text."""
    secrets = () if token is None else (token.reveal(),)
    return scrub(str(text), secrets=secrets)[:_DETAIL_LIMIT]


def _declared_origin(spec):
    expected = spec.get("expected_origin")
    if not isinstance(expected, str) or not expected:
        return None
    return normalize_origin(expected)


def _owner_repo(origin):
    """`owner/name` of an https origin, or None when the path does not match the source_meta pattern."""
    path = urllib.parse.urlsplit(origin).path.strip("/")
    return path if _REPOSITORY.fullmatch(path) else None


def _is_enterprise(src, origin=None) -> bool:
    return src.edition == "enterprise" or (origin is not None and origin == rg.ENTERPRISE_IDENTITY)


def _contained(path, cache_dir, sha):
    """The absolute repository path when `path` is a directory named by `sha` strictly under `cache_dir`, else None.
    The check runs on resolved paths, so a symlink that points outside the cache is refused."""
    if not isinstance(path, (str, os.PathLike)):
        return None
    text = os.fspath(path)
    real = os.path.realpath(text)
    base = os.path.realpath(os.fspath(cache_dir))
    if os.path.basename(text) != sha or real == base:
        return None
    if os.path.commonpath([real, base]) != base or not os.path.isdir(real):
        return None
    return os.path.abspath(text)
