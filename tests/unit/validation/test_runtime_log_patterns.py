"""TST-008-005 data half (REQ-VAL-004, REQ-ACL-002, G-R-22): runtime log patterns are data with evidence
and pass the knowledge checker; every FR-006 log class is covered by at least one pattern."""

import re
import unittest

from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import load_knowledge

from .._setup import SRC  # noqa: F401

FILE = "compatibility/runtime_log_patterns.json"
LOG_CLASSES = {"import_error", "registry", "view_validation", "access_rights", "data_load",
               "asset_compile", "missing_python_dependency"}


class RuntimeLogPatternsTests(unittest.TestCase):
    def setUp(self):
        self.kb = load_knowledge()

    def test_patterns_pass_knowledge_validation(self):
        findings = [f for f in validate_knowledge(self.kb) if f.file == FILE]
        self.assertEqual([f.line() for f in findings], [])

    def test_each_log_class_has_a_pattern_with_evidence(self):
        patterns = self.kb.runtime_patterns.get("patterns", [])
        self.assertEqual(LOG_CLASSES - {p["class"] for p in patterns}, set())
        for p in patterns:
            with self.subTest(p["id"]):
                self.assertTrue(p["evidence"])
                self.assertIsNotNone(re.compile(p["pattern"]))

    def test_invalid_regex_is_reported(self):
        kb = load_knowledge()
        kb.runtime_patterns = {"schema": "odooflux.runtime-log-patterns/1", "patterns": [
            {"id": "registry.bad-regex", "class": "registry", "pattern": "([",
             "version_range": {"from": "16.0", "to": "19.0"}, "evidence": ["EV-360"]}]}
        findings = [f for f in validate_knowledge(kb) if f.file == FILE]
        self.assertTrue(any("regex" in f.message for f in findings), findings)


if __name__ == "__main__":
    unittest.main()
