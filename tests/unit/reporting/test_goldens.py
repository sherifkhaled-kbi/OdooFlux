"""T001 (REQ-REP-001, REQ-REP-006): golden report models cover every status and optional section, and are
reproducible from the scenario states."""

import json
import unittest

from ._setup import SRC  # noqa: F401
from . import fixtures
from .helpers import GOLDEN_DIR, all_goldens, build

STATUSES = {"VERIFIED_SUCCESS", "INSTALL_VERIFIED", "STATIC_VALIDATED", "NEEDS_REVIEW", "FAILED", "BLOCKED"}


class GoldenTests(unittest.TestCase):
    def test_one_model_per_scenario_exists(self):
        self.assertEqual(sorted(p.stem for p in GOLDEN_DIR.glob("*.json")), sorted(fixtures.scenarios()))

    def test_every_status_covered(self):
        seen = {m["status"] for g in all_goldens().values() for m in g["modules"]}
        self.assertEqual(seen, STATUSES)

    def test_optional_sections_present_and_absent(self):
        goldens = all_goldens().values()
        mods = [m for g in goldens for m in g["modules"]]
        self.assertTrue(any("runtime" in m for m in mods) and any("runtime" not in m for m in mods))
        self.assertTrue(any("behavior" in m for m in mods) and any("behavior" not in m for m in mods))
        self.assertTrue(any(g["ai_usage"]["enabled"] for g in goldens))
        self.assertTrue(any(not g["ai_usage"]["enabled"] for g in goldens))
        self.assertTrue(any("provisional" in g for g in goldens) and any("provisional" not in g for g in goldens))
        for kind in ("fixed", "rejected", "needs_review", "open"):
            self.assertTrue(any(g["summary"]["findings_by_status"][kind] for g in goldens), kind)

    def test_goldens_reproducible_from_scenarios(self):
        for name, golden in all_goldens().items():
            self.assertEqual(golden, json.loads(json.dumps(build(name))), name)


if __name__ == "__main__":
    unittest.main()
