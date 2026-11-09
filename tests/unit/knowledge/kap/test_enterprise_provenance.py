"""Enterprise provenance (feature 012 Wave 3; trust contract items 1 to 6).

A GIT_ENTERPRISE source is official-capable under the same identity rules as GIT_COMMUNITY, under the enterprise prefix,
and only with a verifiable licence. ENTERPRISE_LOCAL is never shipped. Enterprise provenance entries carry three optional
fields that are recomputed from the kind. `release.json` carries the top-level `confidentiality: internal` key iff an
enterprise source is listed. Public releases stay byte-identical to the pre-enterprise build. Offline: the verified origin
is set the way git_local.py records it. The one adapter test uses a local git repository only, never the network.
"""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge import validator as v
from odooflux.knowledge.acquisition import sources as s
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.manifest import MANIFEST_NAME, build_manifest, verify_release_tree, \
    write_release_manifest
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.provenance import ENTERPRISE_FIELDS, ENTRY_FIELDS, PROVENANCE_RELPATH, \
    SNAPSHOT_DIRNAME, SOURCE_META_FIELDS, sources_meta, verify_provenance, write_provenance
from odooflux.knowledge.release.safety import fix_gate_findings

GIT = shutil.which("git")
ALLOW = s.load_allow_list()
ENT_ID = "odoo-enterprise-17.0"
COM_ID = "odoo-community-17.0"
ENT_ORIGIN = "https://github.com/odoo/enterprise"
COM_ORIGIN = "https://github.com/odoo/odoo"
ENT_REV = "e" * 40
COM_REV = "a" * 40
DIR_ID = "dir-pack-01"
DIR_REV = "sha256:" + "b" * 64
LICENCE_ID = "ENT-LIC-0001"
CREATED = "2026-11-08T10:00:00Z"
IDENTITY = "OFFICIAL_IDENTITY_UNVERIFIED"
ENTERPRISE_CODE = "ENTERPRISE_DERIVED_REFUSED"
LICENCE_CODE = "LICENCE_UNVERIFIED"
CREDENTIALS = "URL_CREDENTIALS"
DROP = object()  # marks a key to remove in `_rec_with`
SCHEMA_RELEASE = json.loads((KNOWLEDGE_ROOT / "schemas" / "release_manifest.schema.json").read_text("utf-8"))
SCHEMA_REGISTRY = json.loads((KNOWLEDGE_ROOT / "schemas" / "source_registry.schema.json").read_text("utf-8"))
META = {
    "label": "community-17.0-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": CREATED, "host_free": True},
}
# Digests of the public release built by `_public_release` below, recorded BEFORE the enterprise change. Any drift in a
# public release (manifest, provenance or release id) fails `test_public_release_byte_identical`.
PUBLIC_RELEASE_ID = "kr-3e384b779623"
PUBLIC_RELEASE_DIGEST = "3e384b779623697a912e06ce707ecabe5f53385721306dd1538809852330eecb"
PUBLIC_RELEASE_JSON_SHA256 = "ad05d429106c45f2d1e007360690427c3500dc9298b2dd5f1eeeb84052edc46c"
PUBLIC_PROVENANCE_SHA256 = "ffce8f685d7853a9d56619f98fb0371d58a4eebc8076b987bf278f921b1cccf6"
PUBLIC_TOP_KEYS = ["build", "completeness", "coverage_manifest_digest", "files", "format", "framework", "label",
                   "parent_release", "release_digest", "release_id", "schema_versions", "sources", "steps_covered"]

