"""TST-003-013 (REQ-VER-005): follow docs/guides/ADDING_A_VERSION.md with a synthetic version; no core edit."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.core.orchestrator.plan import build_plan
from odooflux.versions.graph.graph import VersionGraph
from odooflux.versions.registry.loader import KNOWLEDGE_FILE, load_version_data

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "guides" / "ADDING_A_VERSION.md"


class AddingVersionProcedureTests(unittest.TestCase):
    def test_guide_exists_and_names_the_three_data_steps(self):
        text = GUIDE.read_text(encoding="utf-8")
        for step in ("versions.json", "transitions", "fixtures"):
            self.assertIn(step, text)

    def test_procedure_adds_20_by_data_and_plans_it(self):
        tmp = Path(tempfile.mkdtemp())
        knowledge = tmp / "versions.json"
        shutil.copy(KNOWLEDGE_FILE, knowledge)
        data = json.loads(knowledge.read_text(encoding="utf-8"))
        data["versions"].append({"id": "20.0", "python_min": "3.10", "python_max": None,
                                 "online_releases": [], "support_status": "UNSUPPORTED"})
        data["transitions"].append({"source": "19.0", "target": "20.0", "research_status": "RESEARCH_SEEDED"})
        knowledge.write_text(json.dumps(data), encoding="utf-8")
        versions, transitions = load_version_data(knowledge)
        plan = build_plan(VersionGraph(versions, transitions), "19.0", "20.0", [])
        self.assertEqual(plan.status, "READY")
        self.assertEqual([s.id for s in plan.steps], ["19.0->20.0"])


if __name__ == "__main__":
    unittest.main()
