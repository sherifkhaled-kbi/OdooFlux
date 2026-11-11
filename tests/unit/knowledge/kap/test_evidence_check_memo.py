"""RC performance fix: the per-record evidence schema check is memoised by content.

Rule creation validates the whole tree twice, so on a real pair (thousands of evidence rows) it re-ran the evidence
schema over every row each time. The schema check is a pure function of the record and the schema, so identical
records are checked once. Findings are identical; a changed record, or a changed schema, is checked again.
"""

import copy
import unittest
from unittest import mock

from odooflux.knowledge import checks
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge


class EvidenceCheckMemoTests(unittest.TestCase):
    def setUp(self):
        self.kb = load_knowledge(KNOWLEDGE_ROOT)
        checks._EVIDENCE_SCHEMA_MEMO.clear()

    def count(self, kb):
        real = checks.validator.check
        calls = []
        def spy(*args, **kwargs):  # the validator recurses through this name; count only the top-level calls
            if len(args) == 2 and not kwargs:
                calls.append(1)
            return real(*args, **kwargs)

        with mock.patch.object(checks.validator, "check", spy):
            findings = checks.check_evidence(kb)
        return findings, len(calls)

    def test_second_validation_of_the_same_records_does_not_recheck_them(self):
        first, n1 = self.count(self.kb)
        second, n2 = self.count(self.kb)
        self.assertGreater(n1, 100)
        self.assertEqual(n2, 0)
        self.assertEqual([f.line() for f in first], [f.line() for f in second])

    def test_findings_are_identical_with_and_without_the_memo(self):
        checks._EVIDENCE_SCHEMA_MEMO.clear()
        with_memo = [f.line() for f in checks.check_evidence(self.kb)]
        with mock.patch.object(checks, "_EVIDENCE_SCHEMA_MEMO", None):
            without = [f.line() for f in checks.check_evidence(self.kb)]
        self.assertEqual(with_memo, without)

    def test_a_changed_record_is_checked_again_and_its_problem_is_reported(self):
        self.count(self.kb)
        kb = copy.deepcopy(self.kb)
        key = next(iter(kb.evidence))
        kb.evidence[key]["locations"] = []  # fails the schema (minItems 1)
        kb.evidence_entries = [(f, kb.evidence[r["id"]] if r.get("id") == key else r) for f, r in kb.evidence_entries]
        findings, calls = self.count(kb)
        self.assertEqual(calls, 1)
        self.assertTrue(any(f.code == "E001" and key in f.file for f in findings))

    def test_a_changed_schema_is_not_served_from_the_memo(self):
        self.count(self.kb)
        real_schema = checks._schema
        stricter = copy.deepcopy(real_schema(self.kb, "evidence"))
        stricter["required"] = list(stricter.get("required", [])) + ["no_such_field"]
        with mock.patch.object(checks, "_schema", lambda kb, name: stricter if name == "evidence" else real_schema(kb, name)):
            findings = checks.check_evidence(self.kb)
        self.assertTrue(any("no_such_field" in f.message for f in findings))


if __name__ == "__main__":
    unittest.main()
