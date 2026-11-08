"""TST-010-001 (T003; REQ-TST-005, REQ-TST-002): the RTM completeness check fails on any REQ without a passing mapped
test, a DEFERRED_KB backlog id (A-8) or a verification record, and names the REQ.

Synthetic repositories exercise each branch; the last class runs the check on the real repository."""

import unittest

from . import _fixture, rtm_tools

TASKS = ["- [X] T001 Do a thing (REQ-AAA-001; TST-001-001)",
         "- [X] T002 Another (REQ-AAA-002; TST-001-002)"]


class SyntheticRtmTests(unittest.TestCase):
    def test_unmapped_req_fails_and_is_named(self):
        root = _fixture.make_repo(["REQ-AAA-001", "REQ-AAA-002"], TASKS,
                                  tests={"t/test_a.py": '"""TST-001-001"""\n'})
        result = rtm_tools.check_rtm(root)
        self.assertFalse(result.ok)
        self.assertTrue(any(m.startswith("REQ-AAA-002:") for m in result.failures), result.failures)
        self.assertFalse(any(m.startswith("REQ-AAA-001:") for m in result.failures))

    def test_all_mapped_passes(self):
        root = _fixture.make_repo(["REQ-AAA-001", "REQ-AAA-002"], TASKS, tests={
            "t/test_a.py": '"""TST-001-001 TST-001-002"""\n'})
        result = rtm_tools.check_rtm(root)
        self.assertTrue(result.ok, result.failures)
        self.assertEqual(result.counts()["TESTED"], 2)

    def test_citing_the_req_id_in_a_test_counts(self):
        root = _fixture.make_repo(["REQ-AAA-001"], ["- [X] T001 No test id here (REQ-AAA-001)"],
                                  tests={"t/test_a.py": '"""Covers REQ-AAA-001."""\n'})
        self.assertTrue(rtm_tools.check_rtm(root).ok)

    def test_deferred_kb_with_a_known_backlog_id_passes(self):
        root = _fixture.make_repo(["REQ-AAA-001"], TASKS[:1], gate="| REQ-AAA-001 | DEFERRED_KB | KB-X-1 | why |\n")
        result = rtm_tools.check_rtm(root)
        self.assertTrue(result.ok, result.failures)
        self.assertEqual(result.rows[0].status, "DEFERRED_KB")

    def test_deferred_kb_without_a_backlog_id_fails(self):
        root = _fixture.make_repo(["REQ-AAA-001"], TASKS[:1], gate="| REQ-AAA-001 | DEFERRED_KB |  | why |\n")
        result = rtm_tools.check_rtm(root)
        self.assertFalse(result.ok)
        self.assertTrue(any("REQ-AAA-001" in m for m in result.failures))

    def test_deferred_kb_with_an_unknown_backlog_id_fails(self):
        root = _fixture.make_repo(["REQ-AAA-001"], TASKS[:1], gate="| REQ-AAA-001 | DEFERRED_KB | KB-NOPE-9 | why |\n")
        result = rtm_tools.check_rtm(root)
        self.assertFalse(result.ok)
        self.assertTrue(any("KB-NOPE-9" in m for m in result.failures))

    def test_tested_requirement_may_also_list_a_partial_deferral(self):
        root = _fixture.make_repo(["REQ-AAA-001"], TASKS[:1], tests={"t/test_a.py": "# TST-001-001\n"},
                                  gate="| REQ-AAA-001 | DEFERRED_KB | KB-X-2 | partial |\n")
        result = rtm_tools.check_rtm(root)
        self.assertTrue(result.ok)
        self.assertEqual(result.rows[0].status, "TESTED")
        self.assertIn("KB-X-2", result.rows[0].notes[0])

    def test_verification_record_passes_only_when_file_and_anchor_exist(self):
        root = _fixture.make_repo(["REQ-AAA-001"], TASKS[:1],
                                  records="| REQ-AAA-001 | docs/record.md | RV-1 recorded |\n")
        self.assertFalse(rtm_tools.check_rtm(root).ok)  # file missing
        (root / "docs/record.md").write_text("nothing here\n", encoding="utf-8")
        self.assertFalse(rtm_tools.check_rtm(root).ok)  # anchor missing
        (root / "docs/record.md").write_text("RV-1 recorded on a date\n", encoding="utf-8")
        result = rtm_tools.check_rtm(root)
        self.assertTrue(result.ok, result.failures)
        self.assertEqual(result.rows[0].status, "RECORD")

    def test_deferral_tag_on_a_task_must_name_a_real_backlog_id(self):
        bad = ["- [ ] T001 Later (REQ-AAA-001) [DEFERRED_KB]"]
        root = _fixture.make_repo(["REQ-AAA-001"], bad, tests={"t/test_a.py": "# REQ-AAA-001\n"})
        self.assertTrue(any("without a backlog id" in m for m in rtm_tools.check_rtm(root).failures))
        unknown = ["- [ ] T001 Later (REQ-AAA-001) [DEFERRED_KB: KB-NOPE-1]"]
        root = _fixture.make_repo(["REQ-AAA-001"], unknown, tests={"t/test_a.py": "# REQ-AAA-001\n"})
        self.assertTrue(any("KB-NOPE-1" in m for m in rtm_tools.check_rtm(root).failures))

    def test_undeclared_task_deferral_is_a_warning(self):
        tagged = ["- [ ] T001 Later (REQ-AAA-001) [DEFERRED_KB: KB-X-1]"]
        root = _fixture.make_repo(["REQ-AAA-001"], tagged, tests={"t/test_a.py": "# REQ-AAA-001\n"})
        result = rtm_tools.check_rtm(root)
        self.assertTrue(result.ok)
        self.assertTrue(any("KB-X-1" in m for m in result.warnings))

    def test_opt_in_only_tests_warn_and_fail_when_strict(self):
        root = _fixture.make_repo(["REQ-AAA-001"], TASKS[:1], tests={
            "t/test_a.py": 'import unittest\n@unittest.skipUnless(False, "opt in")\nclass T: pass  # TST-001-001\n'})
        self.assertTrue(rtm_tools.check_rtm(root).ok)
        self.assertTrue(rtm_tools.check_rtm(root).warnings)
        self.assertFalse(rtm_tools.check_rtm(root, strict=True).ok)

    def test_main_exit_code_follows_the_result(self):
        root = _fixture.make_repo(["REQ-AAA-001"], TASKS[:1])
        self.assertEqual(rtm_tools.main(["--root", str(root)]), 1)


class RealRtmTests(unittest.TestCase):
    def test_repository_rtm_has_no_unmapped_requirement(self):
        result = rtm_tools.check_rtm()
        self.assertEqual(result.failures, [], rtm_tools.format_report(result))

    def test_repository_rtm_lists_every_requirement(self):
        """92 product requirements (features 001-010) plus the 47 REQ-KAP requirements of feature 011. A change to this
        count is an explicit decision to add or remove requirements, never a side effect."""
        rows = rtm_tools.check_rtm().rows
        kap = [r for r in rows if r.req.startswith("REQ-KAP-")]
        self.assertEqual(len(kap), 47)
        self.assertEqual(len(rows) - len(kap), 92)


if __name__ == "__main__":
    unittest.main()