# Gate 1 fixtures (the same synthetic rule and evidence shape as release/test_release_safety.py), bound to ENT_ID.
BASE_EVIDENCE = {
    "id": "EV-900",
    "rule_ids": ["16-17.python.synthetic-fix"],
    "category": "orm",
    "source_applicability": {"from": "16.0", "to": "16.0"},
    "target_applicability": {"from": "17.0", "to": None},
    "description": "Synthetic evidence for the enterprise provenance tests",
    "url": "https://github.com/odoo/odoo/blob/0000/odoo/api.py#L1",
    "repository": "odoo/odoo",
    "revision": "0" * 40,
    "locations": [{"branch": "16.0", "revision": "0" * 40, "path": "odoo/api.py", "line": 1, "match": "x",
                   "kind": "present", "content_sha256": "c" * 64}],
    "detection_method": "grep on pinned source",
    "proposed_transformation": "rename keyword",
    "risk": "LOW",
    "required_validation": ["python_runtime"],
    "status": "DOCUMENTED_NOT_TESTED",
    "checked_on": "2026-11-01",
    "checked_by": "test",
    "official": True,
    "source_id": ENT_ID,
}
BASE_RULE = {
    "id": "16-17.python.synthetic-fix",
    "step": "16-17",
    "category": "python_orm",
    "maturity": "FIX_ENABLED",
    "risk": "LOW",
    "evidence": ["EV-900"],
    "detector_ref": "odooflux.rules.python.generic:flag_decorator",
    "fixer_ref": "odooflux.rules.python.generic:remove_decorator",
    "review_required": False,
    "tests": {"positive": "TST-011-009", "negative": "TST-011-009", "idempotence": "TST-011-009"},
    "conflicts_with": [],
    "origin": "MANUAL",
}


def _tree(root: Path, name: str, text: str) -> Path:
    tree = root / name
    (tree / "addons" / "demo").mkdir(parents=True)
    (tree / "addons" / "demo" / "models.py").write_text(text, encoding="utf-8")
    return tree


def _fresh_release(base: Path) -> Path:
    tree = Path(tempfile.mkdtemp(dir=base))
    (tree / "coverage").mkdir()
    (tree / "coverage" / "coverage-manifest.json").write_text('{"items": []}\n', encoding="utf-8")
    return tree


def _knowledge(release: Path) -> Path:
    """A knowledge tree at <release>/knowledge with one FIX_ENABLED rule backed by EV-900. Create before publishing."""
    root = release / "knowledge"
    (root / "compatibility").mkdir(parents=True)
    (root / "evidence").mkdir(parents=True)
    (root / "compatibility" / "16-17.rules.json").write_text(json.dumps([BASE_RULE]), encoding="utf-8")
    (root / "evidence" / "EV-900.json").write_text(json.dumps(BASE_EVIDENCE), encoding="utf-8")
    return root


def _publish(release: Path, snapshots, records):
    entries = write_provenance(release, snapshots, records)
    write_release_manifest(release, {**META, "sources": sources_meta(entries)})
    return entries


def _rewrite_provenance(release: Path, mutate, *, rebuild: bool = True) -> None:
    """Apply `mutate(entries)` to provenance/sources.json; with `rebuild`, refresh release.json from it as a builder."""
    path = release / PROVENANCE_RELPATH
    entries = json.loads(path.read_text(encoding="utf-8"))
    mutate(entries)
    path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if rebuild:
        write_release_manifest(release, {**META, "sources": sources_meta(entries)})


def _entry(entries, source_id):
    return next(entry for entry in entries if entry["source_id"] == source_id)


def _rec_with(base: dict, **changes) -> dict:
    out = dict(base)
    for key, value in changes.items():
        if value is DROP:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def _spec(**overrides) -> dict:
    spec = {
        "source_id": ENT_ID, "kind": "GIT_ENTERPRISE", "official": True, "url": ENT_ORIGIN + "/",
        "licence_access": "ENTERPRISE_AUTHORIZED", "licence_id": LICENCE_ID, "branch": "17.0", "revision": ENT_REV,
        "scope": {"modules": "*", "include": ["**/*.py"], "exclude": [], "file_kinds": ["python"]},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }
    spec.update(overrides)
    return spec


