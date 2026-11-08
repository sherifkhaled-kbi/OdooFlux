"""TST-003-027 (REQ-ARC-004, REQ-TRF-001): adapter findings equal the legacy check_content output."""

import unittest
from pathlib import Path

from odooflux.core.engine.step_runner import detect
from odooflux.rules.shared.legacy_adapter import legacy_rules_for
from odooflux.rules.shared.legacy_rules import MigrationReport, _rules_for_file, check_content

from ._setup import REPO, SRC  # noqa: F401

FIXTURE = REPO / "tests" / "golden_fixtures" / "p0_kbi_demo_v14"


def _key(issue):
    return (issue.line, issue.category, issue.severity, issue.message)


class LegacyAdapterTests(unittest.TestCase):
    def test_every_golden_file_matches_legacy_output(self):
        checked = 0
        for file in sorted(FIXTURE.rglob("*")):
            if not file.is_file():
                continue
            text = file.read_text(encoding="utf-8")
            path = str(file)
            direct = MigrationReport(module_path="", from_version=14, to_version=19)
            rules = _rules_for_file(Path(path), to_version=19)
            if rules is not None:
                check_content(text, path, rules, 14, direct)
            via_adapter = detect(legacy_rules_for(path, 14, 19), path, text, [])
            self.assertEqual(sorted(map(_key, via_adapter)), sorted(map(_key, direct.issues)), path)
            checked += 1
        self.assertGreater(checked, 3)


if __name__ == "__main__":
    unittest.main()
