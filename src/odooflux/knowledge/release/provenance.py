"""Release provenance writer and verifier (feature 011 notes 15, 19, 20; contracts/knowledge-package-format.md;
release gate 1 in `release/safety.py`).

`write_provenance(release_dir, snapshots, registry_entries)` is the release-builder boundary. For every verified source
it copies the snapshot manifest (not the blobs) to `<release>/snapshots/<snapshot_id>.json` and writes
`<release>/provenance/sources.json`: a sorted list whose entries carry exactly `ENTRY_FIELDS`, the fields gate 1 reads.
Every entry is validated before anything is written; a refusal writes nothing.

`sources_meta(entries)` gives the list for `meta["sources"]` of `write_release_manifest`, so `release.json` binds the
same source identity (source_id, revision, snapshot_digest, official, status, origin_url, snapshot_id). Both files and
the snapshot files are hashed by the release manifest, so altering any of them changes the release digest.
`verify_provenance(release_dir)` cross-checks the provenance file, `release.json` and the shipped snapshot files and
raises `KnowledgeReleaseError` on any mismatch, missing file or extra entry.

Identity: `origin_url` is a DECLARED identity, not cryptographic authenticity. It is the verified `origin` remote of an
official local clone, checked with local git commands and the allow-list (`sources.official_origin`). Nothing here
proves that the repository is the real upstream; a forged local clone with a matching remote passes. Only an external
trust anchor (signed tags, maintainer-published hashes) would close that gap. The snapshot digest does not cover
`origin_url`, and it is unchanged here.

Local paths never reach provenance: an official local clone records its verified https origin as `url`, and any other
`local:` url is written as `LOCAL_URL_PLACEHOLDER`, so package redaction (absolute paths) is never triggered.

Enterprise entries (kind GIT_ENTERPRISE, feature 012 Wave 3) are the only entries that carry three extra fields:
`confidentiality` ("enterprise"), `licence_id` and `licence_access` ("ENTERPRISE_AUTHORIZED"). They follow the same
identity rules as Community entries, under the enterprise prefix. The kind decides the classification. A record field
never does. Enterprise snapshot manifests (paths and hashes, never content) are shipped in the internal release like any
other, and `release.json` then carries the top-level `confidentiality: internal` key (manifest.py).
"""

import json
from pathlib import Path

from odooflux.knowledge.acquisition.sources import CREDENTIALS_CODE, ENTERPRISE_CONFIDENTIALITY, \
    ENTERPRISE_ENTRY_FIELDS, FORCED_UNOFFICIAL, LICENCE_CODE, OFFICIAL_PREFIX, enterprise_entry_problem, \
    has_url_credentials, licence_problem, load_allow_list, normalize_origin, official_origin
from odooflux.knowledge.release.canonical import canonical_bytes, digest_obj, write_json_file
from odooflux.knowledge.release.manifest import CONFIDENTIALITY_KEY, INTERNAL_CONFIDENTIALITY, MANIFEST_NAME
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.safety import IDENTITY_CODE, PINNED_REVISION, SNAPSHOT_ID
from odooflux.utils.redaction import redact_text

__all__ = [
    "PROVENANCE_RELPATH", "SNAPSHOT_DIRNAME", "ENTRY_FIELDS", "SOURCE_META_FIELDS", "ENTERPRISE_FIELDS",
    "LOCAL_URL_PLACEHOLDER", "write_provenance", "sources_meta", "verify_provenance",
]

SNAPSHOT_DIRNAME = "snapshots"
PROVENANCE_RELPATH = "provenance/sources.json"
ENTRY_FIELDS = ("source_id", "kind", "url", "origin_url", "revision", "snapshot_id", "snapshot_digest", "official",
                "status")
SOURCE_META_FIELDS = ("source_id", "revision", "snapshot_digest", "official", "status", "origin_url", "snapshot_id")
# optional, present only on enterprise entries and on the release.json sources items that bind them
ENTERPRISE_FIELDS = ENTERPRISE_ENTRY_FIELDS
LOCAL_URL_PLACEHOLDER = "local:redacted"
ENTERPRISE_CODE = "ENTERPRISE_DERIVED_REFUSED"
ENTERPRISE_KIND = "GIT_ENTERPRISE"
USABLE_STATUS = "VERIFIED"


def _fail(message: str):
    raise KnowledgeReleaseError(message)


