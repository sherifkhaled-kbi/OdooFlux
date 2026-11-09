"""Official source catalog for Odoo editions (feature 012, catalog v2, plan addendum A1).

`catalog.json` is package data. Each entry names a git branch (== version) for one edition: `community` (public
GIT_COMMUNITY source; licence_access PUBLIC_OPEN, redistribution PUBLIC) or `enterprise` (GIT_ENTERPRISE source, needs
credentials; licence_access ENTERPRISE_AUTHORIZED, redistribution RESTRICTED). The retired kind ENTERPRISE_LOCAL is
refused. The commit SHA is resolved at acquisition time, so no SHA is stored in the file. The catalog digest is computed
from the parsed document and never stored in it.

Licence fields (schema 3): `licence_id` is declared by OdooFlux maintainers. The loader checks its form (a bounded
identifier with no whitespace or control characters) and refuses placeholders such as UNKNOWN, but it does NOT verify
the licence against the upstream repository; that is a maintainer responsibility. `licence_access` describes repository
ACCESS authorization only. It is NOT a statement about redistribution rights, which `redistribution` records separately
(PUBLIC or RESTRICTED). Both are exact values per edition, validated like every other contract field.

Validation is fail-closed: every problem raises CatalogError with a stable code. The error message never echoes a URL
value, so a credential-bearing URL cannot leak through an error. Stdlib only, plus the knowledge.acquisition.sources
URL rules that the registry already applies.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from odooflux.knowledge.acquisition import sources

__all__ = ["CatalogError", "CatalogEntry", "Catalog", "load_catalog", "CATALOG_PATH", "MAX_CATALOG_BYTES", "EDITIONS"]

CATALOG_PATH = Path(__file__).with_name("catalog.json")
MAX_CATALOG_BYTES = 256 * 1024
SCHEMA_VERSION = 3
FAMILY = "odoo"
VERIFICATION = "immutable-sha"
OFFICIAL_KIND = "source"

# Edition contract: the only legal repository, expected origin, kind and credential requirement per edition.
EDITIONS = ("community", "enterprise")
_EDITION_SPEC = {
    "community": {
        "repository": "https://github.com/odoo/odoo.git",
        "expected_origin": "https://github.com/odoo/odoo",
        "kind": "GIT_COMMUNITY",
        "requires_credentials": False,
        "licence_access": "PUBLIC_OPEN",
        "redistribution": "PUBLIC",
    },
    "enterprise": {
        "repository": "https://github.com/odoo/enterprise.git",
        "expected_origin": "https://github.com/odoo/enterprise",
        "kind": "GIT_ENTERPRISE",
        "requires_credentials": True,
        "licence_access": "ENTERPRISE_AUTHORIZED",
        "redistribution": "RESTRICTED",
    },
}
_RETIRED_KINDS = ("ENTERPRISE_LOCAL",)

_TOP_KEYS = ("schema_version", "catalog_revision", "family", "entries")
_ENTRY_KEYS = ("version", "branch", "edition", "repository", "expected_origin", "classification", "kind",
               "requires_credentials", "verification", "official_kind", "licence_id", "licence_access",
               "redistribution")
_TEXT_ENTRY_KEYS = tuple(key for key in _ENTRY_KEYS if key not in ("requires_credentials", "licence_id"))
_VERSION = re.compile(r"[0-9]+\.0")
_LICENCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}")
_LICENCE_PLACEHOLDERS = frozenset({"UNKNOWN", "NONE", "NULL", "TBD", "TODO", "FIXME", "PLACEHOLDER", "NA", "CHANGEME",
                                   "XXX"})


class CatalogError(Exception):
    """The catalog breaks a rule. `code` is stable; `message` never repeats a URL value."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CatalogEntry:
    version: str
    branch: str
    edition: str
    repository: str
    expected_origin: str
    classification: str
    kind: str
    requires_credentials: bool
    verification: str
    official_kind: str
    licence_id: str
    licence_access: str
    redistribution: str


