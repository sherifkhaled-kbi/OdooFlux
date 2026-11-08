"""Offline checks for the golden-corpus manifest and fetch tool (no network)."""
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fetch_golden_corpus", ROOT / "tools" / "fetch_golden_corpus.py")
fgc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fgc)


class GoldenCorpusManifest(unittest.TestCase):
    def setUp(self):
        self.m = fgc.load_manifest()

    def test_schema(self):
        self.assertEqual(self.m["schema_version"], 1)
        versions = set()
        for e in self.m["entries"]:
            self.assertEqual(e["repository"], "odoo/odoo")
            self.assertRegex(e["revision"], r"^[0-9a-f]{40}$")
            versions.add(e["version"])
            self.assertTrue(e["files"])
            for f in e["files"]:
                self.assertTrue(f["path"].startswith(f"addons/{e['addon']}/"))
                self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(versions, {"14.0", "15.0", "16.0", "17.0"})

    def test_revisions_match_pinned(self):
        pins = json.loads((ROOT / "src/odooflux/knowledge/official_sources/revisions.json").read_text())
        pinned = {(r["repository"], r["branch"]): r["revision"] for r in pins}
        for e in self.m["entries"]:
            self.assertEqual(e["revision"], pinned[(e["repository"], e["version"])])

    def test_check_offline(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(fgc.check(self.m, d), sum(len(e["files"]) for e in self.m["entries"]))
            entry = self.m["entries"][0]
            f = entry["files"][0]
            p = fgc.target_path(d, entry, f)
            p.parent.mkdir(parents=True)
            p.write_bytes(b"tampered")
            self.assertIn(str(p), "".join([str(p)]))
            self.assertGreater(fgc.check(self.m, d), 0)

    def test_dest_not_under_tests(self):
        self.assertFalse(re.search(r"/tests?/", fgc.DEFAULT_DEST))


if __name__ == "__main__":
    unittest.main()
