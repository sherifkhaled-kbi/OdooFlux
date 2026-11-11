"""TST-011-082 (REQ-KAP-037, REQ-KAP-041, REQ-KAP-042, REQ-KAP-038; contracts/migration-integration.md): transition
coverage of `migrate` against the active knowledge release, and the `--kb-home` / `--require-complete-kb` options.

Each test runs the real `migrate` command in analyze mode (no writes to the module) against a synthetic release built
with the existing manifest and store helpers. The built-in case uses an empty kb-home so the environment never leaks in.
"""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.builtins import default_context
from odooflux.cli.main import run
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.builtin import builtin_digest
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import ReleaseState
from odooflux.knowledge.release.store import KbLock, build_pointer, ensure_layout, set_release_state, utc_now, \
    write_active

GOLDEN = Path(__file__).resolve().parents[3] / "golden_fixtures" / "17.0" / "kbi_demo"
NOT_COVERED = "KAP_TRANSITION_NOT_COVERED"
PARTIAL = "KAP_TRANSITION_PARTIAL"
STEP = "17-18"  # release step key; the plan step id is 17.0->18.0


def normalise_rules(compat: Path) -> None:
    """Synthetic releases carry DETECT_ONLY rules only (REQ-KAP-039 fixtures): FIX_ENABLED rows become DETECT_ONLY."""
    for path in sorted(compat.glob("*.rules.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            if row.get("maturity") == "FIX_ENABLED":
                row["maturity"] = "DETECT_ONLY"
                row["fixer_ref"] = None
        path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def build_release(base: Path, steps: list, completeness: str = "COMPLETE") -> tuple:
    """Install a synthetic active release under base/kb-home. Returns (home, release_id, digest, release_dir)."""
    home = base / "kb-home"
    ensure_layout(home)
    tree = base / "tree"
    shutil.copytree(KNOWLEDGE_ROOT / "compatibility", tree / "knowledge" / "compatibility")
    normalise_rules(tree / "knowledge" / "compatibility")
    meta = {
        "label": "coverage-test", "parent_release": None,
        "framework": {"built_with": "0.0.0-test", "min_framework": "0.0.0", "max_framework": None},
        "schema_versions": {"rule": 1}, "sources": [], "steps_covered": steps,
        "coverage_manifest_digest": "cd" * 32, "completeness": completeness,
        "build": {"tool_version": "0.0.0-test", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
    }
    manifest = write_release_manifest(tree, meta)
    rid = manifest["release_id"]
    release_dir = home / "releases" / rid
    tree.rename(release_dir)
    set_release_state(home, rid, ReleaseState.ACTIVE)
    with KbLock(home):
        write_active(home, build_pointer(None, rid, manifest["release_digest"], utc_now()))
    return home, rid, manifest["release_digest"], release_dir


def make_module(base: Path) -> Path:
    """A clean one-file 17.0 module: no XML, so no view rules fire and the static status is not decided by findings."""
    module = base / "addons" / "kbi_cov"
    (module / "models").mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        "{'name': 'KBI Cov', 'version': '17.0.1.0.0', 'depends': ['base'], 'installable': True}\n", encoding="utf-8")
    (module / "models" / "__init__.py").write_text("", encoding="utf-8")
    (module / "models" / "x.py").write_text("X = 1\n", encoding="utf-8")
    return module


def migrate(base: Path, home: Path, module: Path, extra=(), report_name="report.json") -> tuple:
    """Run the real migrate command (analyze mode). Returns (exit code, report dict or None, stdout, stderr)."""
    report = base / report_name
    argv = ["migrate", "--from-version", "17", "--to-version", "18", "--module", str(module),
            "--state-dir", str(base / "state"), "--report", str(report), "--report-format", "json",
            "--kb-home", str(home), *extra]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run(argv, default_context())  # the same entry as the console script (builtins.main)
    data = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
    return code, data, out.getvalue(), err.getvalue()


def diff_paths(a, b, path=()) -> list:
    """Key paths (tuples) at which two JSON values differ; a key present on one side only is a difference."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                out.append(path + (key,))
            else:
                out += diff_paths(a[key], b[key], path + (key,))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for index, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, path + (index,))
        return out
    return [] if a == b else [path]


def _lookup(obj, path):
    for key in path:
        obj = obj[key]
    return obj


def _is_af1_addition(path) -> bool:
    """A key path AF-1 (default execution) may add to a report: summary.experimental, or fix_class on a module's
    finding or edit (modules[i].findings[j].fix_class / modules[i].edits[j].fix_class)."""
    if path == ("summary", "experimental"):
        return True
    return (len(path) == 5 and path[0] == "modules" and path[2] in ("findings", "edits")
            and path[4] == "fix_class")


class MigrateCoverageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.module = make_module(self.base)
        self.empty_home = self.base / "no-release"

    def tearDown(self):
        self._tmp.cleanup()

    def _status(self, report: dict) -> str:
        return report["modules"][0]["status"]

    def test_not_covered_warns_and_not_verified(self):
        """A release that does not cover 17-18 warns, the report carries the release, and the module is not verified."""
        home, rid, digest, _ = build_release(self.base, steps=[{"step": "16-17", "completeness": "COMPLETE"}])
        code, report, out, _ = migrate(self.base, home, self.module)
        self.assertEqual(code, 0)
        self.assertTrue(any(w.startswith(NOT_COVERED) and STEP in w for w in report["warnings"]), report["warnings"])
        self.assertIn(f"knowledge not available for step {STEP}", " ".join(report["warnings"]))
        self.assertNotEqual(self._status(report), "VERIFIED_SUCCESS")
        self.assertEqual(self._status(report), "NEEDS_REVIEW")
        self.assertIn("unverified_plan", report["modules"][0]["status_reasons"])
        self.assertEqual(report["knowledge_release"]["release_id"], rid)
        self.assertEqual(report["knowledge_release"]["digest"], digest)
        self.assertFalse(report["knowledge_release"]["builtin"])
        self.assertEqual(report["schema_version"], "1.1.0")
        self.assertIn(f"knowledge not available for step {STEP}", out)

    def test_partial_warns(self):
        """A PARTIAL step warns; the status is the same as the built-in run (partial is a warning, not a cap)."""
        home, _rid, _digest, _ = build_release(self.base, steps=[{"step": STEP, "completeness": "PARTIAL"}],
                                               completeness="PARTIAL")
        code, report, _out, _ = migrate(self.base, home, self.module)
        self.assertEqual(code, 0)
        self.assertTrue(any(w.startswith(PARTIAL) and STEP in w for w in report["warnings"]), report["warnings"])
        self.assertFalse(any(w.startswith(NOT_COVERED) for w in report["warnings"]))
        _code, builtin_report, _o, _e = migrate(self.base, self.empty_home, self.module, report_name="builtin.json")
        self.assertEqual(self._status(report), self._status(builtin_report))

    def test_builtin_no_new_warnings(self):
        """No active release: no KAP warnings, and the report records the built-in release with its computed digest."""
        code, report, _out, _err = migrate(self.base, self.empty_home, self.module)
        self.assertEqual(code, 0)
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["knowledge_release"]["release_id"], "builtin")
        self.assertTrue(report["knowledge_release"]["builtin"])
        self.assertEqual(report["knowledge_release"]["digest"], builtin_digest())
        self.assertEqual(report["schema_version"], "1.1.0")

    def test_corrupt_release_fails_closed(self):
        """A release whose bytes no longer match its manifest exits 4 with no report and no built-in fallback."""
        home, _rid, _digest, release_dir = build_release(self.base, steps=[{"step": STEP, "completeness": "COMPLETE"}])
        versions = release_dir / "knowledge" / "compatibility" / "versions.json"
        versions.write_text(versions.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        code, report, _out, err = migrate(self.base, home, self.module)
        self.assertEqual(code, 4)
        self.assertIsNone(report)
        self.assertIn("ERROR: knowledge release", err)

    def test_report_differs_from_golden_only_in_schema_and_release(self):
        """Owner requirement 3: a real `migrate --fix` report equals the golden expected report except for
        schema_version and the knowledge_release block (normalised exactly as tests/integration/helpers does)."""
        work = self.base / "golden"
        module = work / "module" / "kbi_demo"  # the golden harness layout, so paths normalise identically
        shutil.copytree(GOLDEN, module, ignore=shutil.ignore_patterns("expected"))
        shutil.copy(GOLDEN.parent / "PROVISIONAL.md", module.parent / "PROVISIONAL.md")  # the ancestor marker (ADR-019)
        out = work / "report.json"
        argv = ["migrate", "--from-version", "17", "--to-version", "18", "--module", str(module),
                "--state-dir", str(work / "state"), "--fix", "--report", str(out),
                "--report-format", "json", "--kb-home", str(self.empty_home)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run(argv, default_context())
        text = out.read_text(encoding="utf-8").replace(str(work), "<ROOT>")
        actual = json.loads(text)
        for key in ("run_id", "rollback_cmd", "run_log"):
            actual["run"].pop(key, None)
            actual["recovery"].pop(key, None)
        actual["run"].pop("run_id", None)
        expected = json.loads((GOLDEN / "expected" / "18.0" / "report.json").read_text(encoding="utf-8"))
        diffs = diff_paths(expected, actual)
        # AF-1 default execution adds exactly two kinds of key: fix_class on a finding or edit, and
        # summary.experimental. Each must be a pure addition (absent from the golden); anything else still fails.
        af1_added = [p for p in diffs if _is_af1_addition(p)]
        for path in af1_added:
            self.assertNotIn(path[-1], _lookup(expected, path[:-1]), path)
        unexpected = [p for p in diffs if p not in af1_added]
        self.assertEqual(sorted(unexpected), [("knowledge_release",), ("schema_version",)], unexpected)
        self.assertIn(("summary", "experimental"), af1_added)
        self.assertTrue(all(_lookup(actual, p) in ("certified", "experimental", "legacy")
                            for p in af1_added if p[-1] == "fix_class"))
        self.assertEqual(actual["schema_version"], "1.1.0")
        self.assertTrue(actual["knowledge_release"]["builtin"])

    def test_require_complete_kb_refuses_partial(self):
        """--require-complete-kb refuses a PARTIAL release with the existing blocked exit code (4)."""
        home, _rid, _digest, _ = build_release(self.base, steps=[{"step": STEP, "completeness": "PARTIAL"}],
                                               completeness="PARTIAL")
        code, report, _out, err = migrate(self.base, home, self.module, extra=["--require-complete-kb"])
        self.assertEqual(code, 4)
        self.assertIsNone(report)
        self.assertIn("not COMPLETE", err)


if __name__ == "__main__":
    unittest.main()
