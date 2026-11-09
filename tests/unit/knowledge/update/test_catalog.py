"""Feature 012 catalog v2 (plan addendum A1): the packaged catalog loads, covers 12.0-19.0 for both editions, carries no
commit SHA, pairs transitions within one edition, and is refused fail-closed on every rule in the contract. Stdlib
unittest; the repository tree is only read.
"""

import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import odooflux.knowledge as knowledge_pkg
from odooflux.knowledge.update import catalog as cat

SHIPPED_TEXT = cat.CATALOG_PATH.read_text(encoding="utf-8")
SHIPPED_DOC = json.loads(SHIPPED_TEXT)
EXPECTED_VERSIONS = tuple(f"{n}.0" for n in range(12, 20))
COMMUNITY_REPO = "https://github.com/odoo/odoo.git"
ENTERPRISE_REPO = "https://github.com/odoo/enterprise.git"


class ShippedCatalogTests(unittest.TestCase):
    def test_shipped_catalog_loads(self):
        catalog = cat.load_catalog()
        self.assertEqual(catalog.schema_version, 3)
        self.assertEqual(catalog.revision, "2026-11-09.2")
        self.assertEqual(catalog.family, "odoo")
        self.assertEqual(len(catalog.entries), 2 * len(EXPECTED_VERSIONS))
        self.assertEqual(catalog.editions(), ("community", "enterprise"))

    def test_both_editions_cover_exactly_12_to_19(self):
        catalog = cat.load_catalog()
        for edition in ("community", "enterprise"):
            self.assertEqual(catalog.versions(edition), EXPECTED_VERSIONS)
            for version in EXPECTED_VERSIONS:
                self.assertEqual(catalog.entry_for(version, edition).version, version)
            with self.assertRaises(cat.CatalogError) as ctx:
                catalog.entry_for("20.0", edition)
            self.assertEqual(ctx.exception.code, "CATALOG_UNKNOWN_VERSION")

    def test_default_edition_is_community(self):
        catalog = cat.load_catalog()
        self.assertEqual(catalog.versions(), catalog.versions("community"))
        self.assertEqual(catalog.entry_for("16.0"), catalog.entry_for("16.0", "community"))
        self.assertEqual(catalog.entry_for("16.0").edition, "community")

    def test_unknown_edition_lookup_refused(self):
        with self.assertRaises(cat.CatalogError) as ctx:
            cat.load_catalog().entry_for("16.0", "security")
        self.assertEqual(ctx.exception.code, "CATALOG_UNKNOWN_EDITION")

    def test_community_entries_match_contract(self):
        for entry in cat.load_catalog().entries:
            if entry.edition != "community":
                continue
            self.assertEqual(entry.branch, entry.version)
            self.assertEqual(entry.repository, COMMUNITY_REPO)
            self.assertEqual(entry.expected_origin, "https://github.com/odoo/odoo")
            self.assertEqual(entry.classification, "community")
            self.assertEqual(entry.kind, "GIT_COMMUNITY")
            self.assertFalse(entry.requires_credentials)
            self.assertEqual(entry.verification, "immutable-sha")
            self.assertEqual(entry.official_kind, "source")
            self.assertEqual(entry.licence_id, "LGPL-3.0-only")
            self.assertEqual(entry.licence_access, "PUBLIC_OPEN")
            self.assertEqual(entry.redistribution, "PUBLIC")

    def test_enterprise_entries_match_contract(self):
        enterprise = [e for e in cat.load_catalog().entries if e.edition == "enterprise"]
        self.assertEqual(len(enterprise), len(EXPECTED_VERSIONS))
        for entry in enterprise:
            self.assertEqual(entry.branch, entry.version)
            self.assertEqual(entry.repository, ENTERPRISE_REPO)
            self.assertEqual(entry.expected_origin, "https://github.com/odoo/enterprise")
            self.assertEqual(entry.classification, "enterprise")
            self.assertEqual(entry.kind, "GIT_ENTERPRISE")
            self.assertTrue(entry.requires_credentials)
            self.assertEqual(entry.verification, "immutable-sha")
            self.assertEqual(entry.official_kind, "source")
            self.assertEqual(entry.licence_id, "OEEL-1")
            self.assertEqual(entry.licence_access, "ENTERPRISE_AUTHORIZED")
            self.assertEqual(entry.redistribution, "RESTRICTED")

    def test_module_docstring_states_the_licence_caveats(self):
        doc = cat.__doc__
        self.assertIn("declared by OdooFlux maintainers", doc)
        self.assertIn("does NOT verify", doc)
        self.assertIn("ACCESS authorization only", doc)
        self.assertIn("NOT a statement about redistribution rights", doc)

    def test_shipped_file_contains_no_commit_sha(self):
        self.assertIsNone(re.search(r"[0-9a-fA-F]{40}", SHIPPED_TEXT))

    def test_versions_sort_numerically(self):
        template = _entry_for(SHIPPED_DOC, "19.0")
        doc = copy.deepcopy(SHIPPED_DOC)
        doc["entries"] = [{**template, "version": v, "branch": v} for v in ("19.0", "9.0", "10.0")]
        catalog = cat.load_catalog(_write(self, json.dumps(doc)))
        self.assertEqual(catalog.versions(), ("9.0", "10.0", "19.0"))

    def test_package_data_path_is_under_knowledge(self):
        # pyproject ships `knowledge/**/*.json` under the odooflux package; the catalog must live inside that tree.
        knowledge_root = Path(knowledge_pkg.__file__).resolve().parent
        self.assertTrue(cat.CATALOG_PATH.resolve().is_relative_to(knowledge_root))
        self.assertEqual(cat.CATALOG_PATH.name, "catalog.json")


