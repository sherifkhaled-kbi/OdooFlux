"""TST-011-017 (REQ-KAP-026, REQ-KAP-025, REQ-KAP-045): `knowledge release` CLI group and activation boundaries.

Contract: cli-surface (release group, exit codes 0/1/2/5), release-lifecycle ("Activation (atomic)", "Rollback",
"Removal", "Audit actions"). Fixture trees are built from the shipped knowledge tree with DETECT_ONLY rules only, so the
module does not depend on promotion gates. Everything runs offline; the socket layer is patched to raise.
"""

import io
import json
import os
import shutil
import socket
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from odooflux.cli.knowledge import main as knowledge_main
from odooflux.cli.kap_common import EXIT_INTEGRITY, EXIT_OK, EXIT_USAGE, EXIT_VALIDATION
from odooflux.cli import kap_release
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.audit import verify_audit
from odooflux.knowledge.release.canonical import canonical_bytes
from odooflux.knowledge.release.manifest import require_intact, write_release_manifest
from odooflux.knowledge.release.model import ReleaseState
from odooflux.knowledge.release.store import ACTIVE_NAME, ensure_layout, read_active, set_release_state

META = {
    "label": "community-17.0-18.0-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}
RULE = {
    "id": "12-13.python.probe", "step": "12-13", "category": "python_orm", "maturity": "DETECT_ONLY",
    "risk": "LOW", "evidence": ["EV-101"], "detector_ref": "odooflux.rules.python.generic:flag_decorator",
    "fixer_ref": "odooflux.rules.python.generic:remove_decorator",
    "tests": {"positive": "T1", "negative": "T2", "idempotence": "T3"}, "review_required": False,
    "severity": "CRITICAL", "message": "m", "suggestion": "s", "file_kinds": ["python"], "ai_eligible": False,
    "conflicts_with": [], "depends_on": [], "legacy_ref": None, "params": {},
}


def _tree(root: Path, *, coverage: bytes = b'{"items": []}\n', rules=None) -> Path:
    """A complete release tree (not yet installed). `rules=None` ships the one DETECT_ONLY rule."""
    shutil.copytree(KNOWLEDGE_ROOT / "official_sources", root / "knowledge" / "official_sources")
    evidence = json.loads((KNOWLEDGE_ROOT / "evidence" / "EV-101.json").read_text(encoding="utf-8"))
    evidence["status"] = "UNVERIFIED"
    rule_list = [RULE] if rules is None else rules
    files = {
        "knowledge/evidence/EV-101.json": json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        "knowledge/compatibility/versions.json": json.dumps({"versions": [], "transitions": []}) + "\n",
        "knowledge/compatibility/12-13.rules.json": json.dumps(rule_list, indent=2, sort_keys=True) + "\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    (root / "coverage").mkdir(exist_ok=True)
    (root / "coverage" / "coverage-manifest.json").write_bytes(coverage)
    (root / "provenance").mkdir(exist_ok=True)
    (root / "provenance" / "sources.json").write_text('{"sources": []}\n', encoding="utf-8")
    write_release_manifest(root, META)
    return root


def _install(home: Path, tree: Path) -> str:
    """Install a built tree into kb-home as INSTALLED (the state import would leave it in)."""
    release_id = json.loads((tree / "release.json").read_text(encoding="utf-8"))["release_id"]
    dest = home / "releases" / release_id
    if not dest.exists():
        shutil.copytree(tree, dest)
    set_release_state(home, release_id, ReleaseState.INSTALLED)
    return release_id


def _snapshot(home: Path) -> dict:
    out = {}
    for path in sorted(home.rglob("*")):
        rel = path.relative_to(home).as_posix()
        out[rel] = None if path.is_dir() else path.read_bytes()
    return out


class _Offline(unittest.TestCase):
    """Every test in this module runs with the socket layer patched to raise."""

    def setUp(self):
        self._net = mock.patch.object(socket, "socket", side_effect=OSError("network disabled in KAP tests"))
        self._net.start()
        self.addCleanup(self._net.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "kb"
        ensure_layout(self.home)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = knowledge_main(["release", *argv, "--kb-home", str(self.home)])
        return code, out.getvalue(), err.getvalue()


class TestReleaseCli(_Offline):
    def setUp(self):
        super().setUp()
        self.r1 = _install(self.home, _tree(self.tmp / "t1"))
        self.r2 = _install(self.home, _tree(self.tmp / "t2", coverage=b'{"items": [1]}\n'))
        self.r3 = _install(self.home, _tree(self.tmp / "t3", coverage=b'{"items": [2]}\n'))

    def test_list_show_and_json_are_canonical(self):
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, EXIT_OK)
        for rid in (self.r1, self.r2, self.r3):
            self.assertIn(rid, out)
        code, out, _ = self.run_cli("list", "--json")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(out.encode("utf-8"), canonical_bytes(json.loads(out)) + b"\n")
        code, out, _ = self.run_cli("show", self.r2)
        self.assertEqual(code, EXIT_OK)
        self.assertIn(self.r2, out)

    def test_activate_atomic(self):
        code, _, _ = self.run_cli("activate", self.r1)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(read_active(self.home)["release_id"], self.r1)
        for point in kap_release.FAULT_POINTS:
            with self.subTest(point=point):
                before = _snapshot(self.home)
                with self.assertRaises(kap_release.ReleaseFault):
                    kap_release.activate(self.home, self.r2, fault_at=point)
                self.assertEqual(read_active(self.home)["release_id"], self.r1)
                self.assertFalse((self.home / ".lock").exists())
                self.assertEqual(list((self.home / "staging").iterdir()), [])
                self.assertEqual(_snapshot(self.home), before)
                self.assertTrue(verify_audit(self.home)[0])
        code, _, _ = self.run_cli("activate", self.r2)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(read_active(self.home)["release_id"], self.r2)

    def test_activate_tampered_release_refused(self):
        self.run_cli("activate", self.r1)
        (self.home / "releases" / self.r2 / "coverage" / "coverage-manifest.json").write_bytes(b"tampered\n")
        code, _, err = self.run_cli("activate", self.r2)
        self.assertEqual(code, EXIT_INTEGRITY)
        self.assertEqual(read_active(self.home)["release_id"], self.r1)
        self.assertIn("ERROR", err)

    def test_rollback(self):
        self.run_cli("activate", self.r1)
        self.run_cli("activate", self.r2)
        code, _, _ = self.run_cli("rollback")
        self.assertEqual(code, EXIT_OK)
        active = read_active(self.home)
        self.assertEqual(active["release_id"], self.r1)
        self.assertEqual([p["release_id"] for p in active["previous"]], [self.r2])
        code, _, _ = self.run_cli("rollback")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(read_active(self.home)["release_id"], self.r2)
        self.assertTrue(verify_audit(self.home)[0])

    def test_rollback_refuses_corrupt_previous(self):
        self.run_cli("activate", self.r1)
        self.run_cli("activate", self.r2)
        (self.home / "releases" / self.r1 / "coverage" / "coverage-manifest.json").write_bytes(b"tampered\n")
        before = _snapshot(self.home)
        code, _, _ = self.run_cli("rollback")
        self.assertEqual(code, EXIT_INTEGRITY)
        self.assertEqual(_snapshot(self.home), before)
        self.assertEqual(read_active(self.home)["release_id"], self.r2)

    def test_rollback_without_previous_refused(self):
        self.run_cli("activate", self.r1)
        code, _, _ = self.run_cli("rollback")
        self.assertEqual(code, EXIT_VALIDATION)
        self.assertEqual(read_active(self.home)["release_id"], self.r1)

    def test_remove_active_refused(self):
        self.run_cli("activate", self.r1)
        code, _, _ = self.run_cli("remove", self.r1)
        self.assertEqual(code, EXIT_VALIDATION)
        self.assertTrue((self.home / "releases" / self.r1).is_dir())
        self.assertEqual(read_active(self.home)["release_id"], self.r1)

    def test_remove_previous_needs_force(self):
        self.run_cli("activate", self.r1)
        self.run_cli("activate", self.r2)
        code, _, _ = self.run_cli("remove", self.r1)
        self.assertEqual(code, EXIT_VALIDATION)
        self.assertTrue((self.home / "releases" / self.r1).is_dir())
        code, _, _ = self.run_cli("remove", self.r1, "--force-previous")
        self.assertEqual(code, EXIT_OK)
        self.assertFalse((self.home / "releases" / self.r1).exists())
        self.assertEqual(read_active(self.home)["previous"], [])
        self.assertEqual(list((self.home / "staging" / "trash").iterdir()), [])

    def test_remove_inactive_release(self):
        self.run_cli("activate", self.r1)
        code, _, _ = self.run_cli("remove", self.r3)
        self.assertEqual(code, EXIT_OK)
        self.assertFalse((self.home / "releases" / self.r3).exists())
        self.assertTrue(verify_audit(self.home)[0])

    def test_deactivate(self):
        self.run_cli("activate", self.r1)
        code, _, _ = self.run_cli("deactivate")
        self.assertEqual(code, EXIT_OK)
        self.assertFalse((self.home / ACTIVE_NAME).exists())
        code, _, _ = self.run_cli("deactivate")
        self.assertEqual(code, EXIT_OK)

    def test_diff_lists_changes(self):
        code, out, _ = self.run_cli("diff", self.r1, self.r2)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("changed", out)
        self.assertNotIn("DESTRUCTIVE", out)

    def test_diff_flags_destructive_rule_removal(self):
        r4 = _install(self.home, _tree(self.tmp / "t4", rules=[]))
        code, out, _ = self.run_cli("diff", self.r1, r4)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("DESTRUCTIVE", out)

    def test_audit_verify(self):
        self.run_cli("activate", self.r1)
        self.run_cli("activate", self.r2)
        code, _, _ = self.run_cli("audit-verify")
        self.assertEqual(code, EXIT_OK)
        # The chain links each entry to its predecessor, so an edit to a non-final entry is detected.
        log = self.home / "audit.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines(keepends=True)
        self.assertEqual(len(lines), 2)
        lines[0] = lines[0].replace("release_activated", "release_removed", 1)
        log.write_text("".join(lines), encoding="utf-8")
        code, _, _ = self.run_cli("audit-verify")
        self.assertEqual(code, EXIT_INTEGRITY)

    def test_build_requires_a_plan_file(self):
        """T070 replaced the T017 stub: `release build` runs the pipeline from a plan file, so omitting --plan is a usage
        error (exit 2) and nothing is built or installed."""
        before = sorted(p.name for p in (self.home / "releases").iterdir())
        code, _, err = self.run_cli("build", "--dry-run")
        self.assertEqual(code, EXIT_USAGE)
        self.assertNotIn("T070", err)  # the stub text is gone
        self.assertEqual(before, sorted(p.name for p in (self.home / "releases").iterdir()))
        self.assertFalse((self.home / ACTIVE_NAME).exists())

    def test_lock_held_refused(self):
        (self.home / ".lock").write_text(f"{os.getpid()}\n", encoding="utf-8")
        code, _, _ = self.run_cli("activate", self.r1)
        self.assertEqual(code, EXIT_VALIDATION)
        self.assertFalse((self.home / ACTIVE_NAME).exists())

    def test_exit_codes(self):
        self.assertEqual(self.run_cli("list")[0], EXIT_OK)
        self.assertEqual(self.run_cli("show", "kr-000000000000")[0], EXIT_VALIDATION)
        self.run_cli("activate", self.r1)
        self.assertEqual(self.run_cli("remove", self.r1)[0], EXIT_VALIDATION)
        self.assertEqual(self.run_cli("build")[0], EXIT_USAGE)
        self.assertEqual((EXIT_OK, EXIT_VALIDATION, EXIT_USAGE, EXIT_INTEGRITY), (0, 1, 2, 5))


if __name__ == "__main__":
    unittest.main()
