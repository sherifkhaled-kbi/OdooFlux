"""Feature 012 Wave 3d: Enterprise-derived release content never reaches a rendered or serialised output.

An internal release is built from the synthetic fixture (through the migrate fixture). Its evidence `EV-101` cites an
Enterprise source (provenance kind GIT_ENTERPRISE) and carries canary strings in `match`, `locations[].path` and
`description`. The release is installed and activated in a tmp kb-home, then:

- every applicable knowledge verb and a migrate run that fires the Enterprise-evidence-backed rule are executed;
- every captured stream and every report file written is scanned: no canary may appear;
- a public control release (provenance kind GIT_COMMUNITY) with the same canaries shows the redaction is selective.

Offline: socket connections are blocked for the whole test. The git clone used by `refresh` is local.
"""

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins
from odooflux.cli import knowledge as cli
from odooflux.cli.kap_release import activate
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import ReleaseState
from odooflux.knowledge.release.store import ensure_layout, set_release_state
from tests.integration.kap import test_migrate_with_release as mwr
from tests.integration.kap.test_package_lifecycle import META

PROBE = mwr.PROBE
EVIDENCE = "EV-101"
ENTERPRISE_SOURCE = "odoo-enterprise-12.0"
COMMUNITY_SOURCE = "odoo-community-12.0"
ENTERPRISE_SNAPSHOT = "ss-" + "e1" * 6
COMMUNITY_SNAPSHOT = "ss-" + "c2" * 6
SNAP_OLD = {"snapshot_id": "ss-" + "0a" * 6, "snapshot_digest": "0a" * 32}
CANARY_MATCH = "ofcanary_enterprise_match_4e1d"
CANARY_PATH = "ofcanary_enterprise_path_8b7c"
CANARY_DESC = "ofcanary_enterprise_description_c3a9"
CANARIES = (CANARY_MATCH, CANARY_PATH, CANARY_DESC)
WITHHELD = "<enterprise location withheld>"


