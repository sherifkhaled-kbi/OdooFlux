"""PA-3 (approved partial-migration policy): a module is never rolled back because one file's change is refused.

- the refused file keeps its original bytes; the other files of the module are still written (NEVER invalid output);
- a file whose whole-file transform is refused keeps the output of its last VALID stage;
- counts (fixes applied, files written) exclude refused changes; a module with refused edits is
  ``PARTIAL — DEVELOPER ACTION REQUIRED`` and fails the exit gate like FAILED; an all-valid module is unchanged;
- explicit rollback still restores every touched file from the run's backup.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.builtins import build_context
from odooflux.cli.exit_codes import ExitPolicy, exit_code
from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator import knowledge_rules
from odooflux.core.orchestrator.module_plan import plan_module
from odooflux.core.orchestrator.run import reports_from_state
from odooflux.core.orchestrator.status import PARTIAL_STATUS
from odooflux.core.recovery.rollback import rollback
from odooflux.reporting.model.model import build_report
import odooflux.rules.shared.legacy_adapter as adapter

from .helpers import start_run

BROKEN = "def broken(:\n"


def _module(root: Path) -> Path:
    module = root / "demo"
    (module / "models").mkdir(parents=True)
    (module / "__manifest__.py").write_text("{'name': 'demo', 'version': '16.0.1.0.0', 'depends': ['base']}\n",
                                            encoding="utf-8")
    (module / "models" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (module / "models" / "b.py").write_text("y = 2\n", encoding="utf-8")
    return module


def _snapshot(module: Path) -> dict:
    return {p.relative_to(module).as_posix(): p.read_bytes() for p in module.rglob("*") if p.is_file()}


def _fixer(a_output: str, b_output_suffix: str):
    """Legacy fixer double: a.py gets *a_output* (a function of the text), b.py gets its text plus a valid line."""
    def fake(path, from_version, to_version):
        if path.endswith("a.py"):
            return lambda p, t: a_output
        if path.endswith("b.py"):
            return lambda p, t: t + b_output_suffix
        return None
    return fake


class PartialMigrationRunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.module = _module(self.tmp / "addons")
        self.before = _snapshot(self.module)
        self.state_dir = self.tmp / "state"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, mode, fake):
        with mock.patch.object(adapter, "fixer_for", side_effect=fake):
            return start_run(self.state_dir, [self.module], mode=mode, from_v=16, to_v=17)

    def test_refused_file_kept_other_file_written_and_module_partial(self):
        run_id, state = self._run("fix", _fixer(BROKEN, "z = 3\n"))
        after = _snapshot(self.module)
        self.assertEqual(after["models/a.py"], self.before["models/a.py"], "the refused file stays byte-identical")
        self.assertEqual(after["models/b.py"], b"y = 2\nz = 3\n", "the valid file of the same module is written")
        self.assertNotIn(BROKEN.encode(), after.get("models/a.py", b""))

        report = build_report(state, reports_from_state(state))
        module = report["modules"][0]
        self.assertEqual(module["status"], PARTIAL_STATUS)
        self.assertEqual(state["modules"][0]["migration_status"], PARTIAL_STATUS)
        self.assertTrue(module["rejections"][0].startswith("INVALID: "), module["rejections"])
        self.assertEqual(report["summary"]["edits"]["rejected"], 1)
        self.assertEqual(report["summary"]["edits"]["applied"], 1, "a refused change is never counted as applied")
        self.assertEqual(report["summary"]["files_written"], 1)
        self.assertEqual([p.rsplit("/", 1)[-1] for p in module["promoted_files"]], ["b.py"])

        rejected = [f for f in module["findings"] if f["rule_id"] == "Fix Rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["path"], "models/a.py")
        self.assertEqual(rejected[0]["reason_not_fixed"], module["rejections"][0])

        self.assertEqual(exit_code(report, write_mode=True), 3, "rejected edits in write mode keep exit code 3")

    def test_partial_status_text_is_exact(self):
        self.assertEqual(PARTIAL_STATUS, "PARTIAL — DEVELOPER ACTION REQUIRED")

    def test_rollback_restores_every_touched_file(self):
        run_id, _state = self._run("fix", _fixer(BROKEN, "z = 3\n"))
        run = RunDir.open(self.state_dir, run_id)
        self.assertEqual((run.backup_dir / "demo" / "models" / "b.py").read_bytes(), self.before["models/b.py"])
        rollback(self.state_dir, run_id)
        self.assertEqual(_snapshot(self.module), self.before)

    def test_dry_run_plans_only_the_valid_file_and_writes_nothing(self):
        _run_id, state = self._run("dry_run", _fixer(BROKEN, "z = 3\n"))
        self.assertEqual(_snapshot(self.module), self.before)
        report = build_report(state, reports_from_state(state))
        self.assertEqual(report["modules"][0]["status"], PARTIAL_STATUS)
        self.assertEqual(report["summary"]["edits"]["planned"], 1)
        self.assertEqual(report["summary"]["edits"]["applied"], 0)
        self.assertEqual(report["summary"]["edits"]["rejected"], 1)
        self.assertEqual(report["summary"]["files_written"], 0)
        self.assertEqual(state["modules"][0]["report"]["planned_files"], [str(self.module / "models" / "b.py")])
        # a dry run that found a refused edit still fails the default gate, as a FAILED module would
        self.assertEqual(exit_code(report, ExitPolicy(), write_mode=False), 1)
        self.assertEqual(exit_code(report, ExitPolicy(fail_on="none"), write_mode=False), 0)

    def test_all_valid_module_is_unchanged_behaviour(self):
        run_id, state = self._run("fix", _fixer("x = 1\n# migrated\n", "z = 3\n"))
        after = _snapshot(self.module)
        self.assertEqual(after["models/a.py"], b"x = 1\n# migrated\n")
        self.assertEqual(after["models/b.py"], b"y = 2\nz = 3\n")
        report = build_report(state, reports_from_state(state))
        module = report["modules"][0]
        self.assertNotEqual(module["status"], PARTIAL_STATUS)
        self.assertNotIn("migration_status", state["modules"][0])
        self.assertEqual(report["summary"]["edits"]["rejected"], 0)
        self.assertEqual(report["summary"]["edits"]["applied"], 2)
        self.assertEqual(report["summary"]["files_written"], 2)
        self.assertFalse([f for f in module["findings"] if f["rule_id"] == "Fix Rejected"])


class StagedSalvageTests(unittest.TestCase):
    """Within one file: the whole-file transform is refused, the stages are re-run one at a time, and the output of
    the last VALID stage is kept (run_steps stops at the first refusal)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.module = _module(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self, legacy_output, knowledge_fixing):
        rules = {"17-18": _Rule("17-18.attrs", "17-18"), "18-19": _Rule("18-19.attrs", "18-19")}

        def rules_for_file(all_rules, path):
            return list(rules.values()) if path.endswith("a.py") else []

        fake = _fixer(legacy_output, "")
        with mock.patch.object(adapter, "fixer_for", side_effect=fake), \
                mock.patch.object(knowledge_rules, "rules_for_file", side_effect=rules_for_file), \
                mock.patch.object(knowledge_rules, "fixing_transform", side_effect=knowledge_fixing):
            registries = build_context().registries
            _report, edits = plan_module(self.module, 16, 17, registries, compute_edits=True,
                                         knowledge=list(rules.values()), knowledge_steps=["17-18", "18-19"])
        return {e.path.name: e for e in edits}

    def test_last_valid_stage_is_kept_when_a_later_stage_is_refused(self):
        def knowledge_fixing(rules, steps, log=None):
            if len(steps) > 1:  # the whole-file composite: refused, as the step after the legacy fixer is invalid
                return lambda p, t: BROKEN
            if steps[0] == "17-18":  # first knowledge step is valid
                return lambda p, t: t + "# 17\n"
            return lambda p, t: BROKEN  # second knowledge step is invalid

        edit = self._plan("x = 2\n", knowledge_fixing)["a.py"]
        self.assertTrue(edit.rejection.startswith("INVALID: "), edit.rejection)
        self.assertEqual(edit.fixed, "x = 2\n# 17\n")
        self.assertEqual(edit.validation.status, "VALID")
        self.assertNotIn("def broken", edit.fixed)

    def test_nothing_kept_when_the_first_stage_is_refused(self):
        def knowledge_fixing(rules, steps, log=None):
            return lambda p, t: BROKEN

        edit = self._plan(BROKEN, knowledge_fixing)["a.py"]
        self.assertTrue(edit.rejection.startswith("INVALID: "))
        self.assertEqual(edit.fixed, "x = 1\n")
        self.assertEqual(edit.dest, edit.path)


class _Rule:
    """Knowledge rule double: a FIX_ENABLED rule on one step; detection finds nothing."""

    def __init__(self, key, step):
        self.key, self.step, self.fixes, self.maturity = key, step, True, "FIX_ENABLED"
        self.experimental, self.review_required, self.depends = False, False, ()

    def detect(self, document):
        return []

    def applies_to(self, path):
        return path.endswith("a.py")


class ExitPolicyTests(unittest.TestCase):
    def test_partial_module_fails_the_gate_like_failed(self):
        report = {"modules": [{"status": PARTIAL_STATUS, "findings": []}],
                  "summary": {"edits": {"rejected": 0}}}
        self.assertEqual(exit_code(report, ExitPolicy(), write_mode=False), 1)
        self.assertEqual(exit_code(report, ExitPolicy(fail_on="none"), write_mode=False), 0)
        ok = {"modules": [{"status": "STATIC_VALIDATED", "findings": []}], "summary": {"edits": {"rejected": 0}}}
        self.assertEqual(exit_code(ok, ExitPolicy(), write_mode=False), 0)


if __name__ == "__main__":
    unittest.main()
