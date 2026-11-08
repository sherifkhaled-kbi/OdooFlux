"""TST-011-050 (REQ-KAP-011): manifest, assets and data (CSV) extractors.

Manifests are read with `ast.literal_eval` only (no import, no eval). The golden depends and version changes come from
the synthetic 16.0 and 17.0 trees (`tests/fixtures/kap/make_synth_repo.py`).
"""

import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.extract import driver as d
from odooflux.knowledge.extract.domains import assets, data, manifest
from tests.fixtures.kap import make_synth_repo as synth
from odooflux.builtins import build_registries  # composition root: the document adapters the KAP tests inject
REGISTRIES = build_registries()
TOOLKIT = REGISTRIES.extract_toolkit

ADDON = "addons/sale_demo"
ALL = manifest.EXTRACTORS + assets.EXTRACTORS + data.EXTRACTORS


class ManifestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "objects")

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self, name, files):
        root = self.base / name
        root.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return build_snapshot(root, "synth", name, self.store, created_at="2026-01-01T00:00:00Z")

    def pair(self, before_files, after_files, registry=ALL):
        before = self.snapshot("16", before_files)
        after = self.snapshot("17", after_files)
        return d.extract_pair(before, after, None, registry, store=self.store, step="16-17", toolkit=TOOLKIT)


class ManifestGolden(ManifestCase):
    def test_depends_diff_golden(self):
        result = self.pair(synth._TREE_16, synth._TREE_17, manifest.EXTRACTORS)
        own = [c for c in result.drafts if c["detail"].get("reason") != "UNSUPPORTED"]  # unclaimed files: UNKNOWN drafts
        changes = {(c["class"], c["subject_key"]) for c in own}
        self.assertEqual(changes, {("ADDED", "depends.account"), ("SIGNATURE_CHANGED", "version")})
        version = [c for c in result.drafts if c["subject_key"] == "version"][0]
        self.assertEqual(version["detail"]["to"], {"value": "17.0.1.0.0"})
        self.assertEqual(version["detail"]["from"], {"value": "16.0.1.0.0"})

    def test_manifest_literal_eval_only(self):
        marker = self.base / "executed.marker"
        payload = (f"{{'name': 'x', 'version': open({str(marker)!r}, 'w').write('ran') and '1.0'}}\n")
        before = self.snapshot("16", {f"{ADDON}/__manifest__.py": "{'name': 'x'}\n"})
        after = self.snapshot("17", {f"{ADDON}/__manifest__.py": payload})
        result = d.extract_pair(before, after, None, ALL, store=self.store, step="16-17", toolkit=TOOLKIT)
        self.assertFalse(marker.exists())
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("FAILED", "PARSE_ERROR"))

    def test_manifest_must_be_one_literal(self):
        result = self.pair({f"{ADDON}/__manifest__.py": "{'name': 'x'}\n"},
                           {f"{ADDON}/__manifest__.py": "x = {'name': 'x'}\n"}, manifest.EXTRACTORS)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("FAILED", "PARSE_ERROR"))


class AssetsMembership(ManifestCase):
    def test_assets_membership_golden(self):
        before = {f"{ADDON}/__manifest__.py": "{'assets': {'web.assets_backend': ['a/x.js']}}\n"}
        after = {f"{ADDON}/__manifest__.py":
                 "{'assets': {'web.assets_backend': ['a/x.js', 'a/y.js'],"
                 " 'web.assets_web': [('after', 'a/x.js', 'a/z.js')]}}\n"}
        result = self.pair(before, after, assets.EXTRACTORS)
        changes = {(c["class"], c["subject_key"], c["kind"]) for c in result.drafts}
        self.assertEqual(changes, {
            ("ADDED", "web.assets_backend::a/y.js", "member"),
            ("ADDED", "web.assets_web::a/z.js", "member"),
        })

    def test_synth_assets_unchanged(self):
        result = self.pair(synth._TREE_16, synth._TREE_17, assets.EXTRACTORS)
        # Files this domain does not claim appear as UNKNOWN/UNSUPPORTED (no silent skip): only this domain's drafts count.
        own = [c for c in result.drafts if c["detail"].get("reason") != "UNSUPPORTED"]
        self.assertEqual(own, [])


class DataCsv(ManifestCase):
    def test_csv_ids_golden(self):
        before = {f"{ADDON}/data/ir.sequence.csv": "id,name\nrec_a,Alpha\nrec_b,Beta\n"}
        after = {f"{ADDON}/data/ir.sequence.csv": "id,name\nrec_a,Alpha2\nrec_c,Gamma\n"}
        result = self.pair(before, after, data.EXTRACTORS)
        changes = {(c["class"], c["subject_key"]) for c in result.drafts}
        self.assertEqual(changes, {
            ("BEHAVIOUR_CHANGED", "ir.sequence::rec_a"),
            ("REMOVED", "ir.sequence::rec_b"),
            ("ADDED", "ir.sequence::rec_c"),
        })

    def test_csv_without_id_column_is_failed(self):
        before = {f"{ADDON}/data/ir.sequence.csv": "id,name\nrec_a,Alpha\n"}
        after = {f"{ADDON}/data/ir.sequence.csv": "name\nAlpha\n"}
        result = self.pair(before, after, data.EXTRACTORS)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("FAILED", "PARSE_ERROR"))


if __name__ == "__main__":
    unittest.main()
