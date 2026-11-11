"""AC-18: `odooflux versions` shows the declared support policy and research maturity unchanged, and adds the executable
fix-rule count per step without promoting any status."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPAT = REPO / "src" / "odooflux" / "knowledge" / "compatibility"


def _cli(*args):
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "PYTHONPATH": str(REPO / "src"), "ODOOFLUX_KB_HOME": tmp, "XDG_CACHE_HOME": tmp}
        return subprocess.run([sys.executable, "-m", "odooflux", *args], cwd=tmp, env=env, capture_output=True,
                              text=True, timeout=120).stdout


class VersionsOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _cli("versions")

    def test_support_column_matches_the_registry_data(self):
        for entry in json.loads((COMPAT / "versions.json").read_text(encoding="utf-8"))["versions"]:
            self.assertRegex(self.out, rf"(?m)^{re.escape(entry['id'])}\s+\S+\s+{entry['support_status']}\s*$")

    def test_no_version_is_promoted_beyond_the_declared_policy(self):
        declared = {e["support_status"] for e in
                    json.loads((COMPAT / "versions.json").read_text(encoding="utf-8"))["versions"]}
        for status in ("SUPPORTED", "EXPERIMENTAL"):
            if status not in declared:
                self.assertNotRegex(self.out, rf"(?m)^\d+\.0\s+\S+\s+{status}")

    def test_research_column_matches_the_step_records(self):
        for path in sorted(COMPAT.glob("*-*.research.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if not re.fullmatch(r"\d+-\d+", record["step"]):
                continue
            a, b = record["step"].split("-")
            row = re.search(rf"(?m)^{a}\.0->{b}\.0\s+(\S+)", self.out)
            if row:
                self.assertEqual(row.group(1), record["research_status"], path.name)

    def test_fix_rule_counts_agree_with_knowledge_status(self):
        total = sum(int(m) for m in re.findall(r"(?m)^\d+\.0->\d+\.0\s+\S+\s+(\d+)\s*$", self.out))
        status = _cli("knowledge", "status")
        self.assertIn(f"fix-enabled rules: {total}", status)

    def test_legend_separates_policy_research_and_capability(self):
        self.assertIn("Neither is a statement about what `migrate --fix` can edit", self.out)


if __name__ == "__main__":
    unittest.main()
