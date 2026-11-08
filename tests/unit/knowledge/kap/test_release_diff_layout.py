"""TST-011-014 (REQ-KAP-030): destructive-change detection must work on the real release layout, where the manifest lists
records as `knowledge/compatibility/*.rules.json` and `knowledge/evidence/*.json` (found by the T017 CLI tests)."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.release.diff import _family, diff_releases
from odooflux.knowledge.release.manifest import write_release_manifest

from .test_release_diff import META, _evidence, _index, _rule


def _real_layout_release(root: Path, rules, evidence) -> Path:
    (root / "knowledge" / "compatibility").mkdir(parents=True)
    (root / "knowledge" / "evidence").mkdir(parents=True)
    (root / "knowledge" / "compatibility" / "16-17.rules.json").write_text(
        json.dumps(rules, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for record in evidence:
        (root / "knowledge" / "evidence" / f"{record['id']}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_release_manifest(root, META)
    return root


class RealLayoutTests(unittest.TestCase):
    def test_family_accepts_prefixed_and_bare_paths(self):
        self.assertEqual("rules", _family("knowledge/compatibility/16-17.rules.json"))
        self.assertEqual("rules", _family("compatibility/16-17.rules.json"))
        self.assertEqual("evidence", _family("knowledge/evidence/EV-900.json"))
        self.assertIsNone(_family("knowledge/schemas/rule_metadata.schema.json"))

    def test_removed_rule_is_destructive_in_a_real_layout_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            a = _real_layout_release(base / "a", [_rule("16-17.python.one"), _rule("16-17.python.two")],
                                     [_evidence("EV-900", "VERIFIED")])
            b = _real_layout_release(base / "b", [_rule("16-17.python.one")], [])
            diff = diff_releases(a, b)
            index = _index(diff)
            self.assertTrue(index[("rules", "16-17.python.two")]["destructive"])
            self.assertTrue(index[("evidence", "EV-900")]["destructive"])
            self.assertTrue(diff.has_destructive)


if __name__ == "__main__":
    unittest.main()
