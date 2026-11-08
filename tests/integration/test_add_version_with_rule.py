"""TST-006-034 (REQ-VER-005, FR-016): add synthetic version 99.0 with one step rule and a fixture using data and
test files only, then run a migration. The test snapshots every ``src/odooflux/**/*.py`` file before and after and
requires them to be unchanged, so no engine or rule code is touched."""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.core.orchestrator.plan import build_plan
from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule
from odooflux.versions.graph.graph import VersionGraph
from odooflux.versions.registry.loader import load_version_data

SRC = KNOWLEDGE_ROOT.parents[1]
RULE_ID = "19-99.python.synthetic-keyword"
EVIDENCE_ID = "EV-990"


def source_digest() -> dict:
    return {str(p.relative_to(SRC)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(SRC.rglob("*.py"))}


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class AddVersionWithRuleTests(unittest.TestCase):
    def build_tree(self) -> Path:
        root = Path(tempfile.mkdtemp()) / "knowledge"
        shutil.copytree(KNOWLEDGE_ROOT, root, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
        versions = json.loads((root / "compatibility" / "versions.json").read_text(encoding="utf-8"))
        versions["versions"].append({"id": "99.0", "python_min": "3.10", "python_max": None,
                                     "online_releases": [], "support_status": "UNSUPPORTED"})
        versions["transitions"].append({"source": "19.0", "target": "99.0", "research_status": "RESEARCH_SEEDED"})
        write_json(root / "compatibility" / "versions.json", versions)
        evidence = json.loads((root / "evidence" / "EV-101.json").read_text(encoding="utf-8"))
        evidence.update(id=EVIDENCE_ID, description="Synthetic claim for the add-a-version proof",
                        rule_ids=[RULE_ID], status="UNVERIFIED")
        write_json(root / "evidence" / f"{EVIDENCE_ID}.json", evidence)
        research = json.loads((root / "compatibility" / "18-19.research.json").read_text(encoding="utf-8"))
        research.update(step="19-99", research_status="RESEARCH_SEEDED", open_gaps=[], peer_reviewed=False)
        write_json(root / "compatibility" / "19-99.research.json", research)
        write_json(root / "compatibility" / "19-99.rules.json", [{
            "id": RULE_ID, "step": "19-99", "category": "python_orm", "file_kinds": ["python"],
            "severity": "WARNING", "maturity": "FIX_ENABLED", "review_required": False, "ai_eligible": False,
            "risk": "LOW", "evidence": [EVIDENCE_ID], "depends_on": [], "conflicts_with": [],
            "detector_ref": "odooflux.rules.python.generic:keyword_in_call",
            "fixer_ref": "odooflux.rules.python.generic:rename_keyword",
            "params": {"callee": "synthetic_call", "keyword": "old_name", "new_keyword": "new_name"},
            "validation": ["python-syntax"],
            "tests": {"positive": "TST-006-034", "negative": "TST-006-034", "idempotence": "TST-006-034"},
            "message": "synthetic", "suggestion": "synthetic", "legacy_ref": None}])
        return root

    def test_synthetic_version_runs_a_migration_with_data_files_only(self):
        before = source_digest()
        root = self.build_tree()
        errors = [f for f in validate_knowledge(load_knowledge(root)) if f.severity == "ERROR"]
        self.assertEqual([f.line() for f in errors], [])

        versions, transitions = load_version_data(root / "compatibility" / "versions.json")
        plan = build_plan(VersionGraph(versions, transitions), "19.0", "99.0", [], allow_unverified=True)
        self.assertEqual(plan.status, "READY")
        self.assertEqual([s.id for s in plan.steps], ["19.0->99.0"])

        rules = [r for r in load_knowledge(root).rules if r["step"] == "19-99"]
        self.assertEqual([r["id"] for r in rules], [RULE_ID])
        bound = bind_rule(rules[0], BINDABLE_MODULES)
        fixture = Document.from_text("fixture/models/m.py", "synthetic_call(1, old_name=2)\nother(old_name=3)\n")
        result = apply_edits(fixture, bound.fix(fixture), precedence=[RULE_ID])
        self.assertEqual(result.text, "synthetic_call(1, new_name=2)\nother(old_name=3)\n")
        self.assertEqual(bound.fix(Document.from_text("fixture/models/m.py", result.text)), [])

        self.assertEqual(source_digest(), before)


if __name__ == "__main__":
    unittest.main()
