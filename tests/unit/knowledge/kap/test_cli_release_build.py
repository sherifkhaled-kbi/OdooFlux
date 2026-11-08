"""TST-011-070 (REQ-KAP-029; contracts/cli-surface.md, release-lifecycle.md): `knowledge release build` runs the pipeline.

- A dry run prints the plan (17 steps) and writes nothing: the kb-home directory is not even created.
- A required source that cannot be acquired stops the build with exit 4, and no release is installed, so there is
  nothing to export.
- A successful build (the synthetic 16.0 to 17.0 pair, which is PARTIAL) is installed in kb-home as INSTALLED and is
  never ACTIVE (no automatic activation). `active.json` is not written.
Offline: sockets are patched to fail. The plan file is written into a temporary directory.
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

from odooflux.builtins import build_registries
from odooflux.cli import knowledge as cli
from odooflux.knowledge import pipeline as pl
from odooflux.knowledge.release.store import list_installed
from tests.fixtures.kap.make_synth_repo import build_synth_repo

GIT_AVAILABLE = shutil.which("git") is not None
CREATED = "2026-11-08T10:00:00Z"


def _spec(sid: str, url: str, revision: str, branch: str) -> dict:
    return {
        "source_id": sid, "kind": "GIT_COMMUNITY", "official": False, "url": url, "licence_access": "PUBLIC_OPEN",
        "licence_id": "LGPL-3", "branch": branch, "revision": revision,
        "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []}, "retrieved_at": None,
        "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }


class _NoSocket:
    def __init__(self, *args, **kwargs):
        raise AssertionError("network access attempted in an offline test")


@unittest.skipUnless(GIT_AVAILABLE, "git is not installed; the git-local adapter needs git")
class CliReleaseBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.repo = build_synth_repo(cls.base / "synth")
        cls._patches = [mock.patch.object(socket, "socket", _NoSocket),
                        mock.patch.object(socket, "create_connection", _NoSocket)]
        for patch in cls._patches:
            patch.start()

    @classmethod
    def tearDownClass(cls):
        for patch in cls._patches:
            patch.stop()
        cls._tmp.cleanup()

    def setUp(self):
        self.registries = build_registries()
        self.home = Path(tempfile.mkdtemp(prefix="kb-home-", dir=self.base))

    def _plan_file(self, name: str, specs: list, pairs: list, label: str = "cli-build") -> Path:
        document = {
            "label": label, "sources": specs, "pairs": pairs,
            "source_meta": {s["source_id"]: {"repository": "odoo/odoo"} for s in specs},
            "created_at": CREATED, "checked_on": "2026-11-08", "author": "cli-test",
        }
        path = self.base / f"{name}.plan.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def _synthetic_plan(self, name: str, *, from_url=None) -> Path:
        local = "local:" + self.repo.path
        specs = [_spec("odoo-community-16.0", from_url or local, self.repo.from_sha, "16.0"),
                 _spec("odoo-community-17.0", local, self.repo.to_sha, "17.0")]
        pairs = [{"step": "16-17", "from": "odoo-community-16.0", "to": "odoo-community-17.0"}]
        return self._plan_file(name, specs, pairs)

    def _cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), self.registries)
        return code, out.getvalue(), err.getvalue()

    def test_build_dry_run(self):
        plan = self._synthetic_plan("dry")
        home = self.home / "never-created"
        code, out, err = self._cli("release", "build", "--plan", str(plan), "--dry-run", "--kb-home", str(home))
        self.assertEqual(code, 0, err)
        for name in pl.STEP_NAMES:
            self.assertIn(name, out)
        self.assertIn("RUN", out)
        self.assertFalse(home.exists(), "a dry run writes nothing, not even the kb-home directory")

    def test_build_failed_not_exportable(self):
        missing = "local:" + str(self.base / "no-such-clone")
        plan = self._plan_file("missing", [
            _spec("odoo-community-16.0", missing, self.repo.from_sha, "16.0"),
            _spec("odoo-community-17.0", "local:" + self.repo.path, self.repo.to_sha, "17.0")],
            [{"step": "16-17", "from": "odoo-community-16.0", "to": "odoo-community-17.0"}])
        code, out, err = self._cli("release", "build", "--plan", str(plan), "--kb-home", str(self.home))
        self.assertEqual(code, 4, out + err)
        self.assertIn("SOURCE_REQUIRED_FAILED", err + out)
        self.assertEqual(list_installed(self.home), [], "a failed build installs no release")
        self.assertFalse((self.home / "active.json").exists())
        code, _, err = self._cli("release", "list", "--kb-home", str(self.home))
        self.assertEqual(code, 0, err)

    def test_partial_build_installed_not_active(self):
        plan = self._synthetic_plan("partial")
        code, out, err = self._cli("release", "build", "--plan", str(plan), "--kb-home", str(self.home), "--json")
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["outcome"], "OK")
        self.assertEqual(result["completeness"], "PARTIAL")
        installed = list_installed(self.home)
        self.assertEqual([r.release_id for r in installed], [result["release_id"]])
        self.assertEqual(installed[0].state.value, "INSTALLED")
        self.assertFalse((self.home / "active.json").exists(), "a built release is never activated automatically")

        code, out, err = self._cli("coverage", "show", "--release", result["release_id"], "--kb-home", str(self.home))
        self.assertEqual(code, 0, out + err)
        self.assertIn("M2 file_scan", out)
        self.assertIn("completeness PARTIAL", out)
        code, out, err = self._cli("coverage", "gates", "--release", result["release_id"], "--kb-home", str(self.home))
        self.assertEqual(code, 0, out + err)
        self.assertIn("G-FILES", out)
        self.assertIn("limit G-FILES", out)
        code, _, err = self._cli("coverage", "show", "--release", "kr-000000000000", "--kb-home", str(self.home))
        self.assertEqual(code, 2, err)


if __name__ == "__main__":
    unittest.main()
