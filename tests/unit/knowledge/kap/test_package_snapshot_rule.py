"""TST-011-011 (REQ-KAP-022, REQ-KAP-028): only snapshot MANIFESTS may ship in a package; blobs and everything else under
snapshots/, and all of staging/, stay forbidden (source content can be licensed)."""

import unittest

from odooflux.knowledge.package.builder import is_forbidden_entry


class SnapshotExportRuleTests(unittest.TestCase):
    def test_snapshot_manifest_allowed(self):
        self.assertFalse(is_forbidden_entry("snapshots/ss-0123456789ab.json"))

    def test_other_snapshot_content_forbidden(self):
        for rel in ("snapshots/blob.bin", "snapshots/ss-0123456789ab.json.bak", "snapshots/sub/ss-0123456789ab.json",
                    "snapshots/ss-0123456789AB.json", "snapshots/ss-0123456789a.json", "snapshots/",
                    "snapshots/blobs/ab/cd.bin"):
            self.assertTrue(is_forbidden_entry(rel), rel)

    def test_staging_always_forbidden(self):
        self.assertTrue(is_forbidden_entry("staging/x.json"))
        self.assertTrue(is_forbidden_entry("staging/ss-0123456789ab.json"))

    def test_ordinary_entries_allowed(self):
        for rel in ("release.json", "provenance/sources.json", "knowledge/compatibility/16-17.rules.json"):
            self.assertFalse(is_forbidden_entry(rel), rel)


if __name__ == "__main__":
    unittest.main()
