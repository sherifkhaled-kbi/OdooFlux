"""TST-009-004 (REQ-REP-006, REQ-BIZ-003): verification-scope and recovery blocks are always rendered; honesty
about unrun layers, UNAVAILABLE vs FAIL, provisional label, rejected edits, per-file findings."""

import re
import unittest

from ._setup import SRC  # noqa: F401
from .helpers import all_goldens, golden

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(model, width=160, **kw):
    from odooflux.reporting.options import RendererOptions
    from odooflux.reporting.terminal.ansi import render_terminal
    return render_terminal(model, RendererOptions(color="never", width=width, **kw))


class SectionTests(unittest.TestCase):
    def test_scope_and_recovery_always_present(self):
        for name, model in all_goldens().items():
            text = plain(model)
            self.assertIn("VERIFICATION SCOPE", text, name)
            self.assertIn("RECOVERY", text, name)
            self.assertIn("MODULE RESULTS", text, name)
            self.assertIn("TOTALS modules=", text, name)

    def test_static_validated_states_install_and_behaviour_unverified(self):
        text = plain(golden("static_validated"))
        self.assertIn("STATIC_VALIDATED", text)
        self.assertRegex(text, r"(?s)Why not verified:.*installation \(L4\).*behaviour \(L5\)")
        self.assertIn("Not run:", text)

    def test_unrun_layers_never_shown_as_pass(self):
        text = plain(golden("static_validated"))
        self.assertRegex(text, r"L4 SKIPPED")
        for line in text.splitlines():
            if "L4" in line and ("PASS" in line):
                self.assertNotRegex(line, r"L4[ :]+PASS")
                self.assertNotRegex(line, r"L5[ :]+PASS")

    def test_unavailable_distinct_from_fail(self):
        text = plain(golden("mixed"), width=120)
        self.assertRegex(text, r"L3 UNAVAILABLE")
        self.assertRegex(text, r"L1 FAIL")
        self.assertNotIn("L3 FAIL", text)

    def test_verified_modules_show_layers_run(self):
        text = plain(golden("verified_success"))
        self.assertRegex(text, r"Ran: .*L4")
        self.assertNotIn("Why not verified", text)

    def test_rollback_command_in_write_mode(self):
        text = plain(golden("install_verified"))
        self.assertIn("Roll back: odooflux rollback run-golden", text)

    def test_dry_run_states_nothing_written(self):
        text = plain(golden("static_validated"))
        self.assertIn("nothing was written", text)
        self.assertNotIn("Roll back: odooflux rollback", text)

    def test_non_reversible_run_flagged(self):
        model = golden("install_verified")
        model["recovery"]["reversible"] = False
        self.assertIn("NOT reversible", plain(model))

    def test_provisional_label_rendered(self):
        text = plain(golden("provisional"))
        self.assertRegex(text, r"(?m)^PROVISIONAL RUN")
        self.assertNotIn("PROVISIONAL RUN", plain(golden("static_validated")))

    def test_rejected_edits_listed_with_reasons(self):
        text = plain(golden("failed"))
        self.assertIn("REJECTED EDITS (2)", text)
        self.assertIn("IndentationError line 119", text)
        self.assertIn("protected_identifier_changed", text)

    def test_per_file_findings_with_evidence_and_action(self):
        text = plain(golden("needs_review"), width=200, show_fixed=True)
        self.assertIn("kbi_hr_extension/views/hr.xml", text)
        self.assertRegex(text, r"WARNING +L42:UNKNOWN +17-18\.xml\.attrs-removed +\[NEEDS_REVIEW\]")
        self.assertIn("Action:", text)
        self.assertIn("EV-109 https://www.odoo.com/documentation/18.0/", text)
        self.assertIn("FIXED", text)

    def test_fixed_hidden_by_default(self):
        self.assertNotRegex(plain(golden("needs_review")), r"(?m)^ +FIXED ")

    def test_max_findings_per_file_caps_list_but_not_totals(self):
        model = golden("static_validated")
        text = plain(model, show_fixed=True, max_findings_per_file=1)
        self.assertIn("more finding(s) not shown", text)
        self.assertRegex(text, r"TOTALS modules=1 findings=4 ")

    def test_ai_usage_shown_when_enabled_and_off_state_stated(self):
        self.assertIn("AI USAGE  (enabled, consent given)", plain(golden("ai_enabled")))
        self.assertIn("anthropic/<configured-model>", plain(golden("ai_enabled")))
        self.assertIn("not used", plain(golden("static_validated")))

    def test_blocked_module_reason_visible(self):
        self.assertIn("module_blocked_before_analysis", plain(golden("blocked"), width=120) +
                      plain(golden("blocked"), width=120, verbose=True))
        self.assertIn("backup failed", plain(golden("blocked")))

    def test_progress_lines_in_verbose(self):
        from odooflux.reporting.terminal.progress import progress_lines
        lines = progress_lines(golden("mixed"))
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith("[1/4] kbi_sale_approval"))
        self.assertIn("PROGRESS", plain(golden("mixed"), verbose=True))
        self.assertNotIn("PROGRESS", plain(golden("mixed")))

    def test_runtime_section_for_verified_modules(self):
        text = plain(golden("install_verified"))
        self.assertIn("odoo:18.0", text)


if __name__ == "__main__":
    unittest.main()