class PairsAndIdentityTests(unittest.TestCase):
    def test_pairs_are_consecutive_within_each_edition(self):
        catalog = cat.load_catalog()
        expected = [(f"{n}.0", f"{n + 1}.0") for n in range(12, 19)]
        self.assertEqual(catalog.pairs("community"), expected)
        self.assertEqual(catalog.pairs("enterprise"), expected)

    def test_pairs_use_numeric_order(self):
        template = _entry_for(SHIPPED_DOC, "19.0")
        doc = copy.deepcopy(SHIPPED_DOC)
        doc["entries"] = [{**template, "version": v, "branch": v} for v in ("19.0", "9.0", "10.0")]
        catalog = cat.load_catalog(_write(self, json.dumps(doc)))
        self.assertEqual(catalog.pairs("community"), [("9.0", "10.0"), ("10.0", "19.0")])

    def test_pairs_never_cross_editions(self):
        catalog = cat.load_catalog()
        self.assertEqual(catalog.pairs("enterprise"), catalog.pairs("community"))
        self.assertEqual(len(catalog.pairs("community")), len(EXPECTED_VERSIONS) - 1)

    def test_source_id_is_edition_qualified(self):
        catalog = cat.load_catalog()
        self.assertEqual(catalog.source_id(catalog.entry_for("16.0", "enterprise")), "odoo-enterprise-16.0")
        self.assertEqual(catalog.source_id(catalog.entry_for("16.0")), "odoo-community-16.0")


