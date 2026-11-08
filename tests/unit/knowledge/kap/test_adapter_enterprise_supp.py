"""TST-011-037 (REQ-KAP-007, REQ-KAP-008): Enterprise-local and supplementary (OCA, OpenUpgrade) adapters.

Offline. Enterprise tests use a temporary directory the user "supplies"; no credentials, no sockets. Supplementary
tests reuse the synthetic repository (T030) as a local clone.
"""

import builtins
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge import validator as v
from odooflux.knowledge.acquisition.adapters.enterprise_local import EnterpriseLocalAdapter, community_limit_entry
from odooflux.knowledge.acquisition.adapters.supplementary import SupplementaryAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from tests.fixtures.kap.make_synth_repo import build_synth_repo

SCHEMA = json.loads((KNOWLEDGE_ROOT / "schemas" / "snapshot.schema.json").read_text(encoding="utf-8"))
ALLOW = ["https://github.com/odoo/odoo/", "https://github.com/odoo/enterprise/"]
CANARY = "CANARY-ENTERPRISE-TOKEN-7f3a"
REV = "3" * 40


def _spec(source_id, kind, url, revision, official=False, licence_access="UNKNOWN"):
    return {
        "source_id": source_id, "kind": kind, "official": official, "url": url,
        "licence_access": licence_access, "licence_id": "OEEL-1", "branch": "17.0", "revision": revision,
        "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": False,
    }


class EnterpriseLocalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.tree = self.base / "enterprise"
        (self.tree / "sale_enterprise").mkdir(parents=True)
        (self.tree / "sale_enterprise" / "__manifest__.py").write_text("{'name': 'Sale Enterprise'}\n")
        self.store = BlobStore(self.base / "store")
        self.spec = _spec("odoo-enterprise-17.0", "ENTERPRISE_LOCAL", f"local:{self.tree}", REV)

    def test_enterprise_skipped_without_entitlement(self):
        adapter = EnterpriseLocalAdapter(entitled=False)
        probe = adapter.probe(self.spec)
        self.assertEqual((probe["available"], probe["reason_code"]), (False, "AUTH_REQUIRED"))
        with self.assertRaises(SourceError) as ctx:
            adapter.snapshot(self.spec, self.store)
        self.assertEqual(ctx.exception.code, "AUTH_REQUIRED")
        self.assertFalse((self.base / "store").exists())  # nothing written when skipped
        # community-only builds continue: the skip is listed as an exclusion in limits
        community = {
            "snapshot_id": "ss-" + "a" * 12, "source_id": "odoo-community-17.0", "revision": "1" * 40,
            "entries": [], "snapshot_digest": "a" * 64, "created_at": "2026-11-08T10:00:00Z",
            "limits": {"excluded": [community_limit_entry(self.spec)]},
        }
        self.assertEqual(v.check(community, SCHEMA), [])
        self.assertIn("SKIPPED_UNAUTHORIZED", community["limits"]["excluded"][0]["reason"])
        self.assertEqual(community["limits"]["excluded"][0]["path"], "source:odoo-enterprise-17.0")
        # provenance records the constraints and the (absent) entitlement flag
        prov = adapter.provenance(self.spec)
        self.assertFalse(prov["entitled"])
        self.assertEqual(prov["licence_access"], "UNKNOWN")
        self.assertEqual(prov["licence_id"], "OEEL-1")

    def test_entitled_directory_snapshot_recorded(self):
        adapter = EnterpriseLocalAdapter(entitled=True)
        snap = adapter.snapshot(self.spec, self.store, created_at="2026-11-08T10:00:00Z")
        self.assertEqual(v.check(snap, SCHEMA), [])
        self.assertEqual([e["path"] for e in snap["entries"]], ["sale_enterprise/__manifest__.py"])
        self.assertTrue(adapter.provenance(self.spec)["entitled"])

    def test_no_network_no_credentials_read(self):
        real_open = builtins.open
        opened = []

        def spy_open(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        def no_socket(*args, **kwargs):
            raise AssertionError("enterprise adapter must not open sockets")

        adapter = EnterpriseLocalAdapter(entitled=True)
        with mock.patch.dict("os.environ", {"ODOO_ENTERPRISE_TOKEN": CANARY, "ODOO_API_KEY": CANARY}), \
                mock.patch.object(socket, "socket", side_effect=no_socket), \
                mock.patch.object(socket, "create_connection", side_effect=no_socket), \
                mock.patch.object(builtins, "open", side_effect=spy_open):
            snap = adapter.snapshot(self.spec, self.store, created_at="2026-11-08T10:00:00Z")
            prov = adapter.provenance(self.spec)
        for name in opened:
            self.assertNotIn("netrc", name)
            self.assertNotIn("credential", name.lower())
            self.assertNotIn(".odoorc", name)
        self.assertNotIn(CANARY, json.dumps(snap))
        self.assertNotIn(CANARY, json.dumps(prov))

    def test_remote_url_refused_without_network(self):
        adapter = EnterpriseLocalAdapter(entitled=True)
        remote = _spec("odoo-enterprise-17.0", "ENTERPRISE_LOCAL", "https://github.com/odoo/enterprise/", REV)
        probe = adapter.probe(remote)
        self.assertEqual(probe["reason_code"], "NETWORK_DISABLED")
        with self.assertRaises(SourceError) as ctx:
            adapter.snapshot(remote, self.store)
        self.assertEqual(ctx.exception.code, "NETWORK_DISABLED")

    def test_missing_path_reported_not_raised_as_crash(self):
        adapter = EnterpriseLocalAdapter(entitled=True)
        missing = _spec("odoo-enterprise-17.0", "ENTERPRISE_LOCAL", f"local:{self.base / 'absent'}", REV)
        self.assertEqual(adapter.probe(missing)["reason_code"], "IO_ERROR")
        with self.assertRaises(SourceError) as ctx:
            adapter.snapshot(missing, self.store)
        self.assertEqual(ctx.exception.code, "IO_ERROR")


class SupplementaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = build_synth_repo(Path(cls._tmp.name) / "synth")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.store = BlobStore(Path(self._dir.name) / "store")

    def test_supplementary_labelled_unofficial(self):
        for kind, source_id in (("OCA", "oca-web-17.0"), ("OPENUPGRADE", "openupgrade-17.0")):
            with self.subTest(kind=kind):
                # the spec file claims official=true; the adapter forces it to false (source-adapter rule 5)
                spec = _spec(source_id, kind, f"local:{self.repo.path}", self.repo.to_sha, official=True)
                adapter = SupplementaryAdapter(kind, allow_list=ALLOW)
                label = adapter.label(spec)
                self.assertEqual(label["official"], False)
                self.assertEqual(label["label"], "SUPPLEMENTARY_NON_OFFICIAL")
                self.assertEqual(label["kind"], kind)
                snap = adapter.snapshot(spec, self.store, created_at="2026-11-08T10:00:00Z")
                self.assertTrue(snap["entries"])
                self.assertEqual(adapter.probe(spec)["available"], True)

    def test_supplementary_rejects_non_supplementary_kind(self):
        with self.assertRaises(ValueError):
            SupplementaryAdapter("GIT_COMMUNITY")


if __name__ == "__main__":
    unittest.main()