def _entries_digest(snap: dict):
    """Recomputed snapshot digest (snapshot.py: source_id, revision and entries), or None when malformed."""
    entries = snap.get("entries")
    if not isinstance(entries, list):
        return None
    return digest_obj({"source_id": snap.get("source_id"), "revision": snap.get("revision"), "entries": entries})


def _shaped(obj) -> bool:
    """True when the canonical JSON of `obj` holds a credential shape (REQ-KAP-046). Nothing shaped ships."""
    text = canonical_bytes(obj).decode("utf-8")
    return redact_text(text) != text


def _verified_origin(kind, origin, allow) -> bool:
    return isinstance(origin, str) and official_origin(kind, origin, allow) == origin


def _is_local(url) -> bool:
    return isinstance(url, str) and url.startswith("local:")


def _entry_for(rec: dict, snap, allow: list) -> dict:
    """One provenance entry for a registry record and its snapshot. Raises before anything is written."""
    sid = rec.get("source_id")
    kind = rec.get("kind")
    official = rec.get("official") is True
    status = rec.get("status")
    for label, value in (("url", rec.get("url")), ("expected_origin", rec.get("expected_origin")),
                         ("origin_url", snap.get("origin_url") if snap else None)):
        if has_url_credentials(value):  # a configuration error: refused, never normalised into an identity
            _fail(f"{sid}: {label} carries credentials ({CREDENTIALS_CODE}); remove user:password from the URL")
    # note 35: licensed content is never shipped. An enterprise kind is recognised by its kind, never by a record field.
    if kind == "ENTERPRISE_LOCAL":
        _fail(f"{sid}: enterprise-local source is never shipped ({ENTERPRISE_CODE})")
    if rec.get("enterprise_derived") is True and kind != ENTERPRISE_KIND:
        _fail(f"{sid}: enterprise_derived source; its snapshot is not shipped ({ENTERPRISE_CODE})")
    if kind == ENTERPRISE_KIND:
        if not (official and status == USABLE_STATUS):
            _fail(f"{sid}: enterprise source must be official and VERIFIED to ship ({ENTERPRISE_CODE})")
        problem = licence_problem(rec.get("licence_access"), rec.get("licence_id"))
        if problem is not None:  # names the field only; a licence value is never echoed
            _fail(f"{sid}: {problem} ({LICENCE_CODE})")
    if status != USABLE_STATUS:
        _fail(f"{sid}: status {status!r} is not {USABLE_STATUS}; only verified sources ship in a release")
    if snap is None:
        _fail(f"{sid}: no verified snapshot is available for this source")
    if snap.get("source_id") != sid:
        _fail(f"{sid}: snapshot belongs to {snap.get('source_id')!r}")
    revision = rec.get("revision")
    if not isinstance(revision, str) or not PINNED_REVISION.match(revision):
        _fail(f"{sid}: revision is not pinned (40-hex or sha256:<64hex>)")
    if snap.get("revision") != revision:
        _fail(f"{sid}: registry revision differs from the snapshot revision")
    if _shaped(snap):
        _fail(f"{sid}: snapshot contains credential-shaped content; refused and nothing was written")
    recomputed = _entries_digest(snap)
    if recomputed is None or snap.get("snapshot_digest") != recomputed:
        _fail(f"{sid}: snapshot digest does not match its entries")
    if rec.get("checksum") not in (None, recomputed):
        _fail(f"{sid}: registry checksum differs from the recomputed snapshot digest")
    snapshot_id = snap.get("snapshot_id")
    if not isinstance(snapshot_id, str) or snapshot_id != "ss-" + recomputed[:12]:
        _fail(f"{sid}: snapshot_id does not derive from the snapshot digest")

    origin = snap.get("origin_url")
    if origin is not None:
        if not _verified_origin(kind, origin, allow):
            _fail(f"{sid}: origin_url is not a verified official origin ({IDENTITY_CODE})")
        expected = rec.get("expected_origin")
        if expected is not None and normalize_origin(expected) != origin:
            _fail(f"{sid}: origin_url does not match expected_origin ({IDENTITY_CODE})")

    url = rec.get("url")
    if official:
        if kind not in OFFICIAL_PREFIX or kind in FORCED_UNOFFICIAL:
            _fail(f"{sid}: official source needs kind GIT_COMMUNITY, GIT_ENTERPRISE or DOCS")
        if _is_local(url):
            if origin is None:
                _fail(f"{sid}: official local clone has no verified origin_url ({IDENTITY_CODE})")
            out_url = origin
        else:
            if not isinstance(url, str) or official_origin(kind, url, allow) is None:
                _fail(f"{sid}: official url is not allow-listed for its kind")
            out_url = url
    else:
        out_url = LOCAL_URL_PLACEHOLDER if _is_local(url) else url
    entry = {
        "source_id": sid, "kind": kind, "url": out_url, "origin_url": origin, "revision": revision,
        "snapshot_id": snapshot_id, "snapshot_digest": recomputed, "official": official, "status": USABLE_STATUS,
    }
    if kind == ENTERPRISE_KIND:  # licence verified above; the enterprise fields are present on these entries only
        entry.update({"confidentiality": ENTERPRISE_CONFIDENTIALITY, "licence_id": rec["licence_id"],
                      "licence_access": rec["licence_access"]})
    return entry


