"""TST-004-008 (REQ-EVD-005, SC-004): refresh classifies unchanged, moved, missing, and unavailable
against two local git repositories; --apply demotes missing records; dry-run leaves git clean."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.loader import load_knowledge
from odooflux.knowledge.refresh import apply_report, refresh

from .helpers import git


def _commit(repo: Path, files: dict, message: str) -> str:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def _record(id_, path, line, match, sha, kind="present", search_scope=None):
    loc = {"branch": "17.0", "revision": sha, "path": path, "line": line, "match": match, "kind": kind}
    if search_scope:
        loc["search_scope"] = search_scope
    return {"id": id_, "rule_ids": [], "category": "orm",
            "source_applicability": {"from": "16.0", "to": "16.0"}, "target_applicability": {"from": "17.0", "to": None},
            "description": f"fixture {id_}", "url": f"https://github.com/odoo/odoo/blob/{sha}/{path}",
            "repository": "odoo/odoo", "revision": sha, "locations": [loc], "detection_method": "grep",
            "proposed_transformation": "review-only", "risk": "LOW", "required_validation": ["static.rescan"],
            "status": "DOCUMENTED_NOT_TESTED", "checked_on": "2026-11-06", "checked_by": "fixture"}


class RefreshTests(unittest.TestCase):
    """Fixture history: old (match at line 1 of models.py, gone.py exists), new (match moved to
    line 13), gone (gone.py deleted). The unavailable case uses an all-zero revision."""

    @classmethod
    def setUpClass(cls):
        cls.clone = Path(tempfile.mkdtemp()) / "odoo"
        cls.clone.mkdir()
        git(cls.clone, "init", "-q")
        old_models = ["def name_get(self):\n"] + [f"line {n}\n" for n in range(2, 40)]
        cls.old = _commit(cls.clone, {"odoo/models.py": "".join(old_models),
                                      "odoo/gone.py": "def vanished(self):\n"}, "old")
        new_models = ["\n"] * 12 + old_models
        cls.new = _commit(cls.clone, {"odoo/models.py": "".join(new_models)}, "new")
        git(cls.clone, "rm", "-q", "odoo/gone.py")
        cls.gone_rev = _commit(cls.clone, {}, "delete gone.py")

    def _kb(self, records):
        root = Path(tempfile.mkdtemp())
        shutil.copytree(Path(__file__).resolve().parents[3] / "tests/golden_fixtures/knowledge/valid", root / "kb")
        kb_root = root / "kb"
        for f in (kb_root / "evidence").glob("*.json"):
            f.unlink()
        for rec in records:
            (kb_root / "evidence" / f"{rec['id']}.json").write_text(json.dumps(rec), encoding="utf-8")
        return load_knowledge(kb_root)

    def test_four_cases_are_classified(self):
        records = [
            _record("EV-101", "odoo/models.py", 1, "def name_get(", self.old),       # unchanged at old
            _record("EV-102", "odoo/models.py", 1, "def name_get(", self.new),       # moved 1 -> 13
            _record("EV-103", "odoo/gone.py", 1, "def vanished(", self.gone_rev),    # missing: deleted
            _record("EV-104", "odoo/models.py", 1, "def name_get(", "0" * 40),       # unavailable revision
        ]
        kb = self._kb(records)
        report = refresh(kb, {"odoo/odoo": self.clone}, {})
        result = {r["id"]: r["result"] for r in report["results"]}
        self.assertEqual(result["EV-101"], "unchanged")
        self.assertEqual(result["EV-102"], "moved")
        self.assertEqual(result["EV-103"], "missing")
        self.assertEqual(result["EV-104"], "unavailable")
        moved = [r for r in report["results"] if r["id"] == "EV-102"][0]
        self.assertEqual(moved["new_line"], 13)

    def test_dry_run_leaves_the_tree_untouched(self):
        kb = self._kb([_record("EV-103", "odoo/gone.py", 1, "def vanished(", self.gone_rev)])
        before = (kb.root / "evidence" / "EV-103.json").read_text(encoding="utf-8")
        refresh(kb, {"odoo/odoo": self.clone}, {})
        self.assertEqual((kb.root / "evidence" / "EV-103.json").read_text(encoding="utf-8"), before)

    def test_apply_demotes_missing_and_updates_moved(self):
        kb = self._kb([_record("EV-102", "odoo/models.py", 1, "def name_get(", self.new),
                       _record("EV-103", "odoo/gone.py", 1, "def vanished(", self.gone_rev)])
        report = refresh(kb, {"odoo/odoo": self.clone}, {})
        apply_report(kb, report, today="2026-11-07")
        moved = json.loads((kb.root / "evidence" / "EV-102.json").read_text(encoding="utf-8"))
        gone = json.loads((kb.root / "evidence" / "EV-103.json").read_text(encoding="utf-8"))
        self.assertEqual(moved["locations"][0]["line"], 13)
        self.assertEqual(gone["status"], "CONFLICTING")
        self.assertEqual(moved["checked_on"], "2026-11-07")


if __name__ == "__main__":
    unittest.main()
