"""TST-003-034 and TST-003-035 (REQ-SAF-009, FR-014): resume after an interruption at every module
boundary yields the same report as an uninterrupted run; a changed source is refused."""

import unittest
from pathlib import Path

from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator.run import SourceChangedError
from odooflux.core.recovery.resume import resume
from odooflux.builtins import build_context

from .helpers import make_module, new_tmp, normalised_report, start_run, tree

NAMES = ["kbi_a", "kbi_b", "kbi_c"]


class Interrupt(RuntimeError):
    pass


def _interrupt_after(name):
    def hook(done):
        if done == name:
            raise Interrupt(f"stop after {name}")
    return hook


class ResumeTests(unittest.TestCase):
    def test_resume_equals_uninterrupted_at_each_boundary(self):
        clean_root = new_tmp()
        clean_modules = [make_module(clean_root / "src", n) for n in NAMES]
        clean_run, _ = start_run(clean_root / "state", clean_modules)
        expected = normalised_report(clean_root / "state", clean_run, [clean_root / "src"])

        for boundary in NAMES[:-1]:
            with self.subTest(after=boundary):
                root = new_tmp()
                modules = [make_module(root / "src", n) for n in NAMES]
                with self.assertRaises(Interrupt):
                    start_run(root / "state", modules, hook=_interrupt_after(boundary))
                (run_dir,) = list((root / "state" / "runs").iterdir())
                ctx = build_context()
                resume(root / "state", run_dir.name, ctx.registries, layer3=ctx.layer3)
                actual = normalised_report(root / "state", run_dir.name, [root / "src"])
                self.assertEqual(actual, expected)

    def test_resume_refused_when_a_pending_source_changed(self):
        root = new_tmp()
        modules = [make_module(root / "src", n) for n in NAMES]
        with self.assertRaises(Interrupt):
            start_run(root / "state", modules, hook=_interrupt_after("kbi_a"))
        (run_dir,) = list((root / "state" / "runs").iterdir())
        (modules[2] / "models" / "demo.py").write_text("# edited after the interruption\n", encoding="utf-8")
        with self.assertRaises(SourceChangedError):
            resume(root / "state", run_dir.name, build_context().registries, layer3=build_context().layer3)


if __name__ == "__main__":
    unittest.main()
