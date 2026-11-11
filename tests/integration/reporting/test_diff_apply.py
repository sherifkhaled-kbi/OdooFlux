"""TST-009-009 (REQ-REP-004, SC-003): the exported diff applies with ``patch -p1`` from the modules' parent and
reproduces the promoted output byte for byte, including CRLF files, files without a final newline, and the
__openerp__.py -> __manifest__.py rename."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.unit.reporting import _setup  # noqa: F401
from tests.integration.helpers import FIXTURE, start_run  # noqa: E402

HAVE_PATCH = shutil.which("patch") is not None


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _variant(dest: Path, kind: str) -> Path:
    shutil.copytree(FIXTURE, dest)
    for p in dest.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".xml", ".csv"):
            data = p.read_bytes()
            if kind == "crlf":
                p.write_bytes(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            elif kind == "nofinal":
                p.write_bytes(data.rstrip(b"\r\n"))
    return dest


def _export(state_dir: Path, run_id: str, state: dict):
    from odooflux.core.jobs.state_dir import RunDir
    from odooflux.core.orchestrator.run import reports_from_state
    from odooflux.reporting.exporters.diff import backup_reader, export_diff
    from odooflux.reporting.model.model import build_report
    run = RunDir.open(state_dir, run_id)
    model = build_report(state, reports_from_state(state), run_log_path="")
    return model, export_diff(model, backup_reader(run.backup_dir))


class DiffApplyTests(unittest.TestCase):
    def _case(self, kind: str):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        work, pristine = tmp / "work", tmp / "pristine"
        for root in (work, pristine):
            root.mkdir()
            _variant(root / "kbi_demo", kind)
        run_id, state = start_run(tmp / "state", [work / "kbi_demo"], mode="fix")
        self.assertNotEqual(_tree(work), _tree(pristine), "fixture must change in write mode")
        model, result = _export(tmp / "state", run_id, state)
        self.assertTrue(result.patch.strip(), "patch must not be empty")
        patch_file = tmp / "out.patch"
        patch_file.write_bytes(result.patch.encode("utf-8"))
        proc = subprocess.run(["patch", "-p1", "-d", str(pristine), "-i", str(patch_file), "--no-backup-if-mismatch"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(_tree(pristine), _tree(work))
        return result

    @unittest.skipUnless(HAVE_PATCH, "patch(1) not available")
    def test_lf_fixture(self):
        result = self._case("lf")
        self.assertIn("--- a/kbi_demo/", result.patch)
        self.assertIn("+++ b/kbi_demo/", result.patch)

    @unittest.skipUnless(HAVE_PATCH, "patch(1) not available")
    def test_crlf_fixture(self):
        self.assertIn("\r\n", self._case("crlf").patch)

    @unittest.skipUnless(HAVE_PATCH, "patch(1) not available")
    def test_no_final_newline_fixture(self):
        self.assertIn("\\ No newline at end of file", self._case("nofinal").patch)

    @unittest.skipUnless(HAVE_PATCH, "patch(1) not available")
    def test_rename_is_delete_plus_create(self):
        result = self._case("lf")
        self.assertIn("--- a/kbi_demo/__openerp__.py", result.patch)
        self.assertIn("+++ /dev/null", result.patch)
        self.assertIn("--- /dev/null", result.patch)
        self.assertIn("+++ b/kbi_demo/__manifest__.py", result.patch)

    @unittest.skipUnless(HAVE_PATCH, "patch(1) not available")
    def test_index_maps_hunks_to_edits_and_rules(self):
        index = self._case("lf").index
        self.assertTrue(index["files"])
        hunks = [h for f in index["files"] for h in f["hunks"]]
        self.assertTrue(hunks)
        for h in hunks:
            self.assertRegex(h["header"], r"^@@ -\d+(,\d+)? \+\d+(,\d+)? @@")
            self.assertTrue(all(e.startswith("e-") for e in h["edit_ids"]))
        self.assertTrue(any(h["rule_ids"] for h in hunks))
        json.dumps(index)  # serialisable

    @unittest.skipUnless(HAVE_PATCH, "patch(1) not available")
    def test_every_corpus_fixture_round_trips(self):
        """Every <source>/<module>/expected/<target> fixture in the golden corpus (provisional or not)."""
        golden = Path(__file__).resolve().parents[2] / "golden_fixtures"
        cases = [(m, t) for src in sorted(golden.glob("[0-9]*.0")) for m in sorted(src.iterdir())
                 if m.is_dir() for t in sorted((m / "expected").glob("[0-9]*.0"))]
        for module, target in cases:
            with self.subTest(f"{module.parent.name}/{module.name}->{target.name}"):
                tmp = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
                for root in ("work", "pristine"):
                    shutil.copytree(module, tmp / root / module.name, ignore=shutil.ignore_patterns("expected"))
                run_id, state = start_run(tmp / "state", [tmp / "work" / module.name], mode="fix",
                                          from_v=int(module.parent.name.split(".")[0]),
                                          to_v=int(target.name.split(".")[0]))
                _, result = _export(tmp / "state", run_id, state)
                (tmp / "out.patch").write_bytes(result.patch.encode("utf-8"))
                if result.patch:
                    proc = subprocess.run(["patch", "-p1", "-d", str(tmp / "pristine"), "-i", str(tmp / "out.patch"),
                                           "--no-backup-if-mismatch"], capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(_tree(tmp / "pristine"), _tree(tmp / "work"))

    def test_rejected_module_exports_its_accepted_edit(self):
        """PA-3 cleanup: a module with refused edits is partial; its accepted edit is exported (refused files are not:
        tests/unit/reporting/test_column_and_dry_run.py covers the refused file)."""
        from odooflux.reporting.exporters.diff import export_diff
        from tests.unit.reporting.helpers import golden
        model = golden("failed")
        model["modules"][0]["edits"] = [{"path": "/work/kbi_stock_custom/models/stock.py",
                                         "dest": "/work/kbi_stock_custom/models/stock.py",
                                         "spans": [{"start": 0, "end": 1, "before": "a", "after": "b"}]}]
        result = export_diff(model, lambda module, path: b"a\n")
        self.assertIn("a/kbi_stock_custom/models/stock.py", result.patch)
        self.assertEqual(result.index["excluded_modules"], [])

    def test_missing_original_is_an_error_not_a_guess(self):
        from odooflux.reporting.exporters.diff import OriginalUnavailableError, export_diff
        from tests.unit.reporting.helpers import golden
        model = golden("static_validated")
        self.assertTrue(model["modules"][0]["edits"])

        def missing(module, path):
            raise FileNotFoundError(path)
        with self.assertRaises(OriginalUnavailableError):
            export_diff(model, missing)

    def test_dry_run_state_without_planned_edits_gives_empty_patch(self):
        from odooflux.reporting.exporters.diff import export_diff
        from tests.unit.reporting.helpers import golden
        model = golden("needs_review")
        self.assertEqual(model["modules"][0]["edits"], [])
        result = export_diff(model, lambda m, p: b"")
        self.assertEqual(result.patch, "")
        self.assertEqual(result.index["files"], [])


if __name__ == "__main__":
    unittest.main()
