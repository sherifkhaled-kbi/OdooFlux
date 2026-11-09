"""Source registry and status machine (REQ-KAP-006, REQ-KAP-008, REQ-KAP-009; source-adapter contract).

A registry entry is a SourceSpec (`schemas/source_registry.schema.json`). The registry is data-driven: adapters
register by `kind` in `ADAPTERS`. Specs are normalised before validation, so OCA and OpenUpgrade are always
`official=false` whatever the spec file says (rule 5). Remote URLs must match the allow-list by prefix (rule 3);
`local:` inputs skip the allow-list. Git kinds need a full 40-hex revision (rule 2). Branches are informational.

Official local clones (`official=true` with a `local:` url) are trusted only through `expected_origin`: the https URL the
clone must have as its `origin` remote. The adapter verifies the remote at acquisition time (git_local.py) and records the
verified value as `origin_url`. A `local:` claim without `expected_origin` is never official.
"""

import copy
import json
import re
from pathlib import Path

from odooflux.knowledge import validator as v
from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.utils.redaction import redact_text

__all__ = [
    "SourceError", "RegistryError", "SourceRegistry", "ADAPTERS", "register_adapter", "KINDS", "STATUSES",
    "TRANSITIONS", "load_allow_list", "require_allowed", "normalize", "validate_spec", "normalize_origin",
    "origin_under_prefix", "origin_allowed", "official_origin", "verify_declared_origin", "OFFICIAL_PREFIX",
    "CREDENTIALS_CODE", "has_url_credentials", "GIT_KINDS", "ENTERPRISE_KINDS", "is_enterprise_kind",
    "ENTERPRISE_CONFIDENTIALITY", "ENTERPRISE_LICENCE_ACCESS", "ENTERPRISE_ENTRY_FIELDS", "LICENCE_CODE",
    "licence_problem", "enterprise_entry_problem",
]

KINDS = (
    "GIT_COMMUNITY", "GIT_ENTERPRISE", "DOCS", "UPGRADE_SCRIPTS", "ENTERPRISE_LOCAL", "OCA", "OPENUPGRADE",
    "SNAPSHOT_PACK", "DIRECTORY",
)
GIT_KINDS = ("GIT_COMMUNITY", "GIT_ENTERPRISE", "DOCS", "UPGRADE_SCRIPTS", "OCA", "OPENUPGRADE")
FORCED_UNOFFICIAL = ("OCA", "OPENUPGRADE")
# the only remote prefixes for which official=true is valid
OFFICIAL_PREFIX = {
    "GIT_COMMUNITY": "https://github.com/odoo/odoo/",
    "GIT_ENTERPRISE": "https://github.com/odoo/enterprise/",
    "DOCS": "https://github.com/odoo/documentation/",
}
# Enterprise kinds hold licensed content. Classification is by kind only, never by a record field. ENTERPRISE_LOCAL is
# never official; GIT_ENTERPRISE may be official under the same identity rules as GIT_COMMUNITY, plus a licence.
ENTERPRISE_KINDS = ("GIT_ENTERPRISE", "ENTERPRISE_LOCAL")
ENTERPRISE_CONFIDENTIALITY = "enterprise"
ENTERPRISE_LICENCE_ACCESS = "ENTERPRISE_AUTHORIZED"
# provenance fields carried only by enterprise entries (all three or none)
ENTERPRISE_ENTRY_FIELDS = ("confidentiality", "licence_id", "licence_access")
LICENCE_CODE = "LICENCE_UNVERIFIED"
# closed failure codes (data-model SourceSpec.failure_reason); the text after the code is free
FAILURE_CODES = ("REVISION_UNAVAILABLE", "CHECKSUM_MISMATCH", "AUTH_REQUIRED", "NOT_ALLOWLISTED", "IO_ERROR",
                 "OFFICIAL_IDENTITY_UNVERIFIED")

