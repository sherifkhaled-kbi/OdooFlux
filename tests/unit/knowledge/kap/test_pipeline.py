"""TST-011-068 (REQ-KAP-029, REQ-KAP-030, REQ-KAP-045): the build orchestrator in `knowledge/pipeline.py`.

The steps here are stubs (`stub_steps`), so only the orchestration is under test: step order and stop rules, the dry-run
plan (no writes at all), resume with input-change invalidation, the destructive-change check that needs an explicit
supersede approval, and the audit entries written by a real (non-dry) run. No network, no sockets, no AI.
"""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge import pipeline as pl
from odooflux.knowledge.release.audit import verify_audit


def make_plan(**overrides) -> pl.BuildPlan:
    base = dict(label="unit-test", specs=[], pairs=[], base_tree=Path("/nonexistent-base"), adapters={},
                extract=None, known_detectors={}, created_at="2026-11-08T10:00:00Z", checked_on="2026-11-08",
                author="unit", tool_version="0.0.0-test", marker="m1")
    base.update(overrides)
    return pl.BuildPlan(**base)


def stub_steps(calls: list, *, fail_at=None, audit_at=None):
    """One stub per contract step. Each records its name in `calls`. Step 2 has a probe that reads `plan.marker`, which
    stands in for a changed snapshot digest; the fingerprint of the plan does not include `marker`."""
    steps = []
    for number, name in enumerate(pl.STEP_NAMES, start=1):
        def run(ctx, number=number, name=name):
            calls.append(name)
            if number == fail_at:
                raise pl.StepStop("STUB_FAILED", f"stub failure at {name}")
            if number == audit_at and ctx.audit is not None:
                ctx.audit.record("source_acquired", target="stub-source", outcome="ok",
                                 details={"note": "stub"})
            return {"stub": name}
        probe = (lambda ctx: {"marker": ctx.plan.marker}) if number == 2 else None
        steps.append(pl.Step(number, name, run, probe=probe))
    return steps


