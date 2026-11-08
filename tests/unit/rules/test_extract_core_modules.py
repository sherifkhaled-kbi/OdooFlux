"""TST-006-002 (REQ-DEP-001): tools/extract_core_modules.py on a synthetic git repository, no network."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge import validator
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "extract_core_modules.py"


def _git(repo: Path, *args: str) -> str:
    cmd = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-C", str(repo), *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def _make_repo(root: Path, files) -> str:
    _git(root, "init", "-q")
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "synthetic core")
    return _git(root, "rev-parse", "HEAD")


SYNTHETIC_FILES = [
    "addons/base/__manifest__.py",
    "addons/account/__manifest__.py",
    "addons/web/__manifest__.py",
    "addons/no_manifest/readme.txt",
    "addons/web/static/src/nested/__manifest__.py",   # nested, must not count as a module
    "odoo/addons/base_import/__manifest__.py",
    "odoo/addons/zeta_tool/__manifest__.py",
    "odoo/models.py",
]


class ExtractCoreModulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls._tmp.name) / "odoo"
        cls.repo.mkdir()
        cls.sha = _make_repo(cls.repo, SYNTHETIC_FILES)
        cls.out = Path(cls._tmp.name) / "out"
        cls.out.mkdir()
        cls.core_path = cls.out / "18.0.json"
        cls.evidence_path = cls.out / "EV-300.json"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _run(self, *extra):
        import subprocess as sp
        cmd = ["python3", str(TOOL), "--repo", str(self.repo), "--sha", self.sha, "--version", "18.0",
               "--core-out", str(self.core_path), "--evidence-out", str(self.evidence_path),
               "--evidence-id", "EV-300", "--checked-on", "2026-11-07", *extra]
        return sp.run(cmd, check=True, capture_output=True, text=True)

    def test_lists_direct_manifest_modules_from_both_roots(self):
        self._run()
        data = json.loads(self.core_path.read_text(encoding="utf-8"))
        self.assertEqual(data["modules"], ["account", "base", "base_import", "web", "zeta_tool"])
        self.assertEqual(data["version"], "18.0")
        self.assertEqual(data["revision"], self.sha)
        self.assertEqual(data["evidence"], "EV-300")

    def test_output_is_sorted_and_deterministic(self):
        self._run()
        first = self.core_path.read_bytes()
        self._run()
        self.assertEqual(self.core_path.read_bytes(), first)
        modules = json.loads(first)["modules"]
        self.assertEqual(modules, sorted(modules))

    def test_evidence_record_matches_schema(self):
        self._run()
        record = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        schema = json.loads((KNOWLEDGE_ROOT / "schemas" / "evidence.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validator.check(record, schema), [])
        self.assertEqual(record["id"], "EV-300")
        self.assertEqual(record["revision"], self.sha)


if __name__ == "__main__":
    unittest.main()
