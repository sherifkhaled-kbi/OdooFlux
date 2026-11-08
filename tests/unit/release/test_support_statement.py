"""TST-010-003 (T006; REQ-VER-003, REQ-EVD-006; SC-005, FC A-9): a version path is `supported` only when every step is
`RULES_TESTED` and the target is `RUNTIME_VALIDATED`. Everything else is experimental or unsupported and is listed in
the required section "Not yet supported (knowledge pending)". Paths that rest on the provisional corpus say so."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.unit import _setup  # noqa: F401

from odooflux.cli import support_statement as ss


def facts(step, rules="RULES_TESTED", runtime="RUNTIME_VALIDATED", research="RESEARCHED", runnable=3,
          provisional=False):
    return ss.StepFacts(step=step, research=research, rules=rules, runtime=runtime, runnable_rules=runnable,
                        provisional=provisional)


class ClassifyTests(unittest.TestCase):
    def classify(self, *steps):
        return ss.classify_path("14.0", "16.0", list(steps))

    def test_all_steps_rules_tested_and_target_validated_is_supported(self):
        row = self.classify(facts("14-15", runtime="—"), facts("15-16"))
        self.assertEqual(row.status, "supported")

    def test_rules_tested_without_runtime_validation_is_not_supported(self):
        row = self.classify(facts("14-15"), facts("15-16", runtime="—"))
        self.assertNotEqual(row.status, "supported")
        self.assertTrue(any("RUNTIME_VALIDATED" in r for r in row.reasons))

    def test_one_step_below_rules_tested_is_not_supported(self):
        row = self.classify(facts("14-15", rules="RULES_DRAFTED"), facts("15-16"))
        self.assertNotEqual(row.status, "supported")
        self.assertTrue(any("14-15" in r and "RULES_TESTED" in r for r in row.reasons))

    def test_failed_runtime_run_is_not_supported(self):
        row = self.classify(facts("14-15"), facts("15-16", runtime="RUN_FAILED"))
        self.assertNotEqual(row.status, "supported")

    def test_runtime_validation_of_an_intermediate_step_alone_is_not_enough(self):
        row = self.classify(facts("14-15", rules="NOT_ASSESSED"), facts("15-16", runtime="—", rules="NOT_ASSESSED"))
        self.assertNotEqual(row.status, "supported")

    def test_experimental_needs_runnable_rules_on_every_step(self):
        row = self.classify(facts("14-15", rules="NOT_ASSESSED", runtime="—", research="RESEARCH_SEEDED"),
                            facts("15-16", rules="NOT_ASSESSED", runtime="—", research="RESEARCH_SEEDED"))
        self.assertEqual(row.status, "experimental")
        row = self.classify(facts("14-15", rules="NOT_ASSESSED", runtime="—", research="RESEARCH_SEEDED"),
                            facts("15-16", rules="NOT_ASSESSED", runtime="—", research="RESEARCH_SEEDED", runnable=0))
        self.assertEqual(row.status, "unsupported")

    def test_missing_research_is_unsupported(self):
        row = self.classify(facts("14-15", rules="NOT_ASSESSED", runtime="—", research="NOT_ASSESSED"),
                            facts("15-16", rules="NOT_ASSESSED", runtime="—", research="NOT_ASSESSED"))
        self.assertEqual(row.status, "unsupported")

    def test_provisional_step_labels_the_path_and_never_hides_it(self):
        row = self.classify(facts("14-15", rules="NOT_ASSESSED", runtime="—", provisional=True), facts("15-16"))
        self.assertTrue(row.provisional)
        supported = self.classify(facts("14-15", provisional=True), facts("15-16"))
        self.assertEqual(supported.status, "supported")
        self.assertTrue(supported.provisional)


class RenderTests(unittest.TestCase):
    def rows(self):
        return [ss.classify_path("14.0", "15.0", [facts("14-15")]),
                ss.classify_path("15.0", "16.0", [facts("15-16", rules="NOT_ASSESSED", runtime="—")]),
                ss.classify_path("16.0", "17.0", [facts("16-17", rules="NOT_ASSESSED", runtime="—", runnable=0,
                                                         research="NOT_ASSESSED", provisional=True)])]

    def test_required_sections_and_pending_ids(self):
        text = ss.render(self.rows(), step_facts=[], pending=ss.PENDING_BACKLOG)
        self.assertIn("## Not yet supported (knowledge pending)", text)
        self.assertIn("## Supported paths", text)
        self.assertIn("## Verification limits", text)
        pending = text.split("## Not yet supported (knowledge pending)")[1]
        self.assertIn("15.0 → 16.0", pending)
        self.assertIn("16.0 → 17.0", pending)
        self.assertNotIn("14.0 → 15.0", pending)
        for kb in ss.PENDING_BACKLOG:
            self.assertIn(kb, pending)

    def test_supported_section_is_explicit_when_empty(self):
        rows = [ss.classify_path("15.0", "16.0", [facts("15-16", rules="NOT_ASSESSED", runtime="—")])]
        text = ss.render(rows, step_facts=[], pending=ss.PENDING_BACKLOG)
        self.assertIn("No path is supported", text)

    def test_provisional_rows_carry_the_label(self):
        text = ss.render(self.rows(), step_facts=[], pending=ss.PENDING_BACKLOG)
        line = next(l for l in text.splitlines() if l.startswith("| 16.0 → 17.0"))
        self.assertIn("PROVISIONAL", line)

    def test_output_is_deterministic(self):
        self.assertEqual(ss.render(self.rows(), [], ss.PENDING_BACKLOG), ss.render(self.rows(), [], ss.PENDING_BACKLOG))

    def test_no_approval_wording(self):
        text = ss.render(self.rows(), [], ss.PENDING_BACKLOG)
        self.assertNotRegex(text.lower(), r"\bapproved by\b|\bsigned off\b|\bcertified\b(?! )")


class RealDataTests(unittest.TestCase):
    def test_pending_backlog_ids_exist_in_the_backlog(self):
        text = (Path(__file__).resolve().parents[3] / "docs/planning/KNOWLEDGE_BASE_BACKLOG.md").read_text("utf-8")
        for kb in ss.PENDING_BACKLOG:
            self.assertIn(f"| {kb} |", text)

    def test_real_matrix_lists_no_supported_path(self):
        rows, _ = ss.build_rows()
        self.assertEqual(len(rows), 28)  # 8 versions: every ordered pair source < target
        self.assertEqual([r for r in rows if r.status == "supported"], [])

    def test_validation_path_is_experimental_and_provisional(self):
        rows, _ = ss.build_rows()
        row = next(r for r in rows if (r.source, r.target) == ("17.0", "18.0"))
        self.assertEqual(row.status, "experimental")
        self.assertTrue(row.provisional)

    def test_committed_statement_matches_the_generator(self):
        path = Path(__file__).resolve().parents[3] / "docs/planning/SUPPORT_STATEMENT.md"
        self.assertTrue(path.is_file(), "run: odooflux support-statement --out docs/planning/SUPPORT_STATEMENT.md")
        self.assertEqual(path.read_text(encoding="utf-8"), ss.generate_text())


class CommandTests(unittest.TestCase):
    def test_out_writes_and_check_detects_drift(self):
        out = Path(tempfile.mkdtemp()) / "S.md"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ss.main(["--out", str(out)]), 0)
            self.assertEqual(ss.main(["--out", str(out), "--check"]), 0)
            out.write_text("stale\n", encoding="utf-8")
            self.assertEqual(ss.main(["--out", str(out), "--check"]), 1)

    def test_dispatch_through_the_cli(self):
        from odooflux.builtins import main as cli_main  # noqa: F401  (the launcher entry point)
        out = Path(tempfile.mkdtemp()) / "S.md"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main(["support-statement", "--out", str(out)]), 0)
        self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()


class InstalledPackageGuardTests(unittest.TestCase):
    """Review R3 finding: outside a source checkout the command must refuse, not emit a statement without labels."""

    def test_refuses_when_the_fixture_index_is_missing(self):
        import io
        from contextlib import redirect_stderr
        from unittest import mock
        from odooflux.cli import support_statement as ss
        err = io.StringIO()
        with mock.patch.object(ss, "FIXTURE_INDEX", ss.REPO_ROOT / "does-not-exist.json"), redirect_stderr(err):
            code = ss.main(["--check"])
        self.assertEqual(code, 2)
        self.assertIn("source checkout", err.getvalue())
