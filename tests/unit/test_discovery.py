"""TST-003-011 (REQ-VER-006, REQ-MAN-001): discovery reads manifests as literals, reports problems,
skips manifest-less directories, never follows escaping symlinks, and writes nothing."""

import os
import tempfile
import unittest
from pathlib import Path

from odooflux.discovery.ignore import IgnoreRules
from odooflux.discovery.modules import find_modules, iter_module_files, manifest_findings, module_ref
from odooflux.utils.hashing import digest_tree

from ._setup import SRC  # noqa: F401


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addons = self.root / "addons"
        self.addons.mkdir()
        good = self.addons / "good"
        good.mkdir()
        (good / "__manifest__.py").write_text("{'name': 'good', 'version': '14.0.1.0.0', 'depends': ['base']}\n")
        bad = self.addons / "bad"
        bad.mkdir()
        (bad / "__manifest__.py").write_text("{'name': os.system('x')}\n")  # not a literal
        (self.addons / "plain").mkdir()  # no manifest
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "__manifest__.py").write_text("{'name': 'escape'}\n")
        os.symlink(outside, self.addons / "escape")

    def tearDown(self):
        self._tmp.cleanup()

    def test_finds_modules_skips_plain_and_escaping_symlinks(self):
        findings = []
        found = find_modules([], [self.addons], findings)
        self.assertEqual([p.name for p in found], ["bad", "good"])
        self.assertIn("NO_MANIFEST", [f["rule_id"] for f in findings])

    def test_declared_version_and_mismatch_findings(self):
        good = module_ref(self.addons / "good")
        self.assertEqual(good.declared_version, "14.0.1.0.0")
        self.assertEqual(manifest_findings(good, 14), [])
        mismatch = manifest_findings(good, 16)
        self.assertEqual(mismatch[0]["rule_id"], "VERSION_MISMATCH")

    def test_malformed_manifest_becomes_a_finding(self):
        bad = module_ref(self.addons / "bad")
        self.assertIsNone(bad.declared_version)
        self.assertEqual(manifest_findings(bad, 14)[0]["rule_id"], "MANIFEST_MALFORMED")

    def test_discovery_writes_nothing(self):
        before = digest_tree(self.root)
        find_modules([], [self.addons], [])
        [module_ref(p) for p in (self.addons / "good", self.addons / "bad")]
        self.assertEqual(digest_tree(self.root), before)

    def test_gitignore_negation_anchor_and_dir_only(self):
        rules = IgnoreRules(["*.pyc", "!keep.pyc", "/build", "tmp/"])
        self.assertTrue(rules.ignored("a.pyc"))
        self.assertFalse(rules.ignored("keep.pyc"))
        self.assertTrue(rules.ignored("build", True))
        self.assertFalse(rules.ignored("sub/build", True))
        self.assertTrue(rules.ignored("tmp", True))
        self.assertFalse(rules.ignored("tmp", False))

    def test_module_walk_ignores_gitignored_files(self):
        module = self.addons / "good"
        (module / "junk.pyc").write_text("x")
        (module / ".gitignore").write_text("*.pyc\n")
        names = [p.name for p in iter_module_files(module)]
        self.assertNotIn("junk.pyc", names)
        self.assertIn("__manifest__.py", names)


if __name__ == "__main__":
    unittest.main()
