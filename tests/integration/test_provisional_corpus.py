"""PROVISIONAL validation corpus for the 17.0 -> 18.0 path (ADR-019; 006 T035-prov, T059-prov; 002 T020).

The expected tree and report under ``tests/golden_fixtures/17.0/kbi_demo/expected/18.0`` were produced by running the
current engine. They are NOT approved migration truth (certification: PENDING_HUMAN_REVIEW, FHR-A-002/FHR-A-003).
These tests check framework mechanics only: byte-exact reproducibility, idempotence, SC-005, input rejection, and that
the corpus can never be relabelled as approved without a test failing.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._support import fixtures
from tests._support.cli import run_legacy_cli
from tests.integration.helpers import normalised_report, start_run
from tests.integration.test_golden_migrations import GoldenCase, compare, tree_differences

ROOT = fixtures.FIXTURES_ROOT
SOURCE_DIR = ROOT / "17.0"
MODULE = SOURCE_DIR / "kbi_demo"
RULES = Path(__file__).resolve().parents[2] / "src" / "odooflux" / "knowledge" / "compatibility" / "17-18.rules.json"
MARKER = "PROVISIONAL.md"


def _case() -> GoldenCase:
    return GoldenCase("17.0", "18.0", MODULE, MODULE / "expected" / "18.0")


def marker_problems(root: Path = ROOT) -> list:
    """Reasons the provisional corpus under *root* is not clearly labelled PROVISIONAL (empty when it is)."""
    problems = []
    index = json.loads((root / "INDEX.json").read_text(encoding="utf-8"))
    if index.get("authority") != "PROVISIONAL":
        problems.append(f"INDEX.json authority is {index.get('authority')!r}, expected 'PROVISIONAL'")
    for item in index["fixtures"]:
        if item.get("targets") and item.get("authority") != "PROVISIONAL":
            problems.append(f"fixture {item['id']} has expected outputs but authority {item.get('authority')!r}")
    required = [root / "17.0", root / "17.0" / "kbi_demo" / "expected", root / "17.0" / "kbi_demo" / "expected" / "18.0"]
    for directory in required:
        marker = directory / MARKER
        if not marker.is_file():
            problems.append(f"missing {marker.relative_to(root)}")
            continue
        text = marker.read_text(encoding="utf-8")
        if "PROVISIONAL" not in text or "PENDING_HUMAN_REVIEW" not in text:
            problems.append(f"{marker.relative_to(root)} lacks the PROVISIONAL / PENDING_HUMAN_REVIEW labels")
        if "approved migration truth" in text.replace("NOT approved migration truth", "").replace(
                "Not approved migration truth", ""):
            problems.append(f"{marker.relative_to(root)} claims approval")
    return problems


def _detect_only_ids() -> set:
    return {r["id"] for r in json.loads(RULES.read_text(encoding="utf-8")) if r["maturity"] == "DETECT_ONLY"}


class ProvisionalCorpusTests(unittest.TestCase):
    def test_migration_output_matches_provisional_expected_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(compare(_case(), Path(tmp)), [])

    def test_provisional_run_is_labelled_in_the_report(self):
        """ADR-019 item 4: a run on the provisional corpus carries the PROVISIONAL label (set by the marker)."""
        expected = json.loads((_case().expected / "report.json").read_text(encoding="utf-8"))
        self.assertTrue(expected["provisional"]["active"])
        self.assertIn("PROVISIONAL", expected["provisional"]["labels"][0])

    def test_input_digest_matches_index(self):
        item = fixtures.entry("17.0/kbi_demo")
        self.assertEqual(fixtures.input_digest(item), item["input_digest"])

    def test_second_migration_of_output_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            module = work / "m" / "kbi_demo"
            shutil.copytree(_case().expected / "tree", module)
            before = {p.relative_to(module).as_posix(): p.read_bytes() for p in module.rglob("*") if p.is_file()}
            start_run(work / "state", [module], mode="fix", from_v=17, to_v=18)
            after = {p.relative_to(module).as_posix(): p.read_bytes() for p in module.rglob("*") if p.is_file()}
            self.assertEqual(before, after)

    def test_detect_only_rules_produce_no_edits(self):
        """SC-005: no finding of a DETECT_ONLY rule is FIXED, and their constructs survive byte-for-byte."""
        detect_only = _detect_only_ids()
        self.assertTrue(detect_only)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            module = fixtures.copy_fixture("17.0/kbi_demo", work / "in")
            run_id, _ = start_run(work / "state", [module], mode="fix", from_v=17, to_v=18)
            report = normalised_report(work / "state", run_id, roots=[work])
            for mod in report["modules"]:
                for finding in mod["findings"]:
                    if finding["rule_id"] in detect_only:
                        self.assertNotEqual(finding["status"], "FIXED", finding["rule_id"])
                edited_ids = {f["rule_id"] for f in mod["findings"] if f["status"] == "FIXED"}
                self.assertFalse(edited_ids & detect_only)
            for path, needle in (("models/demo.py", "def name_get"), ("models/demo.py", "_name_search"),
                                 ("models/demo.py", "user_has_groups"), ("models/demo.py", "mail.shortcode"),
                                 ("data/cron.xml", 'name="numbercall"'), ("views/demo_views.xml", "kanban-box"),
                                 ("static/src/js/demo.js", 'useService("rpc")'),
                                 ("security/ir.model.access.csv", "mail.model_mail_shortcode")):
                self.assertIn(needle, (module / path).read_text(encoding="utf-8"), f"{path}: {needle}")

    def test_unsupported_target_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = fixtures.copy_fixture("17.0/kbi_demo", tmp)
            done = run_legacy_cli(["migrate", "--module", module, "--from-version", "17.0", "--to-version", "99.0",
                                   "--state-dir", Path(tmp) / "state"])
        self.assertEqual(done.exit, 2)
        self.assertIn("99.0 is not in the registry", done.stderr + done.stdout)

    def test_two_step_plan_16_to_18_smoke(self):
        """Shape only (no byte-exact expectations): plan lists both steps; the report carries run, steps and modules."""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            module = fixtures.copy_fixture("17.0/kbi_demo", work / "in")
            run_id, state = start_run(work / "state", [module], mode="analyze", from_v=16, to_v=18)
            report = normalised_report(work / "state", run_id, roots=[work])
        self.assertEqual(report["run"]["steps"], ["16.0->17.0", "17.0->18.0"])
        self.assertEqual((report["run"]["source"], report["run"]["target"]), ("16.0", "18.0"))
        self.assertEqual(report["run"]["plan_status"], "READY")
        self.assertEqual(len(report["modules"]), 1)
        self.assertIn("status", report["modules"][0])
        self.assertIn("findings", report["modules"][0])


class ProvisionalMarkerTests(unittest.TestCase):
    def test_marker_and_authority_present(self):
        self.assertEqual(marker_problems(), [])

    def test_relabelling_as_approved_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "golden"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("p0_kbi_demo_v14", "knowledge", "rules",
                                                                      "runtime", "transformations", "tree"))
            index = json.loads((copy / "INDEX.json").read_text(encoding="utf-8"))
            index["authority"] = "APPROVED"
            (copy / "INDEX.json").write_text(json.dumps(index), encoding="utf-8")
            self.assertTrue(any("authority" in p for p in marker_problems(copy)))
            (copy / "17.0" / MARKER).unlink()
            self.assertTrue(any("missing" in p for p in marker_problems(copy)))

    def test_tree_differences_helper_still_detects_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "t"
            shutil.copytree(_case().expected / "tree", copy)
            (copy / "__manifest__.py").write_bytes(b"x")
            self.assertEqual(tree_differences(_case().expected / "tree", copy), ["content differs __manifest__.py"])


if __name__ == "__main__":
    unittest.main()