class DigestTests(unittest.TestCase):
    def test_digest_stable_across_loads(self):
        self.assertEqual(cat.load_catalog().digest, cat.load_catalog().digest)

    def test_digest_is_sha256_of_canonical_parsed_document(self):
        canonical = json.dumps(SHIPPED_DOC, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(cat.load_catalog().digest, hashlib.sha256(canonical.encode("utf-8")).hexdigest())

    def test_digest_changes_when_an_entry_changes(self):
        before = cat.load_catalog().digest
        doc = copy.deepcopy(SHIPPED_DOC)
        # still valid, one document field changed: the revision label of the catalog
        doc["catalog_revision"] = "2026-11-09.3"
        after = cat.load_catalog(_write(self, json.dumps(doc))).digest
        self.assertNotEqual(before, after)

    def test_digest_changes_when_an_enterprise_entry_is_removed(self):
        before = cat.load_catalog().digest
        doc = copy.deepcopy(SHIPPED_DOC)
        doc["entries"] = [e for e in doc["entries"] if (e["edition"], e["version"]) != ("enterprise", "19.0")]
        catalog = cat.load_catalog(_write(self, json.dumps(doc)))
        self.assertNotEqual(before, catalog.digest)
        self.assertEqual(catalog.versions("enterprise")[-1], "18.0")

    def test_digest_not_stored_in_file(self):
        self.assertNotIn("digest", SHIPPED_DOC)


class RejectionTests(unittest.TestCase):
    def setUp(self):
        self.doc = copy.deepcopy(SHIPPED_DOC)

    def assertRejected(self, code: str, doc=None, text=None):
        path = _write(self, text if text is not None else json.dumps(doc if doc is not None else self.doc))
        with self.assertRaises(cat.CatalogError) as ctx:
            cat.load_catalog(path)
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception

    def test_credential_bearing_url_refused(self):
        _entry_for(self.doc, "16.0")["repository"] = "https://user:s3cr3t-token@github.com/odoo/odoo.git"
        exc = self.assertRejected("URL_CREDENTIALS")
        self.assertNotIn("s3cr3t-token", str(exc))

    def test_credential_bearing_enterprise_url_refused(self):
        _entry_for(self.doc, "16.0", "enterprise")["repository"] = (
            "https://user:s3cr3t-token@github.com/odoo/enterprise.git")
        exc = self.assertRejected("URL_CREDENTIALS")
        self.assertNotIn("s3cr3t-token", str(exc))

    def test_non_allow_listed_origin_refused(self):
        entry = _entry_for(self.doc, "16.0")
        entry["repository"] = entry["expected_origin"] = "https://github.com/evil/odoo"
        self.assertRejected("CATALOG_ORIGIN")

    def test_cross_edition_swap_community_to_enterprise_repo_refused(self):
        entry = _entry_for(self.doc, "16.0", "community")
        entry["repository"] = ENTERPRISE_REPO
        entry["expected_origin"] = "https://github.com/odoo/enterprise"
        self.assertRejected("CATALOG_REPOSITORY")

    def test_cross_edition_swap_enterprise_to_community_repo_refused(self):
        entry = _entry_for(self.doc, "16.0", "enterprise")
        entry["repository"] = COMMUNITY_REPO
        entry["expected_origin"] = "https://github.com/odoo/odoo"
        self.assertRejected("CATALOG_REPOSITORY")

    def test_enterprise_requires_credentials_false_refused(self):
        _entry_for(self.doc, "16.0", "enterprise")["requires_credentials"] = False
        self.assertRejected("CATALOG_CREDENTIALS")

    def test_community_requires_credentials_true_refused(self):
        _entry_for(self.doc, "16.0", "community")["requires_credentials"] = True
        self.assertRejected("CATALOG_CREDENTIALS")

    def test_non_boolean_requires_credentials_refused(self):
        _entry_for(self.doc, "16.0", "enterprise")["requires_credentials"] = "true"
        self.assertRejected("CATALOG_FIELD")

    def test_unknown_edition_refused(self):
        _entry_for(self.doc, "16.0")["edition"] = "security"
        self.assertRejected("CATALOG_EDITION")

    def test_missing_edition_refused(self):
        del _entry_for(self.doc, "16.0")["edition"]
        self.assertRejected("CATALOG_MISSING_FIELD")

    def test_enterprise_classification_on_community_entry_refused(self):
        _entry_for(self.doc, "16.0", "community")["classification"] = "enterprise"
        self.assertRejected("CATALOG_CLASSIFICATION")

    def test_community_classification_on_enterprise_entry_refused(self):
        _entry_for(self.doc, "16.0", "enterprise")["classification"] = "community"
        self.assertRejected("CATALOG_CLASSIFICATION")

    def test_enterprise_kind_on_community_entry_refused(self):
        _entry_for(self.doc, "16.0", "community")["kind"] = "ENTERPRISE_LOCAL"
        self.assertRejected("CATALOG_KIND")

    def test_community_kind_on_enterprise_entry_refused(self):
        _entry_for(self.doc, "16.0", "enterprise")["kind"] = "GIT_COMMUNITY"
        self.assertRejected("CATALOG_KIND")

    def test_duplicate_version_within_edition_refused(self):
        self.doc["entries"].append(copy.deepcopy(_entry_for(self.doc, "16.0", "community")))
        self.assertRejected("CATALOG_DUPLICATE_VERSION")

    def test_duplicate_edition_version_refused_in_enterprise(self):
        self.doc["entries"].append(copy.deepcopy(_entry_for(self.doc, "16.0", "enterprise")))
        self.assertRejected("CATALOG_DUPLICATE_VERSION")

    def test_same_version_in_both_editions_accepted(self):
        self.assertEqual(len(cat.load_catalog(_write(self, json.dumps(self.doc))).entries),
                         2 * len(EXPECTED_VERSIONS))

    def test_unknown_top_level_key_refused(self):
        self.doc["digest"] = "0" * 64
        self.assertRejected("CATALOG_UNKNOWN_KEY")

    def test_unknown_entry_key_refused(self):
        _entry_for(self.doc, "16.0")["commit"] = "main"
        self.assertRejected("CATALOG_UNKNOWN_KEY")

    def test_branch_mismatch_refused(self):
        _entry_for(self.doc, "16.0")["branch"] = "17.0"
        self.assertRejected("CATALOG_BRANCH_MISMATCH")

    def test_http_scheme_refused(self):
        _entry_for(self.doc, "16.0")["repository"] = "http://github.com/odoo/odoo.git"
        self.assertRejected("CATALOG_SCHEME")

    def test_oversize_file_refused(self):
        text = SHIPPED_TEXT + " " * (cat.MAX_CATALOG_BYTES + 1 - len(SHIPPED_TEXT.encode("utf-8")))
        self.assertRejected("CATALOG_TOO_LARGE", text=text)

    def test_file_at_size_limit_accepted(self):
        text = SHIPPED_TEXT + " " * (cat.MAX_CATALOG_BYTES - len(SHIPPED_TEXT.encode("utf-8")))
        self.assertEqual(len(cat.load_catalog(_write(self, text)).entries), 2 * len(EXPECTED_VERSIONS))

    def test_invalid_json_refused(self):
        self.assertRejected("CATALOG_INVALID_JSON", text="{not json")

    def test_duplicate_object_key_refused(self):
        self.assertRejected("CATALOG_INVALID_JSON", text='{"schema_version":2,"schema_version":2}')

    def test_non_utf8_refused(self):
        path = _write_bytes(self, b'{"schema_version": 2, "x": "\xff\xfe"}')
        with self.assertRaises(cat.CatalogError) as ctx:
            cat.load_catalog(path)
        self.assertEqual(ctx.exception.code, "CATALOG_ENCODING")

    def test_wrong_schema_version_refused(self):
        self.doc["schema_version"] = 1
        self.assertRejected("CATALOG_SCHEMA_VERSION")

    def test_boolean_schema_version_refused(self):
        self.doc["schema_version"] = True
        self.assertRejected("CATALOG_SCHEMA_VERSION")

    def test_wrong_family_refused(self):
        self.doc["family"] = "odoo-community"
        self.assertRejected("CATALOG_FAMILY")

    def test_blank_field_refused(self):
        self.doc["catalog_revision"] = "   "
        self.assertRejected("CATALOG_FIELD")

    def test_missing_entry_field_refused(self):
        del _entry_for(self.doc, "16.0")["kind"]
        self.assertRejected("CATALOG_MISSING_FIELD")

    def test_bad_version_pattern_refused(self):
        entry = _entry_for(self.doc, "16.0")
        entry["version"] = entry["branch"] = "16.1"
        self.assertRejected("CATALOG_VERSION")

    def test_non_source_official_kind_refused(self):
        _entry_for(self.doc, "16.0")["official_kind"] = "documentation"
        self.assertRejected("CATALOG_VALUE")

    def test_non_immutable_verification_refused(self):
        _entry_for(self.doc, "16.0", "enterprise")["verification"] = "branch-head"
        self.assertRejected("CATALOG_VALUE")

    def test_non_community_kind_refused(self):
        _entry_for(self.doc, "16.0")["kind"] = "OCA"
        self.assertRejected("CATALOG_KIND")

    def test_missing_licence_id_refused(self):
        del _entry_for(self.doc, "16.0")["licence_id"]
        self.assertRejected("CATALOG_MISSING_FIELD")

    def test_missing_licence_id_refused_for_enterprise(self):
        del _entry_for(self.doc, "16.0", "enterprise")["licence_id"]
        self.assertRejected("CATALOG_MISSING_FIELD")

    def test_placeholder_licence_id_refused(self):
        for placeholder in ("UNKNOWN", "unknown", "Unknown", "TBD", "TODO", "PLACEHOLDER", "none", "NULL", "NA", "XXX"):
            with self.subTest(placeholder=placeholder):
                _entry_for(self.doc, "16.0")["licence_id"] = placeholder
                self.assertRejected("CATALOG_LICENCE_ID")
                _entry_for(self.doc, "16.0", "enterprise")["licence_id"] = placeholder
                self.assertRejected("CATALOG_LICENCE_ID")

    def test_malformed_licence_id_refused(self):
        for bad in ("", "   ", "LGPL 3.0", "LGPL\n", "LGPL\x00", "L" * 65, "-LGPL", "LGPL/3.0", "LGPLé", 7, None):
            with self.subTest(bad=repr(bad)):
                _entry_for(self.doc, "16.0")["licence_id"] = bad
                exc = self.assertRejected("CATALOG_LICENCE_ID")
                self.assertNotIn("LGPL", str(exc))

    def test_licence_id_at_length_limit_accepted(self):
        _entry_for(self.doc, "16.0")["licence_id"] = "L" * 64
        self.assertEqual(len(cat.load_catalog(_write(self, json.dumps(self.doc))).entries),
                         2 * len(EXPECTED_VERSIONS))

    def test_wrong_licence_access_refused(self):
        _entry_for(self.doc, "16.0", "community")["licence_access"] = "ENTERPRISE_AUTHORIZED"
        self.assertRejected("CATALOG_LICENCE_ACCESS")
        self.doc = copy.deepcopy(SHIPPED_DOC)
        _entry_for(self.doc, "16.0", "enterprise")["licence_access"] = "PUBLIC_OPEN"
        self.assertRejected("CATALOG_LICENCE_ACCESS")
        self.doc = copy.deepcopy(SHIPPED_DOC)
        _entry_for(self.doc, "16.0", "enterprise")["licence_access"] = "UNKNOWN"
        self.assertRejected("CATALOG_LICENCE_ACCESS")

    def test_wrong_redistribution_refused(self):
        _entry_for(self.doc, "16.0", "community")["redistribution"] = "RESTRICTED"
        self.assertRejected("CATALOG_REDISTRIBUTION")
        self.doc = copy.deepcopy(SHIPPED_DOC)
        _entry_for(self.doc, "16.0", "enterprise")["redistribution"] = "PUBLIC"
        self.assertRejected("CATALOG_REDISTRIBUTION")

    def test_missing_licence_access_or_redistribution_refused(self):
        del _entry_for(self.doc, "16.0")["licence_access"]
        self.assertRejected("CATALOG_MISSING_FIELD")
        self.doc = copy.deepcopy(SHIPPED_DOC)
        del _entry_for(self.doc, "16.0", "enterprise")["redistribution"]
        self.assertRejected("CATALOG_MISSING_FIELD")

    def test_enterprise_local_kind_refused_on_enterprise_entry(self):
        _entry_for(self.doc, "16.0", "enterprise")["kind"] = "ENTERPRISE_LOCAL"
        exc = self.assertRejected("CATALOG_KIND")
        self.assertIn("retired", str(exc))

    def test_enterprise_entry_must_use_git_enterprise_kind(self):
        _entry_for(self.doc, "16.0", "enterprise")["kind"] = "GIT_COMMUNITY"
        self.assertRejected("CATALOG_KIND")

    def test_empty_entries_refused(self):
        self.doc["entries"] = []
        self.assertRejected("CATALOG_FIELD")


def _entry_for(doc: dict, version: str, edition: str = "community") -> dict:
    for entry in doc["entries"]:
        if entry["version"] == version and entry["edition"] == edition:
            return entry
    raise KeyError((edition, version))


def _write(case: unittest.TestCase, text: str) -> Path:
    return _write_bytes(case, text.encode("utf-8"))


def _write_bytes(case: unittest.TestCase, data: bytes) -> Path:
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    path = Path(tmp.name) / "catalog.json"
    path.write_bytes(data)
    return path


if __name__ == "__main__":
    unittest.main()