def write_provenance(release_dir, snapshots: list, registry_entries: list) -> list:
    """Write `snapshots/<id>.json` and `provenance/sources.json` into `release_dir`; return the sorted entries.

    `registry_entries` are SourceSpec records (status VERIFIED); `snapshots` are the SourceSnapshot manifests they
    were verified against, one per source. Refuses (KnowledgeReleaseError) and writes nothing when a source has no
    verified snapshot, the recomputed digest differs, the status is not VERIFIED, or an official source lacks the
    identity gate 1 requires. Unbound snapshots are refused too."""
    root = Path(release_dir)
    allow = load_allow_list()
    by_source = {}
    for snap in snapshots:
        sid = snap.get("source_id")
        if sid in by_source:
            _fail(f"{sid}: more than one snapshot was supplied for this source")
        by_source[sid] = snap
    entries, seen = [], set()
    for rec in registry_entries:
        sid = rec.get("source_id")
        if sid in seen:
            _fail(f"{sid}: source listed twice")
        seen.add(sid)
        entries.append(_entry_for(rec, by_source.get(sid), allow))
    unbound = sorted(str(sid) for sid in set(by_source) - seen)
    if unbound:
        _fail(f"snapshots without a registry source: {unbound}")
    entries.sort(key=lambda entry: entry["source_id"])

    snap_dir = root / SNAPSHOT_DIRNAME
    snap_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        snap = by_source[entry["source_id"]]
        (snap_dir / f"{entry['snapshot_id']}.json").write_bytes(canonical_bytes(snap) + b"\n")
    (root / PROVENANCE_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    write_json_file(root / PROVENANCE_RELPATH, entries)
    return entries


def sources_meta(entries: list) -> list:
    """`release.json` `sources` list for the given provenance entries, sorted by source_id."""
    out = []
    for entry in sorted(entries, key=lambda item: item["source_id"]):
        missing = [key for key in SOURCE_META_FIELDS if key not in entry]
        if missing:
            _fail(f"provenance entry {entry.get('source_id')!r} lacks {missing}")
        item = {key: entry[key] for key in SOURCE_META_FIELDS}
        item.update({key: entry[key] for key in ENTERPRISE_FIELDS if key in entry})  # enterprise entries only
        out.append(item)
    return out


def verify_provenance(release_dir) -> None:
    """Cross-check `provenance/sources.json`, `release.json` `sources` and `snapshots/` in a release tree.

    Raises KnowledgeReleaseError naming every problem: missing or unreadable files, entries present in only one of
    provenance and release.json, identity fields that differ, snapshot files that are missing, altered (not canonical,
    or a digest that does not recompute), or unreferenced. An empty result means the three agree."""
    root = Path(release_dir)
    allow = load_allow_list()
    try:
        entries = json.loads((root / PROVENANCE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _fail(f"{PROVENANCE_RELPATH} is missing or unreadable")
    if not isinstance(entries, list):
        _fail(f"{PROVENANCE_RELPATH} is not a list")
    try:
        release = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _fail(f"{MANIFEST_NAME} is missing or unreadable")
    if not isinstance(release, dict):
        _fail(f"{MANIFEST_NAME} is not a JSON object")
    problems = []

    # an entry has exactly ENTRY_FIELDS (public), or ENTRY_FIELDS plus all of ENTERPRISE_FIELDS (enterprise)
    allowed_shapes = (set(ENTRY_FIELDS), set(ENTRY_FIELDS) | set(ENTERPRISE_FIELDS))
    by_id = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) not in allowed_shapes:
            problems.append("malformed provenance entry (fields are neither ENTRY_FIELDS nor ENTRY_FIELDS plus all "
                            "enterprise fields)")
            continue
        if entry["source_id"] in by_id:
            problems.append(f"{entry['source_id']}: duplicated provenance entry")
        by_id[entry["source_id"]] = entry

    listed = release.get("sources")
    release_by_id = {}
    for item in listed if isinstance(listed, list) else []:
        if isinstance(item, dict):
            release_by_id[item.get("source_id")] = item
    for sid in sorted(set(by_id) - set(release_by_id), key=str):
        problems.append(f"{sid}: in provenance but not in release.json sources")
    for sid in sorted(set(release_by_id) - set(by_id), key=str):
        problems.append(f"{sid}: in release.json sources but not in provenance")
    for sid in sorted(set(by_id) & set(release_by_id), key=str):
        bound = {key: release_by_id[sid].get(key) for key in SOURCE_META_FIELDS}
        differs = bound != {key: by_id[sid][key] for key in SOURCE_META_FIELDS}
        # optional enterprise fields: present on both sides with equal values, or absent on both
        differs = differs or any((key in release_by_id[sid]) != (key in by_id[sid])
                                 or release_by_id[sid].get(key) != by_id[sid].get(key) for key in ENTERPRISE_FIELDS)
        if differs:
            problems.append(f"{sid}: release.json sources differ from provenance")

    # the top-level key marks a release that carries enterprise sources, and only such a release (derived from entries)
    enterprise_sources = sorted(str(sid) for sid, entry in by_id.items()
                                if entry.get("confidentiality") == ENTERPRISE_CONFIDENTIALITY)
    if enterprise_sources and release.get(CONFIDENTIALITY_KEY) != INTERNAL_CONFIDENTIALITY:
        problems.append(f"release.json must carry {CONFIDENTIALITY_KEY} {INTERNAL_CONFIDENTIALITY}: it lists "
                        f"enterprise sources")
    if not enterprise_sources and CONFIDENTIALITY_KEY in release:
        problems.append(f"release.json carries {CONFIDENTIALITY_KEY} without any enterprise source")

    referenced = set()
    for sid, entry in sorted(by_id.items(), key=lambda item: str(item[0])):
        coherence = enterprise_entry_problem(entry)
        if coherence is not None:
            problems.append(f"{sid}: {coherence}")
        origin = entry["origin_url"]
        if has_url_credentials(entry["url"]) or has_url_credentials(origin):
            problems.append(f"{sid}: source url carries credentials ({CREDENTIALS_CODE})")
        if origin is not None and not _verified_origin(entry["kind"], origin, allow):
            problems.append(f"{sid}: origin_url is not a verified official origin ({IDENTITY_CODE})")
        if entry["official"] is True and _is_local(entry["url"]) and origin is None:
            problems.append(f"{sid}: official local clone has no verified origin_url ({IDENTITY_CODE})")
        if not isinstance(entry["snapshot_id"], str) or not SNAPSHOT_ID.match(entry["snapshot_id"]):
            problems.append(f"{sid}: snapshot_id is malformed")
            continue
        name = f"{entry['snapshot_id']}.json"
        referenced.add(name)
        path = root / SNAPSHOT_DIRNAME / name
        try:
            raw = path.read_bytes()
            snap = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError):
            problems.append(f"{sid}: snapshot file {name} is missing or unreadable")
            continue
        if not isinstance(snap, dict) or raw != canonical_bytes(snap) + b"\n":
            problems.append(f"{sid}: snapshot file {name} is not the canonical snapshot manifest")
            continue
        if _shaped(snap):
            problems.append(f"{sid}: snapshot file {name} contains credential-shaped content")
            continue
        recomputed = _entries_digest(snap)
        if snap.get("source_id") != sid or snap.get("revision") != entry["revision"]:
            problems.append(f"{sid}: snapshot source or revision differs from provenance")
        if snap.get("origin_url") != origin:
            problems.append(f"{sid}: snapshot origin_url differs from provenance")
        if recomputed is None or recomputed != entry["snapshot_digest"] or snap.get("snapshot_digest") != recomputed:
            problems.append(f"{sid}: snapshot digest does not match provenance or recompute")
        if snap.get("snapshot_id") != entry["snapshot_id"]:
            problems.append(f"{sid}: snapshot_id differs from provenance")

    shipped = root / SNAPSHOT_DIRNAME
    if shipped.is_dir():
        for path in sorted(shipped.iterdir()):
            if path.name not in referenced:
                problems.append(f"extra snapshot file not referenced by provenance: {path.name}")
    if problems:
        _fail("; ".join(problems))
