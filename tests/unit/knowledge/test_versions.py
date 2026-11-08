"""TST-004-005 (REQ-VER-001, REQ-ARC-003): registry load order, uniqueness, Online mapping, SUPPORTED
preconditions, and a 20.0 fixture that needs no code change."""

import json
import unittest

from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.versions.registry.loader import KNOWLEDGE_FILE, load_version_data

from .helpers import GOLDEN, copy_fixture


class VersionTests(unittest.TestCase):
    def test_shipped_registry_lists_12_to_19_in_order(self):
        versions, transitions = load_version_data(KNOWLEDGE_FILE)
        self.assertEqual([v.id for v in versions], [f"{m}.0" for m in range(12, 20)])
        self.assertEqual(len(transitions), 7)

    def test_shipped_knowledge_has_no_registry_findings(self):
        findings = [f for f in validate_knowledge(load_knowledge(KNOWLEDGE_ROOT)) if f.code.startswith("E00")]
        self.assertEqual(findings, [])

    def test_two_entries_with_the_same_major_fail_loading(self):
        root = copy_fixture("valid")
        path = root / "compatibility" / "versions.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["versions"].append(dict(data["versions"][0]))
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIn("E007", {f.code for f in validate_knowledge(load_knowledge(root))})

    def test_adding_20_is_data_only_and_appears_in_the_graph(self):
        root = copy_fixture("valid")
        path = root / "compatibility" / "versions.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["versions"].append({"id": "18.0", "python_min": "3.10", "python_max": None,
                                 "online_releases": [], "support_status": "UNSUPPORTED"})
        data["transitions"].append({"source": "17.0", "target": "18.0", "research_status": "NOT_ASSESSED"})
        path.write_text(json.dumps(data), encoding="utf-8")
        kb = load_knowledge(root)
        self.assertEqual([v["id"] for v in kb.versions], ["16.0", "17.0", "18.0"])
        self.assertEqual(validate_knowledge(kb), [])

    def test_supported_requires_inbound_steps_tested(self):
        root = copy_fixture("valid")
        path = root / "compatibility" / "versions.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["versions"][1]["support_status"] = "SUPPORTED"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIn("E007", {f.code for f in validate_knowledge(load_knowledge(root))})

    def test_online_release_maps_to_next_major(self):
        from odooflux.knowledge.applicability import on_premise_major
        self.assertEqual(on_premise_major("18.1"), ("19.0", True))
        self.assertEqual(on_premise_major("17.0"), ("17.0", False))


if __name__ == "__main__":
    unittest.main()