STATUSES = ("DECLARED", "RETRIEVED", "VERIFIED", "UNAVAILABLE", "FAILED", "SKIPPED_UNAUTHORIZED")
# VERIFIED and SKIPPED_UNAUTHORIZED are terminal. FAILED and UNAVAILABLE may be retried from DECLARED.
TRANSITIONS = {
    "DECLARED": {"RETRIEVED", "FAILED", "UNAVAILABLE", "SKIPPED_UNAUTHORIZED"},
    "RETRIEVED": {"VERIFIED", "FAILED", "UNAVAILABLE"},
    "FAILED": {"DECLARED"},
    "UNAVAILABLE": {"DECLARED"},
    "VERIFIED": set(),
    "SKIPPED_UNAUTHORIZED": set(),
}
NEEDS_REASON = ("FAILED", "UNAVAILABLE")
_SCP_LIKE = re.compile(r"^(?:ssh://)?[^@/:]+@([^:/]+)[:/](.+)$")
_HTTPS_URL = re.compile(r"^https://([^/]+)(/.*)?$", re.IGNORECASE)
# credentials in the authority of a scheme URL (REQ-KAP-046): `user:password@`, or a long bare token before `@`.
# A short bare username (`ssh://git@github.com/...`) is not a credential and stays accepted.
_USERINFO = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://(?:[^/?#\s@]*:[^/?#\s@]*|[A-Za-z0-9_\-]{20,})@")
CREDENTIALS_CODE = "URL_CREDENTIALS"

_SCHEMA_PATH = KNOWLEDGE_ROOT / "schemas" / "source_registry.schema.json"
_ALLOW_LIST_PATH = KNOWLEDGE_ROOT / "official_sources" / "allow_list.json"

ADAPTERS: dict = {}


class RegistryError(ValueError):
    """A spec or transition breaks the registry rules."""


def load_allow_list(path=None) -> list:
    """URL prefixes from `official_sources/allow_list.json`."""
    data = json.loads(Path(path or _ALLOW_LIST_PATH).read_text(encoding="utf-8"))
    return [e["prefix"] for e in data if isinstance(e, dict) and "prefix" in e]


def require_allowed(url: str, allow_list: list, source_id) -> None:
    """Fail closed: a remote URL must start with an allow-listed prefix. `local:` inputs are not network sources."""
    if url.startswith("local:"):
        return
    if not any(url.startswith(prefix) for prefix in allow_list):
        raise SourceError("NOT_ALLOWLISTED", source_id, f"{url!r} is not under an allow-listed prefix")


def normalize(spec: dict) -> dict:
    """Copy of *spec* with the adapter-forced fields applied (OCA and OpenUpgrade are never official)."""
    out = copy.deepcopy(spec)
    if out.get("kind") in FORCED_UNOFFICIAL:
        out["official"] = False
    return out


def normalize_origin(url: str) -> str:
    """Canonical form of a git remote URL for identity comparison. Converts scp-like and ssh forms
    (`git@github.com:org/repo`, `ssh://git@github.com/org/repo`) to `https://github.com/org/repo`, lowercases the
    scheme and host, and strips trailing `/` and `.git`. Path case is kept. Anything else is returned stripped and
    unchanged, so it fails the prefix check."""
    text = url.strip()
    scp = _SCP_LIKE.match(text)
    if scp:
        text = f"https://{scp.group(1)}/{scp.group(2)}"
    match = _HTTPS_URL.match(text)
    if not match:
        return text
    path = (match.group(2) or "").rstrip("/")
    if path.endswith(".git"):
        path = path[:-len(".git")]
    return f"https://{match.group(1).lower()}{path.rstrip('/')}"


def has_url_credentials(url) -> bool:
    """True when a URL string carries userinfo (`user:password@` or a bare token before `@`). Credentials in a
    configured URL are a configuration error: such a source is refused (code `URL_CREDENTIALS`), never normalised."""
    return isinstance(url, str) and _USERINFO.match(url.strip()) is not None


def origin_under_prefix(origin: str, prefix: str) -> bool:
    """True when a normalised https origin lies under an allow-list prefix (the prefix ends at a slash)."""
    return origin.startswith("https://") and (origin + "/").startswith(prefix)


def origin_allowed(url: str, allow_list: list) -> bool:
    """True when *url*, once normalised, is an https URL under an allow-listed prefix."""
    origin = normalize_origin(url)
    return any(origin_under_prefix(origin, prefix) for prefix in allow_list)


