"""TST-011-018 (REQ-KAP-022, REQ-KAP-024, REQ-KAP-027): `knowledge package` CLI group.

Contract: cli-surface (package verbs, exit code 3 for package rejection), knowledge-package-format (writer, reader,
P10 refusal). Packages are built with the real builder from DETECT_ONLY release trees; one explicit test refuses a
FIX_ENABLED rule and asserts the refusal only. kb-home is compared byte for byte wherever a command must not change it.
Everything runs offline; the socket layer is patched to raise.
"""

import hashlib
import io
import json
import shutil
import socket
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from odooflux.cli.kap_common import EXIT_OK, EXIT_PACKAGE_REJECTED, EXIT_VALIDATION
from odooflux.cli.knowledge import main as knowledge_main
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.release.audit import verify_audit
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import ReleaseState
from odooflux.knowledge.release.store import ensure_layout, list_installed, read_active, set_release_state

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


def _tree(root: Path, *, coverage: bytes = b'{"items": []}\n', maturity: str = "DETECT_ONLY") -> Path:
    shutil.copytree(KNOWLEDGE_ROOT / "official_sources", root / "knowledge" / "official_sources")
    evidence = json.loads((KNOWLEDGE_ROOT / "evidence" / "EV-101.json").read_text(encoding="utf-8"))
    evidence["status"] = "UNVERIFIED"
    files = {
        "knowledge/evidence/EV-101.json": json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        "knowledge/compatibility/versions.json": json.dumps({"versions": [], "transitions": []}) + "\n",
        "knowledge/compatibility/12-13.rules.json":
            json.dumps([{**RULE, "maturity": maturity}], indent=2, sort_keys=True) + "\n",
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestPackageCli(unittest.TestCase):
    def setUp(self):
        self._net = mock.patch.object(socket, "socket", side_effect=OSError("network disabled in KAP tests"))
        self._net.start()
        self.addCleanup(self._net.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home_a = self.tmp / "kb-a"
        self.home_b = self.tmp / "kb-b"
        ensure_layout(self.home_a)
        ensure_layout(self.home_b)
        self.release_a = _install(self.home_a, _tree(self.tmp / "tree-a"))

    def run_cli(self, *argv, home=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = knowledge_main(["package", *argv, "--kb-home", str(home or self.home_b)])
        return code, out.getvalue(), err.getvalue()

    def export_a(self, name="pkg.ofkp") -> Path:
        out = self.tmp / name
        code, _, _ = self.run_cli("export", self.release_a, "-o", str(out), home=self.home_a)
        self.assertEqual(code, EXIT_OK)
        return out

    def test_export_import_cli_roundtrip(self):
        pkg = self.export_a()
        code, _, _ = self.run_cli("import", str(pkg), "--activate")
        self.assertEqual(code, EXIT_OK)
        active = read_active(self.home_b)
        self.assertEqual(active["release_id"], self.release_a)
        self.assertEqual(active["digest"], json.loads(
            (self.home_a / "releases" / self.release_a / "release.json").read_text(encoding="utf-8"))["release_digest"])
        self.assertTrue(verify_audit(self.home_a)[0])
        self.assertTrue(verify_audit(self.home_b)[0])

    def test_export_is_deterministic(self):
        first = self.export_a("one.ofkp")
        second = self.export_a("two.ofkp")
        self.assertEqual(_sha256(first), _sha256(second))

    def test_rejection_exit_code_3(self):
        corrupt = self.tmp / "corrupt.ofkp"
        corrupt.write_bytes(b"not a zip archive")
        before = _snapshot(self.home_b)
        code, _, err = self.run_cli("import", str(corrupt), "--activate")
        self.assertEqual(code, EXIT_PACKAGE_REJECTED)
        self.assertIn("ERROR", err)
        self.assertEqual(_snapshot(self.home_b), before)
        code, _, _ = self.run_cli("validate", str(corrupt))
        self.assertEqual(code, EXIT_PACKAGE_REJECTED)

    def test_expect_digest_mismatch(self):
        pkg = self.export_a()
        wrong = "00" * 32
        code, _, _ = self.run_cli("validate", str(pkg), "--expect-digest", wrong)
        self.assertEqual(code, EXIT_PACKAGE_REJECTED)
        before = _snapshot(self.home_b)
        code, _, _ = self.run_cli("import", str(pkg), "--activate", "--expect-digest", wrong)
        self.assertEqual(code, EXIT_PACKAGE_REJECTED)
        self.assertEqual(_snapshot(self.home_b), before)
        digest = json.loads((self.home_a / "releases" / self.release_a / "release.json")
                            .read_text(encoding="utf-8"))["release_digest"]
        code, _, _ = self.run_cli("validate", str(pkg), "--expect-digest", digest)
        self.assertEqual(code, EXIT_OK)

    def test_validate_installs_nothing(self):
        pkg = self.export_a()
        before = _snapshot(self.home_b)
        code, _, _ = self.run_cli("validate", str(pkg))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(_snapshot(self.home_b), before)

    def test_list_and_inspect(self):
        pkg = self.export_a()
        code, out, _ = self.run_cli("list", str(pkg))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("release.json", out)
        self.assertIn("package.json", out)
        code, out, _ = self.run_cli("inspect", str(pkg), "--json")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out)["release_id"], self.release_a)

    def test_export_unknown_release(self):
        code, _, _ = self.run_cli("export", "kr-000000000000", "-o", str(self.tmp / "x.ofkp"), home=self.home_a)
        self.assertEqual(code, EXIT_VALIDATION)
        self.assertFalse((self.tmp / "x.ofkp").exists())

    def test_fix_enabled_rule_refused(self):
        # The one explicit FIX_ENABLED case: the importer must refuse it. Only the refusal is asserted.
        fix_tree = _tree(self.tmp / "tree-fix", maturity="FIX_ENABLED")
        fix_pkg = export_package(_install_tree_dir(self.tmp / "fix-home", fix_tree), self.tmp / "fix.ofkp").path
        before = _snapshot(self.home_b)
        code, _, _ = self.run_cli("import", str(fix_pkg), "--activate")
        self.assertEqual(code, EXIT_PACKAGE_REJECTED)
        self.assertEqual(_snapshot(self.home_b), before)
        self.assertEqual(list_installed(self.home_b), [])

def _install_tree_dir(home: Path, tree: Path) -> Path:
    ensure_layout(home)
    _install(home, tree)
    return home / "releases" / json.loads((tree / "release.json").read_text(encoding="utf-8"))["release_id"]


if __name__ == "__main__":
    unittest.main()
