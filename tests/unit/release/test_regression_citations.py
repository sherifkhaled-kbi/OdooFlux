"""TST-010-002 (T004; REQ-TST-005, FR-002): every resolved finding F-... has a regression test that cites its id.
A finding is resolved when a completed (`[X]`) task in specs/*/tasks.md names it. Missing citations are reported by id."""

import unittest

from . import _fixture, rtm_tools


class SyntheticCitationTests(unittest.TestCase):
    TASKS = ["- [X] T001 Fix the thing (REQ-AAA-001; F-FOO-1, F-FOO-2)",
             "- [ ] T002 Not done yet (REQ-AAA-001; F-FOO-3)"]

    def test_missing_citations_are_reported_by_id(self):
        root = _fixture.make_repo(["REQ-AAA-001"], self.TASKS, tests={"regression/test_a.py": '"""F-FOO-1."""\n'})
        self.assertEqual(rtm_tools.check_regression_citations(root), ["F-FOO-2"])

    def test_unresolved_findings_are_not_required(self):
        root = _fixture.make_repo(["REQ-AAA-001"], self.TASKS, tests={"regression/test_a.py": "# F-FOO-1 F-FOO-2\n"})
        self.assertEqual(rtm_tools.check_regression_citations(root), [])

    def test_citation_in_a_test_name_counts(self):
        body = "class T:\n    def test_f_foo_2(self):\n        pass  # regression F-FOO-2\n"
        root = _fixture.make_repo(["REQ-AAA-001"], self.TASKS, tests={"a/test_b.py": "# F-FOO-1\n" + body})
        self.assertEqual(rtm_tools.check_regression_citations(root), [])


class RealCitationTests(unittest.TestCase):
    def test_every_resolved_finding_of_the_repository_is_cited(self):
        self.assertEqual(rtm_tools.check_regression_citations(), [])


if __name__ == "__main__":
    unittest.main()