@dataclass(frozen=True)
class Catalog:
    schema_version: int
    revision: str
    family: str
    entries: tuple
    digest: str

    def editions(self) -> tuple:
        """Editions that have at least one entry, in contract order."""
        present = {e.edition for e in self.entries}
        return tuple(edition for edition in EDITIONS if edition in present)

    def versions(self, edition: str = "community") -> tuple:
        """Versions of one edition in numeric order."""
        return tuple(sorted((e.version for e in self.entries if e.edition == edition), key=_version_key))

    def entry_for(self, version: str, edition: str = "community") -> CatalogEntry:
        if edition not in EDITIONS:
            raise CatalogError("CATALOG_UNKNOWN_EDITION", f"unknown edition {edition!r}")
        for entry in self.entries:
            if entry.edition == edition and entry.version == version:
                return entry
        raise CatalogError("CATALOG_UNKNOWN_VERSION", f"no {edition} catalog entry for version {version!r}")

    def pairs(self, edition: str) -> list:
        """Consecutive (from_version, to_version) transitions within one edition, in numeric order."""
        versions = self.versions(edition)
        return [(versions[i], versions[i + 1]) for i in range(len(versions) - 1)]

    def source_id(self, entry: CatalogEntry) -> str:
        """Registry-valid source id (`^[a-z0-9][a-z0-9._-]{2,63}$`): `odoo-<edition>-<version>`."""
        return f"odoo-{entry.edition}-{entry.version}"