class PipelineOrchestration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "kb-home"

    def test_step_order_and_stop(self):
        calls = []
        result = pl.run_build(self.home, make_plan(), steps=stub_steps(calls, fail_at=4))
        self.assertEqual(calls, list(pl.STEP_NAMES[:4]), "steps run in contract order and stop at the failure")
        self.assertEqual(result.outcome, "STOPPED")
        self.assertEqual((result.stopped_at, result.code), (4, "STUB_FAILED"))
        steps_dir = self.home / "staging" / "unit-test" / "steps"
        self.assertTrue((steps_dir / "01-acquire.json").is_file())
        failed = json.loads((steps_dir / "04-classify.json").read_text(encoding="utf-8"))
        self.assertEqual(failed["status"], "FAILED")
        self.assertFalse((steps_dir / "05-evidence.json").exists(), "no result is recorded past a stop")

    def test_dry_run_plan(self):
        calls = []
        result = pl.run_build(self.home, make_plan(), steps=stub_steps(calls), dry_run=True)
        self.assertEqual(calls, [], "a dry run executes no step")
        self.assertEqual(result.outcome, "PLAN")
        self.assertEqual([row["name"] for row in result.rows], list(pl.STEP_NAMES))
        self.assertTrue(all(row["action"] == "RUN" for row in result.rows))
        self.assertFalse(self.home.exists(), "a dry run writes nothing, not even the kb-home layout")

    def test_resume_invalidates_changed_input(self):
        calls = []
        first = pl.run_build(self.home, make_plan(), steps=stub_steps(calls))
        self.assertEqual(first.outcome, "OK")
        self.assertEqual(calls, list(pl.STEP_NAMES))

        calls.clear()
        again = pl.run_build(self.home, make_plan(), steps=stub_steps(calls))
        self.assertEqual(calls, [], "unchanged inputs resume with every step reused")
        self.assertEqual(again.outcome, "OK")

        # A changed snapshot digest (the step 2 probe) invalidates step 2 and everything after it; step 1 is reused.
        calls.clear()
        pl.run_build(self.home, make_plan(marker="m2"), steps=stub_steps(calls))
        self.assertEqual(calls, list(pl.STEP_NAMES[1:]))

        # A changed pinned configuration (the plan fingerprint) invalidates every step.
        calls.clear()
        pl.run_build(self.home, make_plan(label="unit-test", checked_on="2026-11-09"), steps=stub_steps(calls))
        self.assertEqual(calls, list(pl.STEP_NAMES))

    def test_from_step_reruns_from_n_onwards(self):
        calls = []
        pl.run_build(self.home, make_plan(), steps=stub_steps(calls))
        calls.clear()
        pl.run_build(self.home, make_plan(), steps=stub_steps(calls), from_step=9)
        self.assertEqual(calls, list(pl.STEP_NAMES[8:]))

    def test_destructive_needs_supersede(self):
        entries = [
            {"kind": "record", "family": "rules", "id": "R-1", "change": "REMOVED", "destructive": True},
            {"kind": "record", "family": "evidence", "id": "EV-9", "change": "REMOVED", "destructive": True},
            {"kind": "record", "family": "rules", "id": "R-2", "change": "ADDED", "destructive": False},
        ]
        self.assertEqual(pl.destructive_unapproved(entries, ()), ["EV-9", "R-1"])
        self.assertEqual(pl.destructive_unapproved(entries, ("R-1",)), ["EV-9"])
        self.assertEqual(pl.destructive_unapproved(entries, ("R-1", "EV-9")), [])
        self.assertEqual(pl.destructive_unapproved([entries[2]], ()), [], "additions never need approval")

    def test_audit_entries_written(self):
        calls = []
        pl.run_build(self.home, make_plan(), steps=stub_steps(calls, audit_at=1))
        log = self.home / "audit.jsonl"
        self.assertTrue(log.is_file())
        actions = [json.loads(line)["action"] for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(actions, ["build_started", "source_acquired", "build_completed"])
        self.assertEqual(verify_audit(self.home), (True, ""))

    def test_failed_run_audited_as_completed_with_outcome(self):
        calls = []
        pl.run_build(self.home, make_plan(), steps=stub_steps(calls, fail_at=2))
        lines = [json.loads(x) for x in (self.home / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(lines[-1]["action"], "build_completed")
        self.assertEqual(lines[-1]["outcome"], "failed")
        self.assertEqual(lines[-1]["details"]["run_outcome"], "STOPPED")

    def test_secret_in_failure_message_is_masked(self):
        plan = make_plan(secrets=("hunter2-secret-value",))

        def leaky(ctx):
            raise pl.StepStop("STUB_FAILED", "token hunter2-secret-value leaked here")

        steps = stub_steps([])
        steps[0] = pl.Step(1, "acquire", leaky)
        result = pl.run_build(self.home, plan, steps=steps)
        self.assertNotIn("hunter2-secret-value", result.message)
        self.assertNotIn("hunter2-secret-value", (self.home / "staging" / "unit-test" / "steps"
                                                  / "01-acquire.json").read_text(encoding="utf-8"))

    def test_stage_tree_carries_every_parent_knowledge_dir(self):
        """TST-011-071 G (note 69): the staged release tree carries the parent's schemas/ too, so it is a complete
        knowledge tree, not only the directories the readers of the first build happened to need."""
        base = self.home.parent / "parent-tree"
        for name in ("evidence", "compatibility", "official_sources", "schemas"):
            (base / name).mkdir(parents=True)
            (base / name / "parent.json").write_text("{}", encoding="utf-8")
        (base / "gaps.json").write_text("[]", encoding="utf-8")
        self.assertIn("schemas", pl.DATA_DIRS)
        ctx = pl.Ctx(home=self.home, workdir=self.home / "staging" / "unit-test", plan=make_plan(base_tree=base),
                     allow_failed=False)
        pl._stage_tree(ctx)
        for name in (*pl.DATA_DIRS, *pl.DATA_FILES):
            self.assertTrue((ctx.tree() / name).exists(), f"the staged tree is missing {name}")
        self.assertTrue((ctx.tree() / "schemas" / "parent.json").is_file())


if __name__ == "__main__":
    unittest.main()
