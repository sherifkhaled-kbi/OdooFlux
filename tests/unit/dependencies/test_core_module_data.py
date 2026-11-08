"""T046 (REQ-DEP-001): core module lists for 12.0-19.0 validate and cite an evidence record with their SHA."""

import unittest

from odooflux.knowledge.loader import load_knowledge

from .. import _setup  # noqa: F401


class CoreModuleDataTests(unittest.TestCase):
    def setUp(self):
        self.kb = load_knowledge()
        self.versions = {v["id"]: v for v in self.kb.core_modules["versions"]}

    def test_eight_versions_present(self):
        self.assertEqual(sorted(self.versions, key=float), [f"{n}.0" for n in range(12, 20)])

    def test_each_cites_evidence_with_the_same_sha(self):
        for vid, record in self.versions.items():
            evidence = self.kb.evidence[record["evidence"]]
            self.assertEqual(evidence["revision"], record["revision"], vid)
            self.assertIn(record["revision"], self.kb.revision_shas, vid)

    def test_lists_are_sorted_unique_and_contain_base(self):
        for vid, record in self.versions.items():
            self.assertEqual(record["modules"], sorted(set(record["modules"])), vid)
            self.assertIn("base", record["modules"], vid)

    def test_knowledge_base_validates(self):
        from odooflux.knowledge import checks
        errors = [f for f in checks.validate_knowledge(self.kb) if f.severity == "ERROR"]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
