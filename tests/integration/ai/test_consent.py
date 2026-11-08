"""TST-007-004 (REQ-AI-001, REQ-SEC-003): --ai without consent stops before discovery."""

import contextlib
import io
import unittest

from odooflux.builtins import main
from tests.integration.helpers import make_module, new_tmp


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


class ConsentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = new_tmp()
        self.module = make_module(self.tmp, "kbi_demo")
        self.base = ["--module", self.module, "--from-version", "14", "--to-version", "19", "--fix",
                     "--state-dir", self.tmp / "state"]

    def test_ai_without_consent_is_a_configuration_error_before_discovery(self):
        code, out, err = run(self.base + ["--ai", "--ai-provider", "fake", "--ai-model", "fake-model",
                                          "--ai-budget-job-tokens", "1000"])
        self.assertEqual(code, 2)
        self.assertIn("--ai-consent-send-code", err)
        self.assertNotIn("Modules :", out)
        self.assertFalse((self.tmp / "state").exists())

    def test_ai_without_job_budget_is_a_configuration_error(self):
        code, _out, err = run(self.base + ["--ai", "--ai-consent-send-code", "--ai-provider", "fake",
                                           "--ai-model", "fake-model"])
        self.assertEqual(code, 2)
        self.assertIn("--ai-budget-job-tokens", err)

    def test_ai_without_provider_names_the_flag(self):
        code, _out, err = run(self.base + ["--ai", "--ai-consent-send-code", "--ai-budget-job-tokens", "10"])
        self.assertEqual(code, 2)
        self.assertIn("--ai-provider", err)

    def test_ai_and_legacy_ai_fix_are_exclusive(self):
        code, _out, err = run(self.base + ["--ai", "--ai-fix"])
        self.assertEqual(code, 2)
        self.assertIn("--ai-fix", err)


if __name__ == "__main__":
    unittest.main()
