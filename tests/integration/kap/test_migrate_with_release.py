"""TST-011-083 (REQ-KAP-001, REQ-KAP-036, REQ-KAP-038, REQ-KAP-042): `migrate` with an activated knowledge release.

Offline: `socket.socket` and `socket.create_connection` are replaced for the whole module and counted, so any network
attempt fails the test. The release is built from `tests/fixtures/kap/fixture_release` (synthetic) and installed
through the real export/import path into a tmp kb-home. Built-in data the fixture does not carry (the compatibility
files the layer-3 check reads, the evidence the built-in rules cite, and DETECT_ONLY copies of the built-in 17-18 and
shared rules) is added to the tmp copy only; FIX_ENABLED rules are never shipped (the importer refuses them unverified).

The fixture's own probe rule (`12-13.python.probe`) is DETECT_ONLY but declares a fixer and no parameters, so it can
never bind. In the tmp copy only, its `fixer_ref` is cleared and its `decorator` parameter set to `api.model`, which
`tests/golden_fixtures/17.0/kbi_demo/models/demo.py` uses; that is what makes the release rule fire.
"""

import contextlib
import io
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.package.importer import import_package
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.resolver import resolve_knowledge
from odooflux.knowledge.release.store import ACTIVE_NAME, ensure_layout, read_active
from tests.integration.kap.test_package_lifecycle import FIXTURE, META

GOLDEN = Path(__file__).resolve().parents[2] / "golden_fixtures" / "17.0" / "kbi_demo"
PROBE = "12-13.python.probe"
DETECT_IDS_17_18 = set()  # filled in setUpModule from the built-in 17-18 rules (DETECT_ONLY only)
BUILTIN_RULE_IDS = set()  # every built-in knowledge rule id; legacy findings are the rows outside this set
STEPS_COVERED = [{"step": "12-13", "completeness": "COMPLETE", "ledger_digest": "ab" * 32},
                 {"step": "17-18", "completeness": "COMPLETE", "ledger_digest": "cd" * 32}]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _detect_rules(name: str) -> list:
    return [r for r in _load(KNOWLEDGE_ROOT / "compatibility" / name) if r.get("maturity") == "DETECT_ONLY"]


SHARED_DETECT_IDS = set()


def setUpModule():
    DETECT_IDS_17_18.update(r["id"] for r in _detect_rules("17-18.rules.json"))
    SHARED_DETECT_IDS.update(r["id"] for r in _detect_rules("shared.rules.json"))
    for path in (KNOWLEDGE_ROOT / "compatibility").glob("*.rules.json"):
        BUILTIN_RULE_IDS.update(r["id"] for r in _load(path))