class EnterpriseSpecTests(unittest.TestCase):
    """Items 1 and the schema admission: the kind, its prefix, and the identity rules of an official spec."""

    def test_kind_is_registered_and_official_capable(self):
        self.assertIn("GIT_ENTERPRISE", s.KINDS)
        self.assertIn("GIT_ENTERPRISE", s.GIT_KINDS)
        self.assertEqual(s.OFFICIAL_PREFIX["GIT_ENTERPRISE"], "https://github.com/odoo/enterprise/")
        self.assertIn("https://github.com/odoo/enterprise/", ALLOW)
        self.assertEqual(s.ENTERPRISE_KINDS, ("GIT_ENTERPRISE", "ENTERPRISE_LOCAL"))

    def test_enterprise_kind_helper(self):
        for kind in ("GIT_ENTERPRISE", "ENTERPRISE_LOCAL"):
            self.assertTrue(s.is_enterprise_kind(kind))
        for kind in ("GIT_COMMUNITY", "DOCS", "OCA", "DIRECTORY", None):
            self.assertFalse(s.is_enterprise_kind(kind))

    def test_official_spec_follows_community_rules(self):
        self.assertEqual(s.validate_spec(_spec(), ALLOW), [])
        self.assertEqual(s.validate_spec(_spec(url="local:/srv/ent", expected_origin=ENT_ORIGIN), ALLOW), [])
        self.assertEqual(s.validate_spec(_spec(official=False), ALLOW), [])
        self.assertTrue(any(p == "/official" for p, _ in s.validate_spec(_spec(url=COM_ORIGIN + "/"), ALLOW)))
        self.assertTrue(any(p == "/expected_origin" for p, _ in s.validate_spec(
            _spec(url="local:/srv/ent", expected_origin=COM_ORIGIN), ALLOW)))
        self.assertTrue(any(p == "/expected_origin" for p, _ in s.validate_spec(
            _spec(url="local:/srv/ent", expected_origin=None), ALLOW)))
        creds = s.validate_spec(_spec(url="https://ci:tok@github.com/odoo/enterprise/"), ALLOW)
        self.assertEqual([p for p, _ in creds], ["/url"])
        self.assertIn(CREDENTIALS, creds[0][1])

    def test_enterprise_local_cannot_be_official(self):
        problems = s.validate_spec(_spec(kind="ENTERPRISE_LOCAL", url="local:/srv/ent", expected_origin=ENT_ORIGIN),
                                   ALLOW)
        self.assertTrue(any(p == "/official" for p, _ in problems), problems)

    def test_empty_allow_list_fails_closed(self):
        self.assertTrue(any(p == "/url" for p, _ in s.validate_spec(_spec(), [])))
        self.assertTrue(any(p == "/expected_origin" for p, _ in s.validate_spec(
            _spec(url="local:/srv/ent", expected_origin=ENT_ORIGIN), [])))

    def test_registry_accepts_and_schema_admits_the_kind(self):
        reg = s.SourceRegistry()
        reg.add(_spec())
        self.assertEqual(reg.get(ENT_ID)["kind"], "GIT_ENTERPRISE")
        self.assertEqual(v.check(_spec(), SCHEMA_REGISTRY), [])
        self.assertTrue(v.check(_spec(kind="GIT_NOPE"), SCHEMA_REGISTRY))

    def test_adapter_accepts_enterprise_git_and_refuses_enterprise_local(self):
        GitLocalAdapter("GIT_ENTERPRISE", allow_list=ALLOW)
        with self.assertRaises(ValueError):
            GitLocalAdapter("ENTERPRISE_LOCAL", allow_list=ALLOW)


class EnterpriseProvenanceBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "store")
        self.ent_snap = build_snapshot(_tree(self.base, "enterprise", "secret_module = 1\n"), ENT_ID, ENT_REV,
                                       self.store, created_at=CREATED)
        self.ent_snap["origin_url"] = ENT_ORIGIN  # recorded the way git_local.py records a verified official clone
        self.ent_rec = {
            "source_id": ENT_ID, "kind": "GIT_ENTERPRISE", "official": True,
            "url": "local:" + str(self.base / "clone-ent"), "expected_origin": ENT_ORIGIN, "revision": ENT_REV,
            "status": "VERIFIED", "checksum": self.ent_snap["snapshot_digest"], "licence_access": "ENTERPRISE_AUTHORIZED",
            "licence_id": LICENCE_ID,
        }
        self.com_snap = build_snapshot(_tree(self.base, "odoo", "x = 1\n"), COM_ID, COM_REV, self.store,
                                       created_at=CREATED)
        self.com_snap["origin_url"] = COM_ORIGIN
        self.com_rec = {
            "source_id": COM_ID, "kind": "GIT_COMMUNITY", "official": True, "url": "local:" + str(self.base / "clone-17"),
            "expected_origin": COM_ORIGIN, "revision": COM_REV, "status": "VERIFIED",
            "checksum": self.com_snap["snapshot_digest"],
        }
        self.dir_snap = build_snapshot(_tree(self.base, "pack", "y = 2\n"), DIR_ID, DIR_REV, self.store,
                                       created_at=CREATED)
        self.dir_rec = {
            "source_id": DIR_ID, "kind": "DIRECTORY", "official": False, "url": "local:" + str(self.base / "pack"),
            "revision": DIR_REV, "status": "VERIFIED", "checksum": self.dir_snap["snapshot_digest"],
        }

    def _refused(self, records, snapshots, *, code=None) -> str:
        release = _fresh_release(self.base)
        with self.assertRaises(KnowledgeReleaseError) as ctx:
            write_provenance(release, snapshots, records)
        if code is not None:
            self.assertIn(code, str(ctx.exception))
        self.assertFalse((release / PROVENANCE_RELPATH).exists())
        self.assertFalse((release / SNAPSHOT_DIRNAME).exists())
        return str(ctx.exception)


