"""Regression: fetching by a SHA that the remote does not have is REVISION_UNAVAILABLE, not IO_ERROR.

Uses a local bare repository as the transport (the `transport_url` test seam). No test contacts the network.
Run: PYTHONPATH=src python3 -m unittest discover -s tests/unit/knowledge/update -p 'test_remote_git_commit_missing.py' -t .
"""

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import SOURCE_ERROR_CODES, SourceError
from odooflux.knowledge.update import remote_git as rg

IDENTITY_INPUT = "https://github.com/odoo/odoo/"
IDENTITY = "https://github.com/odoo/odoo"
BOGUS_SHA = "1" * 40  # well-formed, present in no repository


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git is required for the remote fetch tests")
class CommitMissingOnRemoteTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        work = root / "work"
        work.mkdir()
        _git("init", "-q", cwd=work)
        (work / "f.txt").write_text("hello\n", encoding="utf-8")
        _git("add", "f.txt", cwd=work)
        _git("-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "c1", cwd=work)
        self.sha = _git("rev-parse", "HEAD", cwd=work)
        self.source = root / "remote.git"
        _git("init", "-q", "--bare", str(self.source))
        _git("push", "-q", str(self.source), "HEAD:refs/heads/16.0", cwd=work)
        self.cache = root / "cache"

    def _tmp_entries(self):
        base = self.cache / hashlib.sha256(IDENTITY.encode("utf-8")).hexdigest()[:16]
        return sorted(p.name for p in base.glob("tmp-*")) if base.exists() else []

    def test_bogus_sha_is_revision_unavailable(self):
        with self.assertRaises(SourceError) as ctx:
            rg.fetch_commit(IDENTITY_INPUT, "16.0", BOGUS_SHA, self.cache, transport_url=str(self.source))
        self.assertEqual(ctx.exception.code, "REVISION_UNAVAILABLE")
        self.assertIn(ctx.exception.code, SOURCE_ERROR_CODES)
        self.assertFalse((self.cache / hashlib.sha256(IDENTITY.encode("utf-8")).hexdigest()[:16]
                          / BOGUS_SHA).exists())
        self.assertEqual(self._tmp_entries(), [], "a failing fetch removes its own temporary directory")

    def test_present_sha_still_fetches(self):
        repo = rg.fetch_commit(IDENTITY_INPUT, "16.0", self.sha, self.cache, transport_url=str(self.source))
        self.assertEqual(_git("-C", str(repo), "rev-parse", "--verify", f"{self.sha}^{{commit}}"), self.sha)

    def test_stderr_for_unknown_commit_is_classified_as_revision_unavailable(self):
        stderr = (b"fatal: git upload-pack: not our ref 1111111111111111111111111111111111111111\n"
                  b"fatal: remote error: upload-pack: not our ref 1111111111111111111111111111111111111111\n")
        self.assertEqual(rg.classify_git_stderr(stderr, attached=False), "REVISION_UNAVAILABLE")
        self.assertEqual(rg.classify_git_stderr(b"Server does not allow request for unadvertised object abc",
                                                attached=True), "REVISION_UNAVAILABLE")

    def test_network_failures_keep_their_codes(self):
        self.assertEqual(rg.classify_git_stderr(b"fatal: Could not resolve host: github.com", attached=False),
                         "UNAVAILABLE")
        self.assertIsNone(rg.classify_git_stderr(b"fatal: something unrelated", attached=False))


if __name__ == "__main__":
    unittest.main()