def _build_release(root: Path, label: str):
    """Install-ready release tree from the fixture plus the added built-in data. Returns the tree."""
    tree = root / "release"
    shutil.copytree(FIXTURE, tree)
    shutil.copytree(KNOWLEDGE_ROOT / "official_sources", tree / "knowledge" / "official_sources")
    (tree / "coverage" / "coverage-manifest.json").write_bytes(b'{"items": []}\n')
    compat, evidence = tree / "knowledge" / "compatibility", tree / "knowledge" / "evidence"
    for src in (KNOWLEDGE_ROOT / "compatibility").iterdir():
        if src.name.endswith(".rules.json") or (compat / src.name).exists():
            continue
        if src.is_dir():
            shutil.copytree(src, compat / src.name)
        else:
            shutil.copyfile(src, compat / src.name)
    shutil.copyfile(KNOWLEDGE_ROOT / "compatibility" / "versions.json", compat / "versions.json")
    for src in (KNOWLEDGE_ROOT / "evidence").iterdir():
        if src.is_file() and not (evidence / src.name).exists():
            shutil.copyfile(src, evidence / src.name)
    probe = compat / "12-13.rules.json"
    rules = _load(probe)
    rules[0]["params"] = {"decorator": "api.model"}
    rules[0]["fixer_ref"] = None
    probe.write_text(json.dumps(rules, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (compat / "17-18.rules.json").write_text(json.dumps(_detect_rules("17-18.rules.json"), indent=2, sort_keys=True)
                                             + "\n", encoding="utf-8")
    (compat / "shared.rules.json").write_text(json.dumps(_detect_rules("shared.rules.json"), indent=2, sort_keys=True)
                                              + "\n", encoding="utf-8")
    write_release_manifest(tree, {**META, "label": label, "steps_covered": STEPS_COVERED})
    return tree


def _tree_bytes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class MigrateWithReleaseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.net = mock.MagicMock(side_effect=AssertionError("network is disabled in tests"))
        for target in ("socket.socket", "socket.create_connection"):
            patch = mock.patch(target, self.net)
            patch.start()
            self.addCleanup(patch.stop)
        self.pkg = export_package(_build_release(self.tmp / "src", "kap-083"), self.tmp / "release.ofkp")
        self.home = self.tmp / "kb-home"
        import_package(self.pkg.path, self.home, activate=True)
        self.empty_home = self.tmp / "empty-home"  # no active release: the built-in knowledge
        ensure_layout(self.empty_home)
        self.module = self.tmp / "mod"
        shutil.copytree(GOLDEN, self.module, ignore=shutil.ignore_patterns("expected"))
        self.state = self.tmp / "state"

    def tearDown(self):
        self.assertEqual(self.net.call_count, 0, "a migrate run attempted a network connection")

    def migrate(self, *argv, home=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(["migrate", "--module", str(self.module), "--kb-home",
                                  str(self.home if home is None else home), "--state-dir", str(self.state),
                                  *argv])
        return code, out.getvalue(), err.getvalue()

    def report(self, name: str, *argv, home=None) -> dict:
        path = self.tmp / name
        code, _, err = self.migrate("--from-version", "12", "--to-version", "13", "--report", str(path),
                                    "--report-format", "json", *argv, home=home)
        self.assertIn(code, (0, 1), err)  # 1: open findings are normal here; 2 and 4 are failures
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def findings(report: dict) -> list:
        return [f for m in report["modules"] for f in m["findings"]]

    def probe_findings(self, report: dict) -> list:
        return [f for f in self.findings(report) if f.get("rule_id") == PROBE]

    def test_socket_blocked_migrate(self):
        report = self.report("socket.json")
        self.assertEqual(report["knowledge_release"]["release_id"], self.pkg.release_id)
        self.assertTrue(report["modules"], "the module was analysed")
        self.assertEqual(self.net.call_count, 0)

    def test_active_release_rules_used(self):
        # The probe exists only in the fixture release: it fires on the decorator in models/demo.py.
        with_release = self.report("with.json")
        hits = self.probe_findings(with_release)
        self.assertTrue(hits, "the release-only rule must fire on kbi_demo")
        self.assertTrue(all(h["path"].endswith("models/demo.py") for h in hits), hits)
        # Removing the activation returns to the built-in knowledge, where the probe does not exist.
        active = self.home / ACTIVE_NAME
        saved = active.read_bytes()
        active.unlink()
        try:
            built_in = self.report("built-in.json")
        finally:
            active.write_bytes(saved)
        self.assertFalse(self.probe_findings(built_in))
        self.assertTrue(built_in["knowledge_release"]["builtin"])

    def test_report_has_release_id_digest(self):
        active = read_active(self.home)
        report = self.report("active.json")
        block = report["knowledge_release"]
        self.assertEqual(block["release_id"], self.pkg.release_id)
        self.assertEqual(block["digest"], self.pkg.release_digest)
        self.assertEqual(block["digest"], active["digest"])
        self.assertFalse(block["builtin"])
        self.assertEqual(block["completeness"], "COMPLETE")

        built_in = self.report("built-in-digest.json", home=self.empty_home)
        expected = resolve_knowledge(self.empty_home)
        self.assertTrue(expected.builtin)
        self.assertEqual(built_in["knowledge_release"]["release_id"], expected.release_id)
        self.assertEqual(built_in["knowledge_release"]["digest"], expected.digest)
        self.assertTrue(built_in["knowledge_release"]["builtin"])

    def test_legacy_overlap_with_release(self):
        # Rules present in both the built-in tree and the release (DETECT_ONLY 17-18 and shared rules) must produce
        # the same findings after the legacy/knowledge overlap dedup, whichever knowledge is active.
        def rows(report):
            # Knowledge rows of the rules present in both (the DETECT_ONLY copies), plus every legacy row; the
            # built-in-only FIX_ENABLED rules are excluded from both sides because the release does not ship them.
            kept = DETECT_IDS_17_18 | SHARED_DETECT_IDS
            return sorted((f.get("rule_id") or "", f.get("path") or "", f.get("line") or 0, f.get("severity") or "",
                           f.get("status") or "", f.get("message") or "")
                          for f in self.findings(report)
                          if f.get("rule_id") in kept or f.get("rule_id") not in BUILTIN_RULE_IDS)

        common = ("--from-version", "17", "--to-version", "18")

        def run(name, home):
            path = self.tmp / name
            code, _, err = self.migrate(*common, "--report", str(path), "--report-format", "json", home=home)
            self.assertIn(code, (0, 1), err)
            return json.loads(path.read_text(encoding="utf-8"))

        built_in = run("overlap-builtin.json", self.empty_home)
        with_release = run("overlap-release.json", self.home)
        self.assertTrue(built_in["knowledge_release"]["builtin"])
        self.assertFalse(with_release["knowledge_release"]["builtin"])
        shared_hits = [r for r in rows(built_in) if r[0] in DETECT_IDS_17_18 | SHARED_DETECT_IDS]
        self.assertTrue(shared_hits, "at least one rule present in both must fire, or the overlap is not exercised")
        self.assertEqual(rows(with_release), rows(built_in))

    def test_rollback_contract_unchanged(self):
        before = _tree_bytes(self.module)
        code, _, err = self.migrate("--from-version", "17", "--to-version", "18", "--fix")
        self.assertIn(code, (0, 1, 3), err)
        after = _tree_bytes(self.module)
        self.assertNotEqual(after, before, "the fix run must change the module, or the rollback is not exercised")
        runs = sorted(p.name for p in (self.state / "runs").iterdir())
        self.assertEqual(len(runs), 1)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(["rollback", runs[0], "--state-dir", str(self.state)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(_tree_bytes(self.module), before, "rollback restores the pre-run bytes")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(["rollback", runs[0], "--state-dir", str(self.state)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("already rolled back", out.getvalue())


if __name__ == "__main__":
    unittest.main()