def official_origin(kind: str, url: str, allow_list: list):
    """The normalised origin when *url* is an allow-listed https URL under the official prefix of *kind*
    (a kind in OFFICIAL_PREFIX); None otherwise. Shared by the git-local adapter and release gate 1.

    Trust statement: a configured git remote URL is only a declared identity. It is NOT cryptographic proof of
    repository authenticity. This contract checks consistency between the declared origin, the allow-list, the pinned
    commit and the content digest. A malicious local clone with a forged origin remote is a residual risk that only an
    external trust anchor (signed tags, or hashes published by the maintainers) could close.
    """
    prefix = OFFICIAL_PREFIX.get(kind)
    if prefix is None or not url or has_url_credentials(url):
        return None
    origin = normalize_origin(url)
    if not origin_under_prefix(origin, prefix) or not origin_allowed(origin, allow_list):
        return None
    return origin


def verify_declared_origin(remote: str, expected: str, kind: str, allow_list: list):
    """The verified origin of a local clone: its `origin` remote must equal `expected_origin` after normalisation,
    and both must pass `official_origin`. None means unverified (the caller reports OFFICIAL_IDENTITY_UNVERIFIED).
    The same trust statement as `official_origin` applies."""
    if not remote or not expected or normalize_origin(remote) != normalize_origin(expected):
        return None
    return official_origin(kind, remote, allow_list)


def is_enterprise_kind(kind) -> bool:
    """True for a source kind whose content is Enterprise-licensed (see ENTERPRISE_KINDS)."""
    return kind in ENTERPRISE_KINDS


def licence_problem(licence_access, licence_id):
    """None when an Enterprise licence is verifiable: `ENTERPRISE_AUTHORIZED` access and a real licence identifier.
    The message names the field and never repeats its value, because a value here may be a credential."""
    if licence_access != ENTERPRISE_LICENCE_ACCESS:
        return "licence_access must be ENTERPRISE_AUTHORIZED"
    if not isinstance(licence_id, str) or not licence_id.strip():
        return "licence_id must be a non-empty string"
    if licence_id.strip().upper() == "UNKNOWN":
        return "licence_id must name a licence, not UNKNOWN"
    if redact_text(licence_id) != licence_id:
        return "licence_id must be an identifier, not a credential-shaped value"
    return None


def enterprise_entry_problem(entry: dict):
    """Coherence of the enterprise fields of one provenance entry, or None when coherent. Shared by
    `provenance.verify_provenance` and release gate 1, so both refuse the same forgeries. A GIT_ENTERPRISE entry must
    say confidentiality "enterprise" and carry a verifiable licence. ENTERPRISE_LOCAL is never official. Every other
    kind must carry no enterprise field."""
    kind = entry.get("kind")
    if kind == "ENTERPRISE_LOCAL":
        return "enterprise-local source is never official or shipped"
    if kind == "GIT_ENTERPRISE":
        if entry.get("confidentiality") != ENTERPRISE_CONFIDENTIALITY:
            return "GIT_ENTERPRISE entry must carry confidentiality enterprise"
        return licence_problem(entry.get("licence_access"), entry.get("licence_id"))
    if any(key in entry for key in ENTERPRISE_ENTRY_FIELDS):
        return f"{kind} entry must not carry enterprise fields"
    return None