class EnterpriseAcceptanceTests(EnterpriseProvenanceBase):
    def test_verified_enterprise_source_accepted_end_to_end(self):
        release = _fresh_release(self.base)
        knowledge = _knowledge(release)
        entries = _publish(release, [self.ent_snap], [self.ent_rec])
        verify_provenance(release)
        self.assertEqual(verify_release_tree(release), [])
        self.assertEqual(fix_gate_findings(knowledge), [])  # gate 1 passes for verified enterprise evidence
        self.assertEqual(entries[0]["url"], ENT_ORIGIN)  # the verified origin, never the local clone path
        self.assertEqual(entries[0]["origin_url"], ENT_ORIGIN)
        self.assertNotIn(str(self.base), (release / PROVENANCE_RELPATH).read_text(encoding="utf-8"))

    def test_enterprise_entry_and_release_binding_carry_the_enterprise_fields(self):
        release = _fresh_release(self.base)
        entries = _publish(release, [self.ent_snap], [self.ent_rec])
        self.assertEqual(set(entries[0]), set(ENTRY_FIELDS) | set(ENTERPRISE_FIELDS))
        self.assertEqual((entries[0]["confidentiality"], entries[0]["licence_id"], entries[0]["licence_access"]),
                         ("enterprise", LICENCE_ID, "ENTERPRISE_AUTHORIZED"))
        release_json = json.loads((release / MANIFEST_NAME).read_text(encoding="utf-8"))
        item = release_json["sources"][0]
        self.assertEqual(set(item), set(SOURCE_META_FIELDS) | set(ENTERPRISE_FIELDS))
        self.assertEqual(item["confidentiality"], "enterprise")
        self.assertEqual(v.check(release_json, SCHEMA_RELEASE), [])
        self.assertTrue((release / SNAPSHOT_DIRNAME / f"{self.ent_snap['snapshot_id']}.json").is_file())

    def test_mixed_release_verifies_and_marks_internal(self):
        release = _fresh_release(self.base)
        _knowledge(release)
        _publish(release, [self.ent_snap, self.com_snap, self.dir_snap], [self.ent_rec, self.com_rec, self.dir_rec])
        verify_provenance(release)
        release_json = json.loads((release / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(release_json["confidentiality"], "internal")
        community = next(item for item in release_json["sources"] if item["source_id"] == COM_ID)
        self.assertEqual(set(community), set(SOURCE_META_FIELDS))  # public items keep the base shape
        self.assertEqual(v.check(release_json, SCHEMA_RELEASE), [])


class EnterpriseRefusalTests(EnterpriseProvenanceBase):
    def test_enterprise_local_still_refused(self):
        local = _rec_with(self.ent_rec, kind="ENTERPRISE_LOCAL", official=False, url="local:/srv/enterprise")
        self._refused([local], [self.ent_snap], code=ENTERPRISE_CODE)
        official = _rec_with(self.ent_rec, kind="ENTERPRISE_LOCAL")
        self._refused([official], [self.ent_snap], code=ENTERPRISE_CODE)

    def test_enterprise_record_unofficial_refused(self):
        self._refused([_rec_with(self.ent_rec, official=False)], [self.ent_snap], code=ENTERPRISE_CODE)

    def test_enterprise_record_not_verified_refused(self):
        self._refused([_rec_with(self.ent_rec, status="RETRIEVED")], [self.ent_snap], code=ENTERPRISE_CODE)

    def test_enterprise_derived_flag_is_not_the_classifier(self):
        # the kind decides: a GIT_ENTERPRISE record flagged enterprise_derived is still classified by its kind
        release = _fresh_release(self.base)
        entries = write_provenance(release, [self.ent_snap], [_rec_with(self.ent_rec, enterprise_derived=True)])
        self.assertEqual(entries[0]["confidentiality"], "enterprise")
        # and a flag on a public kind is still refused, as before
        self._refused([_rec_with(self.com_rec, enterprise_derived=True)], [self.com_snap], code=ENTERPRISE_CODE)

    def test_origin_outside_enterprise_prefix_refused(self):
        snap = {**self.ent_snap, "origin_url": COM_ORIGIN}  # a community origin declared as enterprise
        self._refused([_rec_with(self.ent_rec, expected_origin=COM_ORIGIN)], [snap], code=IDENTITY)
        remote = _rec_with(self.ent_rec, url=COM_ORIGIN + "/")  # a community remote declared as enterprise
        self._refused([remote], [self.ent_snap])

    def test_origin_not_allow_listed_refused(self):
        without_enterprise = [p for p in ALLOW if "enterprise" not in p]
        with mock.patch("odooflux.knowledge.release.provenance.load_allow_list", return_value=without_enterprise):
            self._refused([self.ent_rec], [self.ent_snap], code=IDENTITY)

    def test_credentials_in_url_refused_without_echo(self):
        secret = "s3cr3tpassw0rd"
        for label, change in (("url", {"url": f"https://ci-bot:{secret}@github.com/odoo/enterprise/"}),
                              ("expected_origin", {"expected_origin": f"https://ci-bot:{secret}@github.com/odoo/enterprise"})):
            with self.subTest(field=label):
                message = self._refused([_rec_with(self.ent_rec, **change)], [self.ent_snap], code=CREDENTIALS)
                self.assertNotIn(secret, message)

    def test_licence_unverified_refused_and_field_named(self):
        cases = {
            "licence_id missing": ({"licence_id": DROP}, "licence_id"),
            "licence_id empty": ({"licence_id": ""}, "licence_id"),
            "licence_id blank": ({"licence_id": "   "}, "licence_id"),
            "licence_id UNKNOWN": ({"licence_id": "UNKNOWN"}, "licence_id"),
            "licence_id unknown in lower case": ({"licence_id": "unknown"}, "licence_id"),
            "licence_id not a string": ({"licence_id": 42}, "licence_id"),
            "licence_access PUBLIC_OPEN": ({"licence_access": "PUBLIC_OPEN"}, "licence_access"),
            "licence_access UNKNOWN": ({"licence_access": "UNKNOWN"}, "licence_access"),
            "licence_access missing": ({"licence_access": DROP}, "licence_access"),
        }
        for label, (change, field) in cases.items():
            with self.subTest(case=label):
                message = self._refused([_rec_with(self.ent_rec, **change)], [self.ent_snap], code=LICENCE_CODE)
                self.assertIn(field, message)

    def test_credential_shaped_licence_refused_without_echo(self):
        value = "sk-ant-api03-abcdefghijklmnop"
        message = self._refused([_rec_with(self.ent_rec, licence_id=value)], [self.ent_snap], code=LICENCE_CODE)
        self.assertNotIn(value, message)
        self.assertNotIn("sk-ant", message)

    def test_tampered_snapshot_digest_fails(self):
        release = _fresh_release(self.base)
        _knowledge(release)
        _publish(release, [self.ent_snap], [self.ent_rec])
        _rewrite_provenance(release, lambda es: _entry(es, ENT_ID).update(snapshot_digest="e" * 64))
        with self.assertRaises(KnowledgeReleaseError) as ctx:
            verify_provenance(release)
        self.assertIn("snapshot digest does not match", str(ctx.exception))

    def test_snapshot_file_altered_fails(self):
        release = _fresh_release(self.base)
        _knowledge(release)
        _publish(release, [self.ent_snap], [self.ent_rec])
        path = release / SNAPSHOT_DIRNAME / f"{self.ent_snap['snapshot_id']}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["entries"][0]["size"] += 1
        path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(KnowledgeReleaseError):
            verify_provenance(release)

    def test_tampered_revision_fails(self):
        release = _fresh_release(self.base)
        _knowledge(release)
        _publish(release, [self.ent_snap], [self.ent_rec])
        _rewrite_provenance(release, lambda es: _entry(es, ENT_ID).update(revision="c" * 40))
        with self.assertRaises(KnowledgeReleaseError) as ctx:
            verify_provenance(release)
        self.assertIn("revision differs", str(ctx.exception))

    def test_revision_changed_only_in_release_json_fails(self):
        release = _fresh_release(self.base)
        _publish(release, [self.ent_snap], [self.ent_rec])
        path = release / MANIFEST_NAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["sources"][0]["revision"] = "c" * 40
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(KnowledgeReleaseError) as ctx:
            verify_provenance(release)
        self.assertIn("differ from provenance", str(ctx.exception))

    def test_forged_confidentiality_refused_by_verify(self):
        cases = {
            "enterprise kind marked public": (
                lambda es: _entry(es, ENT_ID).update(confidentiality="public"),
                "GIT_ENTERPRISE entry must carry confidentiality enterprise"),
            "enterprise kind with confidentiality dropped": (
                lambda es: _entry(es, ENT_ID).pop("confidentiality"), "malformed provenance entry"),
            "community kind marked enterprise": (
                lambda es: _entry(es, COM_ID).update(confidentiality="enterprise", licence_id=LICENCE_ID,
                                                     licence_access="ENTERPRISE_AUTHORIZED"),
                "GIT_COMMUNITY entry must not carry enterprise fields"),
            "community kind marked public": (
                lambda es: _entry(es, COM_ID).update(confidentiality="public"), "malformed provenance entry"),
        }
        for label, (mutate, expected) in cases.items():
            with self.subTest(case=label):
                release = _fresh_release(self.base)
                _knowledge(release)
                _publish(release, [self.ent_snap, self.com_snap], [self.ent_rec, self.com_rec])
                _rewrite_provenance(release, mutate)
                with self.assertRaises(KnowledgeReleaseError) as ctx:
                    verify_provenance(release)
                self.assertIn(expected, str(ctx.exception))

    def test_top_level_key_iff_enterprise_source(self):
        public = _fresh_release(self.base)
        _publish(public, [self.com_snap, self.dir_snap], [self.com_rec, self.dir_rec])
        self.assertNotIn("confidentiality", json.loads((public / MANIFEST_NAME).read_text(encoding="utf-8")))
        verify_provenance(public)

        forged = _fresh_release(self.base)  # the key on a public release is refused
        _publish(forged, [self.com_snap, self.dir_snap], [self.com_rec, self.dir_rec])
        self._set_top_level(forged, "internal")
        with self.assertRaises(KnowledgeReleaseError) as ctx:
            verify_provenance(forged)
        self.assertIn("without any enterprise source", str(ctx.exception))

        enterprise = _fresh_release(self.base)  # the key is required on an enterprise release
        _publish(enterprise, [self.ent_snap], [self.ent_rec])
        self._set_top_level(enterprise, DROP)
        with self.assertRaises(KnowledgeReleaseError) as ctx:
            verify_provenance(enterprise)
        self.assertIn("must carry confidentiality internal", str(ctx.exception))

    def test_top_level_key_is_covered_by_the_release_digest(self):
        release = _fresh_release(self.base)
        _publish(release, [self.ent_snap], [self.ent_rec])
        self._set_top_level(release, "public", rebuild=False)
        self.assertTrue(verify_release_tree(release))

    def test_caller_cannot_supply_the_top_level_key(self):
        release = _fresh_release(self.base)
        entries = write_provenance(release, [self.com_snap], [self.com_rec])
        with self.assertRaises(KnowledgeReleaseError):
            build_manifest(release, {**META, "sources": sources_meta(entries), "confidentiality": "internal"})

    def _set_top_level(self, release: Path, value, *, rebuild: bool = False) -> None:
        path = release / MANIFEST_NAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if value is DROP:
            manifest.pop("confidentiality", None)
        else:
            manifest["confidentiality"] = value
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class EnterpriseGate1Tests(EnterpriseProvenanceBase):
    def _verified_release(self):
        release = _fresh_release(self.base)
        knowledge = _knowledge(release)
        _publish(release, [self.ent_snap], [self.ent_rec])
        return release, knowledge

    def test_gate1_fails_when_provenance_entry_is_unofficial(self):
        release, knowledge = self._verified_release()
        _rewrite_provenance(release, lambda es: _entry(es, ENT_ID).update(official=False), rebuild=False)
        findings = fix_gate_findings(knowledge)
        codes = [f["code"] for f in findings if f["gate"] == 1]
        self.assertIn("official-claim-unsupported", codes)
        self.assertIn("not official", " ".join(f["detail"] for f in findings))

    def test_gate1_fails_on_wrong_snapshot_binding(self):
        release, knowledge = self._verified_release()
        path = release / SNAPSHOT_DIRNAME / f"{self.ent_snap['snapshot_id']}.json"
        original = path.read_text(encoding="utf-8")

        data = json.loads(original)  # 1. the snapshot digest no longer recomputes
        data["entries"][0]["size"] += 1
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        self.assertTrue(self._gate1_codes(knowledge))

        data = json.loads(original)  # 2. the snapshot origin is not the provenance origin
        data["origin_url"] = COM_ORIGIN
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        self.assertIn(IDENTITY, " ".join(f["detail"] for f in fix_gate_findings(knowledge)))

        path.unlink()  # 3. the snapshot is missing
        self.assertIn("unavailable", " ".join(f["detail"] for f in fix_gate_findings(knowledge)))

    def _gate1_codes(self, knowledge):
        return [f["code"] for f in fix_gate_findings(knowledge) if f["gate"] == 1]

    def test_gate1_refuses_forged_entries_without_verify_provenance(self):
        # the package importer runs gate 1 without verify_provenance, so gate 1 must refuse these forgeries itself
        release, knowledge = self._verified_release()
        path = release / PROVENANCE_RELPATH
        base = json.loads(path.read_text(encoding="utf-8"))
        forged = {
            "enterprise without confidentiality or licence": _without_enterprise_fields(base),
            "enterprise-local marked official": _as_enterprise_local(base),
            "community marked enterprise": _as_community_marked_enterprise(base),
        }
        for label, entries in forged.items():
            with self.subTest(case=label):
                path.write_text(json.dumps(entries, sort_keys=True), encoding="utf-8")
                self.assertTrue(self._gate1_codes(knowledge), label)
        path.write_text(json.dumps(base, sort_keys=True), encoding="utf-8")
        self.assertEqual(fix_gate_findings(knowledge), [])


def _without_enterprise_fields(entries):
    """The enterprise entry with its three enterprise fields removed (a GIT_ENTERPRISE entry that carries none)."""
    out = [dict(e) for e in entries]
    for entry in out:
        for key in ENTERPRISE_FIELDS:
            entry.pop(key, None)
    return out


def _as_enterprise_local(entries):
    """The enterprise entry relabelled ENTERPRISE_LOCAL and still marked official."""
    out = [dict(e) for e in entries]
    out[0] = {**out[0], "kind": "ENTERPRISE_LOCAL"}
    return out


def _as_community_marked_enterprise(entries):
    """The enterprise entry relabelled GIT_COMMUNITY but carrying enterprise fields."""
    out = [dict(e) for e in entries]
    out[0] = {**out[0], "kind": "GIT_COMMUNITY", "confidentiality": "enterprise", "licence_id": LICENCE_ID,
              "licence_access": "ENTERPRISE_AUTHORIZED"}
    return out


class PublicReleaseTests(EnterpriseProvenanceBase):
    def _public_release(self) -> Path:
        release = _fresh_release(self.base)
        _publish(release, [self.com_snap, self.dir_snap], [self.com_rec, self.dir_rec])
        return release

    def test_public_release_byte_identical_to_pre_enterprise_build(self):
        release = self._public_release()
        manifest = json.loads((release / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(manifest["release_id"], PUBLIC_RELEASE_ID)
        self.assertEqual(manifest["release_digest"], PUBLIC_RELEASE_DIGEST)
        self.assertEqual(hashlib.sha256((release / MANIFEST_NAME).read_bytes()).hexdigest(),
                         PUBLIC_RELEASE_JSON_SHA256)
        self.assertEqual(hashlib.sha256((release / PROVENANCE_RELPATH).read_bytes()).hexdigest(),
                         PUBLIC_PROVENANCE_SHA256)

    def test_public_release_has_no_enterprise_keys(self):
        release = self._public_release()
        manifest = json.loads((release / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(sorted(manifest), PUBLIC_TOP_KEYS)
        for item in manifest["sources"]:
            self.assertEqual(set(item), set(SOURCE_META_FIELDS))
        for entry in json.loads((release / PROVENANCE_RELPATH).read_text(encoding="utf-8")):
            self.assertEqual(set(entry), set(ENTRY_FIELDS))

    def test_public_release_with_forged_enterprise_field_on_item_is_refused(self):
        release = self._public_release()
        path = release / MANIFEST_NAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["sources"][0]["licence_id"] = LICENCE_ID
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(KnowledgeReleaseError):
            verify_provenance(release)


@unittest.skipUnless(GIT, "git is not installed; the adapter identity check needs git")
class GitEnterpriseAdapterTests(unittest.TestCase):
    """Local clone with a simulated enterprise origin. Git runs on local paths only; nothing is fetched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo, self.sha = _make_clone(self.base)
        _git(self.repo, "remote", "add", "origin", ENT_ORIGIN + ".git")
        self.store = BlobStore(self.base / "store")
        self.adapter = GitLocalAdapter("GIT_ENTERPRISE", allow_list=ALLOW)

    def _spec(self, **overrides):
        return _spec(url="local:" + str(self.repo), expected_origin=ENT_ORIGIN, revision=self.sha, **overrides)

    def test_same_identity_rules_as_community(self):
        spec = self._spec()
        self.assertEqual(s.validate_spec(spec, ALLOW), [])
        self.assertEqual(self.adapter.probe(spec)["available"], True)
        self.assertEqual(self.adapter.snapshot(spec, self.store, created_at=CREATED)["origin_url"], ENT_ORIGIN)

    def test_wrong_origin_is_identity_failure_and_stores_nothing(self):
        _git(self.repo, "remote", "set-url", "origin", COM_ORIGIN + ".git")
        spec = self._spec()
        self.assertEqual(self.adapter.probe(spec)["reason_code"], IDENTITY)
        with self.assertRaises(SourceError) as ctx:
            self.adapter.snapshot(spec, self.store)
        self.assertEqual(ctx.exception.code, IDENTITY)

    def test_enterprise_remote_is_never_fetched(self):
        remote = _spec(url=ENT_ORIGIN + "/", expected_origin=None)
        self.assertEqual(self.adapter.probe(remote)["reason_code"], "NETWORK_DISABLED")

    def test_clone_to_gate1_end_to_end(self):
        spec = self._spec()
        reg = s.SourceRegistry()
        reg.add(spec)
        snap = self.adapter.snapshot(spec, self.store, created_at=CREATED)
        reg.transition(ENT_ID, "RETRIEVED", retrieved_at=CREATED)
        reg.transition(ENT_ID, "VERIFIED", checksum=snap["snapshot_digest"], origin_url=snap["origin_url"])
        release = _fresh_release(self.base)
        knowledge = _knowledge(release)
        entries = _publish(release, [snap], [reg.get(ENT_ID)])
        verify_provenance(release)
        self.assertEqual(verify_release_tree(release), [])
        self.assertEqual(entries[0]["url"], ENT_ORIGIN)
        self.assertEqual(fix_gate_findings(knowledge), [])


def _make_clone(root: Path, name="clone", content="secret_module = 1\n"):
    """A one-commit git repository. Returns (path, commit sha)."""
    repo = root / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "addons").mkdir()
    (repo / "addons" / "sale_demo.py").write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=kap", "-c", "user.email=kap@example.invalid", "commit", "-q", "-m", "init")
    return repo, _git(repo, "rev-parse", "HEAD").strip()


def _git(cwd, *args) -> str:
    proc = subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(cwd), *args], capture_output=True,
                          text=True, check=True, timeout=120)
    return proc.stdout


if __name__ == "__main__":
    unittest.main()
