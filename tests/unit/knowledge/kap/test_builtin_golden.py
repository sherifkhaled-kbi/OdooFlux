"""TST-011-001 (REQ-KAP-005): built-in knowledge behaviour stays byte-identical.

Golden values live in tests/fixtures/kap/golden/builtin_hashes.json and were recorded on main before any KAP change.
Any one-byte change in `knowledge validate` / `knowledge matrix --check` output, in loader counts, or in the reporting
golden model fails these tests.
"""

import contextlib
import hashlib
import io
import json
import unittest
from pathlib import Path

from odooflux.cli import knowledge as knowledge_cli
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge

from tests.unit.reporting.helpers import build

TESTS_DIR = Path(__file__).resolve().parents[3]
GOLDEN_PATH = TESTS_DIR / "fixtures" / "kap" / "golden" / "builtin_hashes.json"
REPORT_GOLDEN = TESTS_DIR / "golden_fixtures" / "reports" / "mixed.json"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _run_cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = knowledge_cli.main(argv)
    return rc, out.getvalue()


class BuiltinGoldenTests(unittest.TestCase):
    def test_validate_output_unchanged(self):
        rc, text = _run_cli(["validate"])
        expected = _golden()["validate"]
        self.assertEqual(rc, expected["rc"])
        self.assertEqual(len(text.encode("utf-8")), expected["stdout_bytes"])
        self.assertEqual(_sha(text), expected["stdout_sha256"])

    def test_matrix_check_unchanged(self):
        rc, text = _run_cli(["matrix", "--check"])
        expected = _golden()["matrix_check"]
        self.assertEqual(rc, expected["rc"])
        # The check prints the absolute path of the committed matrix; compare the path-independent suffix.
        normalised = text.replace(str(KNOWLEDGE_ROOT.parents[2]), "<REPO>")
        self.assertEqual(_sha(normalised), expected["stdout_sha256"])

    def test_loader_counts_unchanged(self):
        kb = load_knowledge(KNOWLEDGE_ROOT)
        counts = {
            "evidence": len(kb.evidence),
            "evidence_entries": len(kb.evidence_entries),
            "rules": len(kb.rules),
            "rule_candidates": len(kb.rule_candidates),
            "revisions": len(kb.revisions),
            "allow_list": len(kb.allow_list),
            "versions": len(kb.versions),
            "transitions": len(kb.transitions),
            "research": len(kb.research),
            "gaps": len(kb.gaps),
            "load_findings": len(kb.load_findings),
        }
        self.assertEqual(counts, _golden()["loader_counts"])

    def test_report_bytes_unchanged(self):
        text = json.dumps(build("mixed"), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
        expected = _golden()["report"]
        self.assertEqual(_sha(text), expected["model_sha256"])
        self.assertEqual(hashlib.sha256(REPORT_GOLDEN.read_bytes()).hexdigest(), expected["golden_file_sha256"])


if __name__ == "__main__":
    unittest.main()
