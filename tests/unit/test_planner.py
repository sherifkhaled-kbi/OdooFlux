"""TST-003-012 (REQ-VER-003): BLOCKED on unresearched steps; allow-unverified caps; range refusal."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.core.contracts.records import ModuleRef
from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.orchestrator.status import decide_status
from odooflux.versions.graph.graph import VersionGraph
from odooflux.versions.registry.loader import KNOWLEDGE_FILE, load_version_data


def _graph_with(research_for=None):
    data = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    for t in data["transitions"]:
        if research_for and (t["source"], t["target"]) == research_for:
            t["research_status"] = "NOT_ASSESSED"
    path = Path(tempfile.mkdtemp()) / "versions.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    versions, transitions = load_version_data(path)
    return VersionGraph(versions, transitions)


class PlannerTests(unittest.TestCase):
    def test_unresearched_step_blocks_and_is_named(self):
        plan = build_plan(_graph_with(("15.0", "16.0")), "14.0", "19.0", [])
        self.assertEqual(plan.status, "BLOCKED")
        self.assertEqual(plan.blocked_steps, ["15.0->16.0"])
        self.assertTrue(any("15.0->16.0" in r for r in plan.reasons))

    def test_allow_unverified_runs_and_caps_at_needs_review(self):
        plan = build_plan(_graph_with(("15.0", "16.0")), "14.0", "19.0", [], allow_unverified=True)
        self.assertEqual(plan.status, "READY")
        status, reasons = decide_status({1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS", 5: "PASS"},
                                        unverified=plan.allow_unverified, l5_coverage="full")
        self.assertEqual(status, "NEEDS_REVIEW")
        self.assertIn("unverified_plan", reasons)

    def test_source_below_registry_minimum_is_blocked_with_range(self):
        plan = build_plan(_graph_with(), "11.0", "19.0", [])
        self.assertEqual(plan.status, "BLOCKED")
        self.assertIn("12.0–19.0", plan.reasons[0])

    def test_plan_orders_modules_and_reports_cycles(self):
        modules = [ModuleRef("crm", "/x/crm", None, None, ("sale",)),
                   ModuleRef("sale", "/x/sale", None, None, ("base",)),
                   ModuleRef("loop1", "/x/l1", None, None, ("loop2",)),
                   ModuleRef("loop2", "/x/l2", None, None, ("loop1",))]
        plan = build_plan(_graph_with(), "14.0", "15.0", modules)
        self.assertEqual([m.name for m in plan.modules], ["sale", "crm"])
        self.assertEqual(plan.cycles, [["loop1", "loop2"]])
        self.assertEqual(plan.blocked_modules, ["loop1", "loop2"])
        self.assertEqual(plan.status, "READY")


if __name__ == "__main__":
    unittest.main()