def load_catalog(path=None) -> Catalog:
    """Read, validate and digest a catalog. Defaults to the packaged `catalog.json`."""
    target = Path(path) if path is not None else CATALOG_PATH
    try:
        with open(target, "rb") as handle:
            raw = handle.read(MAX_CATALOG_BYTES + 1)  # bounded read: the size check cannot be raced by growth
    except OSError as exc:
        raise CatalogError("CATALOG_IO", f"cannot read catalog: {exc.strerror or type(exc).__name__}") from exc
    if len(raw) > MAX_CATALOG_BYTES:
        raise CatalogError("CATALOG_TOO_LARGE", f"catalog exceeds {MAX_CATALOG_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CatalogError("CATALOG_ENCODING", "catalog is not valid UTF-8") from exc
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise CatalogError("CATALOG_INVALID_JSON", f"catalog is not valid JSON: {exc.msg}") from exc
    return _build(doc)


def _build(doc) -> Catalog:
    if not isinstance(doc, dict):
        raise CatalogError("CATALOG_SHAPE", "top level must be an object")
    _check_keys(doc, _TOP_KEYS, "document")
    schema = doc["schema_version"]
    if type(schema) is not int or schema != SCHEMA_VERSION:
        raise CatalogError("CATALOG_SCHEMA_VERSION", f"schema_version must be {SCHEMA_VERSION}")
    revision = _text(doc, "catalog_revision", "document")
    family = _text(doc, "family", "document")
    if family != FAMILY:
        raise CatalogError("CATALOG_FAMILY", f"family must be {FAMILY!r}")
    raw_entries = doc["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise CatalogError("CATALOG_FIELD", "entries must be a non-empty list")
    allow_list = sources.load_allow_list()
    seen = set()
    entries = []
    for index, raw in enumerate(raw_entries):
        entry = _entry(raw, f"entries[{index}]", allow_list)
        identity = (entry.edition, entry.version)
        if identity in seen:
            raise CatalogError("CATALOG_DUPLICATE_VERSION",
                               f"{entry.edition} version {entry.version} appears more than once")
        seen.add(identity)
        entries.append(entry)
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Catalog(schema_version=schema, revision=revision, family=family, entries=tuple(entries), digest=digest)


def _entry(raw, where: str, allow_list: list) -> CatalogEntry:
    if not isinstance(raw, dict):
        raise CatalogError("CATALOG_SHAPE", f"{where} must be an object")
    _check_keys(raw, _ENTRY_KEYS, where)
    fields = {key: _text(raw, key, where) for key in _TEXT_ENTRY_KEYS}
    version = fields["version"]
    if not _VERSION.fullmatch(version):
        raise CatalogError("CATALOG_VERSION", f"{where}.version must match <major>.0")
    if fields["branch"] != version:
        raise CatalogError("CATALOG_BRANCH_MISMATCH", f"{where}.branch must equal version")
    edition = fields["edition"]
    if edition not in EDITIONS:
        raise CatalogError("CATALOG_EDITION", f"{where}.edition must be one of {', '.join(EDITIONS)}")
    spec = _EDITION_SPEC[edition]
    if fields["classification"] != edition:
        raise CatalogError("CATALOG_CLASSIFICATION", f"{where}.classification must equal edition {edition!r}")
    if fields["kind"] in _RETIRED_KINDS:
        raise CatalogError("CATALOG_KIND", f"{where}.kind {fields['kind']} is retired; use {spec['kind']!r} for {edition}")
    if fields["kind"] != spec["kind"]:
        raise CatalogError("CATALOG_KIND", f"{where}.kind must be {spec['kind']!r} for {edition}")
    requires = raw["requires_credentials"]
    if type(requires) is not bool:
        raise CatalogError("CATALOG_FIELD", f"{where}.requires_credentials must be a boolean")
    if requires != spec["requires_credentials"]:
        raise CatalogError("CATALOG_CREDENTIALS",
                           f"{where}.requires_credentials must be {spec['requires_credentials']} for {edition}")
    if fields["verification"] != VERIFICATION or fields["official_kind"] != OFFICIAL_KIND:
        raise CatalogError("CATALOG_VALUE", f"{where} needs verification {VERIFICATION!r} and official_kind "
                                            f"{OFFICIAL_KIND!r}")
    if fields["licence_access"] != spec["licence_access"]:
        raise CatalogError("CATALOG_LICENCE_ACCESS",
                           f"{where}.licence_access must be {spec['licence_access']!r} for {edition}")
    if fields["redistribution"] != spec["redistribution"]:
        raise CatalogError("CATALOG_REDISTRIBUTION",
                           f"{where}.redistribution must be {spec['redistribution']!r} for {edition}")
    licence_id = _licence_id(raw, where)
    for key in ("repository", "expected_origin"):
        if sources.has_url_credentials(fields[key]):
            raise CatalogError(sources.CREDENTIALS_CODE, f"{where}.{key} carries credentials; remove them")
    for key in ("repository", "expected_origin"):
        if not fields[key].startswith("https://"):
            raise CatalogError("CATALOG_SCHEME", f"{where}.{key} must be an https URL")
    repository, expected = fields["repository"], fields["expected_origin"]
    if not sources.origin_allowed(repository, allow_list):
        raise CatalogError("CATALOG_ORIGIN", f"{where}.repository is not an allow-listed origin")
    if not sources.origin_allowed(expected, allow_list):
        raise CatalogError("CATALOG_ORIGIN", f"{where}.expected_origin is not an allow-listed origin")
    if repository != spec["repository"]:
        raise CatalogError("CATALOG_REPOSITORY", f"{where}.repository must be the {edition} repository")
    if expected != spec["expected_origin"]:
        raise CatalogError("CATALOG_REPOSITORY", f"{where}.expected_origin must be the {edition} origin")
    if edition == "community" and sources.official_origin(spec["kind"], repository, allow_list) is None:
        raise CatalogError("CATALOG_ORIGIN", f"{where}.repository is not an allow-listed official origin")
    if sources.normalize_origin(repository) != sources.normalize_origin(expected):
        raise CatalogError("CATALOG_ORIGIN", f"{where}.expected_origin must match repository")
    return CatalogEntry(**fields, requires_credentials=requires, licence_id=licence_id)


def _licence_id(raw: dict, where: str) -> str:
    """A declared licence identifier: bounded, no whitespace or control characters, never a placeholder. The value is
    not echoed in the error message."""
    value = raw["licence_id"]
    if not isinstance(value, str) or not _LICENCE_ID.fullmatch(value) or value.upper() in _LICENCE_PLACEHOLDERS:
        raise CatalogError("CATALOG_LICENCE_ID", f"{where}.licence_id must be a declared identifier of 1 to 64 "
                                                 "characters (letters, digits, '.', '+', '_', '-'), not a placeholder")
    return value


def _check_keys(obj: dict, allowed: tuple, where: str) -> None:
    unknown = sorted(set(obj) - set(allowed))
    if unknown:
        raise CatalogError("CATALOG_UNKNOWN_KEY", f"{where} has unknown key(s): {', '.join(unknown)}")
    missing = [key for key in allowed if key not in obj]
    if missing:
        raise CatalogError("CATALOG_MISSING_FIELD", f"{where} is missing: {', '.join(missing)}")


def _text(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CatalogError("CATALOG_FIELD", f"{where}.{key} must be a non-blank string")
    return value


def _no_duplicate_keys(pairs) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise CatalogError("CATALOG_INVALID_JSON", "catalog repeats an object key")
        out[key] = value
    return out


def _reject_constant(name: str):
    raise CatalogError("CATALOG_INVALID_JSON", "catalog contains a non-finite number")


def _version_key(version: str) -> int:
    return int(version.split(".", 1)[0])