def _git(repo: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def knowledge_tree(release_tree: Path) -> Path:
    """The knowledge tree of a release (its `knowledge/` directory)."""
    return release_tree / "knowledge"


class ReleaseConfidentialityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is required for the refresh candidate search")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.net = mock.MagicMock(side_effect=AssertionError("network is disabled in tests"))
        for target in ("socket.socket", "socket.create_connection"):
            patch = mock.patch(target, self.net)
            patch.start()
            self.addCleanup(patch.stop)
        self.module = self.tmp / "mod"
        shutil.copytree(mwr.GOLDEN, self.module, ignore=shutil.ignore_patterns("expected"))
        self.out = self.tmp / "out"  # every report file written by a verb or migrate run lands here
        self.out.mkdir()
        self.clone, self.rev = self._make_clone()

    def tearDown(self):
        self.assertEqual(self.net.call_count, 0, "a command attempted a network connection")

    # -- fixtures ---------------------------------------------------------------------------------------------

    def _make_clone(self):
        """A local repository. The canary file sits at the root, so a location under `odoo/` is missing and
        `refresh --search-candidates` finds the file by its basename."""
        clone = self.tmp / "clone"
        clone.mkdir()
        _git(clone, "init", "-q")
        (clone / f"{CANARY_PATH}.py").write_text(f"x = '{CANARY_MATCH}'\n", encoding="utf-8")
        _git(clone, "add", "-A")
        subprocess.run(["git", "-C", str(clone), "-c", "user.email=t@example.invalid", "-c", "user.name=t",
                        "commit", "-q", "-m", "fixture"], check=True, capture_output=True)
        return clone, _git(clone, "rev-parse", "HEAD").strip()

    def _release(self, name: str, source: str, kind: str, snapshot: str) -> dict:
        """An installed and active release whose EV-101 cites `source` (provenance kind `kind`)."""
        tree = mwr._build_release(self.tmp / name, label=f"{name}-12-13")
        evidence_path = tree / "knowledge" / "evidence" / "EV-101.json"
        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        record["source_id"] = source
        record["description"] = f"Canary claim {CANARY_DESC}"
        record["revision"] = self.rev
        for loc in record["locations"]:
            loc["path"] = f"odoo/{CANARY_PATH}.py"
            loc["match"] = CANARY_MATCH
            loc["revision"] = self.rev
            loc["line"] = 1 if loc["kind"] == "present" else None
            if loc["kind"] == "absent":
                loc["search_scope"] = f"odoo/{CANARY_PATH}.py"
        evidence_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        url = "https://github.com/odoo/enterprise" if kind == "GIT_ENTERPRISE" else "https://github.com/odoo/odoo"
        provenance = {"sources": [{
            "source_id": source, "kind": kind, "url": url, "origin_url": None, "revision": self.rev,
            "snapshot_id": snapshot, "snapshot_digest": "ee" * 32, "official": True, "status": "VERIFIED"}]}
        (tree / "provenance" / "sources.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n",
                                                           encoding="utf-8")
        manifest = write_release_manifest(tree, {**META, "label": f"{name}-12-13",
                                                 "steps_covered": mwr.STEPS_COVERED})
        home = self.tmp / f"home-{name}"
        ensure_layout(home)
        shutil.copytree(tree, home / "releases" / manifest["release_id"])
        set_release_state(home, manifest["release_id"], ReleaseState.INSTALLED)
        activate(home, manifest["release_id"])
        return {"tree": knowledge_tree(tree), "id": manifest["release_id"], "home": home, "snapshot": snapshot}

    def _ledger(self, name: str, snapshot: str):
        """A ledger with one change located in `snapshot`; its detail carries a canary attribute value.
        Returns (path, change_id)."""
        drafts = [{"domain": "python_orm", "kind": "field", "subject_key": "sale.demo.order::field::amount",
                   "class": "SIGNATURE_CHANGED", "detail": {"from": CANARY_DESC, "to": "Monetary"},
                   "locations": [{"snapshot_id": snapshot, "path": f"{CANARY_PATH}.py", "line": 7,
                                  "sha256": "a" * 64}],
                   "proposed_by": "DETERMINISTIC"}]
        new = {"snapshot_id": snapshot, "snapshot_digest": "ee" * 32, "entries": [],
               "created_at": "2026-11-08T10:00:00Z"}
        ledger = Ledger.create("12-13", SNAP_OLD, new, drafts, clock=lambda: "2026-11-08T10:00:00Z")
        path = self.tmp / f"{name}.ledger.json"
        ledger.save(path)
        return path, ledger.records()[0]["change_id"]

    # -- running ----------------------------------------------------------------------------------------------

    def knowledge(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def migrate(self, release, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(["migrate", "--module", str(self.module), "--kb-home", str(release["home"]),
                                  "--from-version", "12", "--to-version", "13", *argv])
        return code, out.getvalue(), err.getvalue()

    def run_all_verbs(self, release, tag: str) -> dict:
        """Every applicable verb for `release`: {label: (code, stdout, stderr)}."""
        home, tree, rid = str(release["home"]), str(release["tree"]), release["id"]
        ledger, cid = self._ledger(tag, release["snapshot"])
        clone = f"odoo/odoo={self.clone}"
        return {
            "release show": self.knowledge("release", "show", rid, "--kb-home", home),
            "release show --json": self.knowledge("release", "show", rid, "--kb-home", home, "--json"),
            "release list": self.knowledge("release", "list", "--kb-home", home),
            "rule inspect": self.knowledge("rule", "inspect", "--path", tree, "--id", PROBE),
            "rule inspect --json": self.knowledge("rule", "inspect", "--path", tree, "--id", PROBE, "--json"),
            "rule validate": self.knowledge("rule", "validate", "--path", tree),
            "validate": self.knowledge("validate", "--path", tree),
            "status": self.knowledge("status", "--kb-home", home),
            "status --json": self.knowledge("status", "--kb-home", home, "--json"),
            "history": self.knowledge("history", "--kb-home", home),
            "update check": self.knowledge("check", "--offline", "--kb-home", home),
            "coverage show": self.knowledge("coverage", "show", "--release", rid, "--kb-home", home),
            "candidates list": self.knowledge("candidates", "list", "--path", tree),
            "ledger list": self.knowledge("ledger", "list", "--ledger", str(ledger)),
            "ledger show": self.knowledge("ledger", "show", cid, "--ledger", str(ledger), "--kb-home", home),
            "ledger show --json": self.knowledge("ledger", "show", cid, "--ledger", str(ledger),
                                                 "--kb-home", home, "--json"),
            "ledger verify": self.knowledge("ledger", "verify", "--ledger", str(ledger)),
            "refresh": self.knowledge("refresh", "--path", tree, "--repo", clone, "--search-candidates"),
            "refresh --report": self.knowledge("refresh", "--path", tree, "--repo", clone, "--search-candidates",
                                               "--report", str(self.out / f"{tag}-refresh.json")),
        }

    def migrate_outputs(self, release, tag: str):
        report = self.out / f"{tag}.json"
        sarif, html = self.out / f"{tag}.sarif", self.out / f"{tag}.html"
        code, out, err = self.migrate(release, "--report", str(report), "--report-format", "json",
                                      "--sarif", str(sarif), "--html", str(html), "--ui", "ansi",
                                      "--state-dir", str(self.tmp / f"state-{tag}"))
        self.assertIn(code, (0, 1), err)
        findings = [f for m in json.loads(report.read_text(encoding="utf-8"))["modules"] for f in m["findings"]]
        return (out, err), findings, [report, sarif, html]

    # -- assertions -------------------------------------------------------------------------------------------

    def assert_no_canary(self, texts: dict, files: list):
        for label, text in texts.items():
            for canary in CANARIES:
                self.assertNotIn(canary, text, f"canary leaked into {label}")
        for path in files:
            self.assertTrue(path.is_file(), f"expected report file {path}")
        for path in [p for p in self.out.rglob("*") if p.is_file()] + \
                [p for p in self.tmp.glob("state-*") for p in p.rglob("*") if p.is_file()]:
            text = path.read_text(encoding="utf-8", errors="replace")
            for canary in CANARIES:
                self.assertNotIn(canary, text, f"canary leaked into written file {path.name}")

    # -- tests ------------------------------------------------------------------------------------------------

    def test_enterprise_release_outputs_carry_no_canary(self):
        enterprise = self._release("enterprise", ENTERPRISE_SOURCE, "GIT_ENTERPRISE", ENTERPRISE_SNAPSHOT)
        results = self.run_all_verbs(enterprise, "ent")
        (out, err), findings, files = self.migrate_outputs(enterprise, "ent-migrate")

        # the Enterprise-evidence-backed rule fires in the migrate run, so the test exercises the real path
        probe = [f for f in findings if f.get("rule_id") == PROBE]
        self.assertTrue(probe, "the probe rule did not fire on the Enterprise-evidence-backed release")
        self.assertIn(EVIDENCE, probe[0]["evidence"])

        texts = {"migrate stdout": out, "migrate stderr": err}
        for label, (_code, stdout, stderr) in results.items():
            texts[f"{label} stdout"] = stdout
            texts[f"{label} stderr"] = stderr
        self.assert_no_canary(texts, files)

        # the Enterprise ledger location is withheld (the snapshot id stays), not dropped
        self.assertIn(WITHHELD, results["ledger show"][1])
        self.assertIn(ENTERPRISE_SNAPSHOT, results["ledger show"][1])

    def test_public_control_keeps_public_output(self):
        public = self._release("public", COMMUNITY_SOURCE, "GIT_COMMUNITY", COMMUNITY_SNAPSHOT)
        results = self.run_all_verbs(public, "pub")
        # public outputs are not redacted: the public ledger location and detail are as stored
        self.assertIn(f"{CANARY_PATH}.py", results["ledger show"][1])
        self.assertNotIn(WITHHELD, results["ledger show"][1])
        self.assertIn(f"{CANARY_PATH}.py", json.loads(results["ledger show --json"][1])["locations"][0]["path"])
        (_out, _err), findings, _files = self.migrate_outputs(public, "pub-migrate")
        self.assertTrue([f for f in findings if f.get("rule_id") == PROBE])


if __name__ == "__main__":
    unittest.main()
