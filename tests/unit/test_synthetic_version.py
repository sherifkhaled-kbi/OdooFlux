"""TST-003-009 (REQ-VER-005): a version added as data plans without any code change."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.contracts.records import ModuleRef
from odooflux.versions.graph.graph import VersionGraph
from odooflux.versions.registry.loader import KNOWLEDGE_FILE, load_version_data

from ._setup import SRC  # noqa: F401


class SyntheticVersionTests(unittest.TestCase):
    def test_adding_20_as_data_plans_one_step(self):
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "versions.json"
        shutil.copy(KNOWLEDGE_FILE, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["versions"].append({"id": "20.0", "python_min": None, "python_max": None,
                                 "online_releases": [], "support_status": "UNSUPPORTED"})
        path.write_text(json.dumps(data), encoding="utf-8")
        versions, transitions = load_version_data(path)
        graph = VersionGraph(versions, transitions)
        steps = graph.steps("19.0", "20.0")
        self.assertEqual([s.id for s in steps], ["19.0->20.0"])
        self.assertEqual(steps[0].research_status, "NOT_ASSESSED")
        plan = build_plan(graph, "19.0", "20.0", [])
        self.assertEqual(plan.status, "BLOCKED")  # unresearched by default, as the spec requires
        self.assertEqual(build_plan(graph, "19.0", "20.0", [], allow_unverified=True).status, "READY")


if __name__ == "__main__":
    unittest.main()
