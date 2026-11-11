"""AD-05 / AF-4: every candidate edit gets one per-file verdict (VALID, INVALID or UNKNOWN).

INVALID rejects the file's edit and keeps the original text. UNKNOWN is kept and reported (nothing failed, but
nothing confirmed the text). A syntax check never proves semantic equivalence.
"""

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from odooflux.builtins import build_context
from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.records import ValidationResult
from odooflux.core.engine.step_runner import Step, run_step, validate_output
from odooflux.core.engine.verdict import INVALID, UNKNOWN, VALID, judge_output
from odooflux.core.orchestrator.module_plan import plan_module
from odooflux.validation.syntax.python import PythonSyntaxValidator
from odooflux.validation.syntax.xml import XmlSyntaxValidator


def _validators():
    return build_context().registries.validators.all()


def _replace(text):
    return lambda path, original: text


class PythonCompileTests(unittest.TestCase):
    def test_module_level_return_is_refused_like_compile_refuses_it(self):
        # ast.parse accepts a module-level return; compile() (the AD-05 check) does not
        result = PythonSyntaxValidator().validate("models/a.py", "return 1\n")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("outside function", result.reason)


class VerdictTests(unittest.TestCase):
    def test_invalid_python_output_is_rejected_and_original_kept(self):
        original = "x = 1\n"
        outcome = run_step(Step("s", [], _replace("def f(:\n")), "models/a.py", original, _validators())
        self.assertTrue(outcome.rejected)
        self.assertTrue(outcome.rejection.startswith("INVALID: "))
        self.assertEqual(outcome.output, original)
        self.assertEqual(outcome.verdict.status, INVALID)

    def test_invalid_xml_output_is_rejected_and_original_kept(self):
        original = "<odoo><record/></odoo>"
        outcome = run_step(Step("s", [], _replace("<odoo><record></odoo>")), "views/a.xml", original, _validators())
        self.assertTrue(outcome.rejected)
        self.assertEqual(outcome.output, original)
        self.assertEqual(outcome.verdict.status, INVALID)
        self.assertIn("not well-formed", outcome.rejection)

    def test_valid_outputs_are_valid_and_kept(self):
        cases = [("models/a.py", "x = 2\n"), ("views/a.xml", "<odoo/>"),
                 ("__manifest__.py", "{'name': 'x', 'version': '17.0.1.0.0'}")]
        for path, fixed in cases:
            with self.subTest(path=path):
                outcome = run_step(Step("s", [], _replace(fixed)), path, "x", _validators())
                self.assertFalse(outcome.rejected)
                self.assertEqual(outcome.output, fixed)
                self.assertEqual(outcome.verdict.status, VALID)
                self.assertEqual(outcome.verdict.as_dict(), {"status": VALID, "reason": ""})

    def test_unsupported_format_is_unknown_reported_and_kept(self):
        outcome = run_step(Step("s", [], _replace("body{}")), "static/a.css", "body {}", _validators())
        self.assertEqual(outcome.verdict.status, UNKNOWN)
        self.assertEqual(outcome.verdict.reason, "no syntax check exists for this file format")
        self.assertFalse(outcome.rejected)  # nothing failed: kept, with the uncertainty reported
        self.assertEqual(outcome.output, "body{}")

    def test_unknown_with_a_passing_check_and_an_unavailable_check_is_kept(self):
        @dataclass
        class Passes:
            layer: int = 1
            key: str = "fake.pass"
            contract_version: int = CONTRACT_VERSION

            def applies_to(self, path):
                return True

            def validate(self, path, text):
                return ValidationResult(layer=1, outcome="PASS")

        @dataclass
        class Unavailable(Passes):
            key: str = "fake.unavailable"

            def validate(self, path, text):
                return ValidationResult(layer=1, outcome="UNAVAILABLE", reason="checker missing")

        verdict = judge_output([Passes(), Unavailable()], "models/a.py", "x = 1\n")
        self.assertEqual(verdict.status, UNKNOWN)
        self.assertTrue(verdict.keep)
        self.assertIn("checker missing", verdict.reason)

    def test_validate_output_refuses_only_invalid(self):
        self.assertIsNone(validate_output(_validators(), "models/a.py", "x = 1\n"))
        self.assertIsNone(validate_output(_validators(), "static/a.css", "body{}"))
        self.assertTrue(validate_output(_validators(), "models/a.py", "def f(:\n").startswith("INVALID: "))


class PlanModuleVerdictTests(unittest.TestCase):
    def _module(self, root: Path) -> Path:
        module = root / "demo"
        (module / "models").mkdir(parents=True)
        (module / "__manifest__.py").write_text("{'name': 'demo', 'version': '17.0.1.0.0'}\n", encoding="utf-8")
        (module / "models" / "a.py").write_text("x = 1\n", encoding="utf-8")
        return module

    def _plan(self, module: Path, produce):
        def fake_fixer(path, from_version, to_version):
            return (lambda p, t: produce(t)) if path.endswith("a.py") else None

        with mock.patch("odooflux.rules.shared.legacy_adapter.fixer_for", side_effect=fake_fixer):
            _report, edits = plan_module(module, 16, 17, build_context().registries, compute_edits=True)
        return {e.path.name: e for e in edits}

    def test_invalid_output_leaves_the_file_as_written_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = self._module(Path(tmp))
            edits = self._plan(module, lambda t: "def f(:\n")
            edit = edits["a.py"]
            self.assertTrue(edit.rejection.startswith("INVALID: "))
            self.assertEqual(edit.validation.status, INVALID)
            self.assertEqual(edit.fixed, "x = 1\n")
            self.assertEqual((module / "models" / "a.py").read_text(encoding="utf-8"), "x = 1\n")

    def test_valid_output_carries_valid_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = self._module(Path(tmp))
            edit = self._plan(module, lambda t: t + "y = 2\n")["a.py"]
            self.assertFalse(edit.rejection)
            self.assertEqual(edit.validation.as_dict(), {"status": VALID, "reason": ""})
            self.assertEqual(edit.fixed, "x = 1\ny = 2\n")


if __name__ == "__main__":
    unittest.main()