def validate_spec(spec: dict, allow_list: list) -> list:
    """Problems as (pointer, message) pairs. An empty list means the spec may be registered."""
    creds = [pointer for pointer, value in (("/url", spec.get("url")), ("/expected_origin", spec.get("expected_origin")))
             if has_url_credentials(value)]
    if creds:  # refused before any schema message can echo the value; the message never repeats the URL
        return [(pointer, f"{CREDENTIALS_CODE}: remove user:password from the URL; credentials in a URL are a "
                          f"configuration error") for pointer in creds]
    spec = normalize(spec)
    problems = v.check(spec, json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))
    if problems:
        return problems
    kind, url = spec["kind"], spec["url"]
    expected = spec.get("expected_origin")
    if kind in GIT_KINDS and not _is_hex40(spec["revision"]):
        problems.append(("/revision", "git sources need a full 40-hex commit SHA"))
    if expected is not None and not origin_allowed(expected, allow_list):
        problems.append(("/expected_origin", "expected_origin is not an allow-listed https URL"))
    if spec["official"]:
        prefix = OFFICIAL_PREFIX.get(kind)
        if prefix is None:
            problems.append(("/official", "official=true needs kind GIT_COMMUNITY, GIT_ENTERPRISE or DOCS"))
        elif url.startswith("local:"):
            if not expected:
                problems.append(("/expected_origin", "official local clone needs expected_origin, the https URL "
                                                     "its origin remote must match"))
            elif official_origin(kind, expected, allow_list) is None:
                problems.append(("/expected_origin", f"expected_origin must be under {prefix}"))
        elif not url.startswith(prefix):
            problems.append(("/official", f"official=true needs kind {kind} under {prefix}"))
    if not url.startswith("local:") and not any(url.startswith(p) for p in allow_list):
        problems.append(("/url", "remote URL is not under an allow-listed prefix"))
    return problems


def _is_hex40(text: str) -> bool:
    return len(text) == 40 and all(c in "0123456789abcdef" for c in text)


def register_adapter(kind: str, adapter) -> None:
    """Register an adapter for a source kind. Unknown kinds are refused."""
    if kind not in KINDS:
        raise ValueError(f"unknown source kind {kind!r}")
    ADAPTERS[kind] = adapter


class SourceRegistry:
    """In-memory registry keyed by source_id. Persistence is added by the CLI task (T040)."""

    def __init__(self, allow_list=None):
        self._allow = load_allow_list() if allow_list is None else list(allow_list)
        self._specs: dict = {}

    def add(self, spec: dict) -> None:
        problems = validate_spec(spec, self._allow)
        if spec.get("status") != "DECLARED":
            problems.append(("/status", "a new source must start as DECLARED"))
        for key in ("retrieved_at", "checksum", "failure_reason", "origin_url"):
            if spec.get(key) is not None:
                problems.append((f"/{key}", "must be null before retrieval"))
        if spec.get("source_id") in self._specs:
            problems.append(("/source_id", "already registered"))
        if problems:
            raise RegistryError("; ".join(f"{p or '/'}: {m}" for p, m in problems))
        self._specs[spec["source_id"]] = normalize(spec)

    def get(self, source_id: str) -> dict:
        if source_id not in self._specs:
            raise RegistryError(f"unknown source {source_id!r}")
        return copy.deepcopy(self._specs[source_id])

    def sources(self) -> list:
        return [copy.deepcopy(self._specs[k]) for k in sorted(self._specs)]

    def transition(self, source_id: str, new_status: str, *, failure_reason=None, checksum=None,
                   retrieved_at=None, origin_url=None) -> None:
        """Move a source along the status machine. Failure statuses need a closed failure code."""
        rec = self.get(source_id)
        current = rec["status"]
        if new_status not in TRANSITIONS.get(current, set()):
            raise RegistryError(f"{source_id}: {current} -> {new_status} is not allowed")
        if new_status in NEEDS_REASON:
            code = (failure_reason or "").split(" ", 1)[0].rstrip(":")
            if code not in FAILURE_CODES:
                raise RegistryError(f"{source_id}: {new_status} needs a failure code from {FAILURE_CODES}")
        rec["status"] = new_status
        rec["failure_reason"] = failure_reason if new_status in NEEDS_REASON + ("SKIPPED_UNAUTHORIZED",) else None
        if new_status == "DECLARED":
            rec["retrieved_at"], rec["checksum"] = None, None
            rec.pop("origin_url", None)
        if checksum is not None:
            rec["checksum"] = checksum
        if retrieved_at is not None:
            rec["retrieved_at"] = retrieved_at
        if origin_url is not None:
            rec["origin_url"] = origin_url
        problems = v.check(rec, json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))
        if problems:
            raise RegistryError(f"{source_id}: record would be invalid: {problems}")
        self._specs[source_id] = rec

