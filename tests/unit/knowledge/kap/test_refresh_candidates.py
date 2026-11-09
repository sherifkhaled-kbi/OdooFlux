"""Regression: `refresh --search-candidates` returns hits for a match that moved to another path.

`git grep -l` prints "REV:path" (one colon). The candidate parser used to require two colons, so every
hit was dropped and the search never returned anything. These tests use a local repository only.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge import refresh as rf

MATCH = "CANARY_REFRESH_MATCH"


def _git(repo: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git is required for the refresh candidate search")
class RefreshCandidateSearchTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "clone"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        # The match lives under a new directory (the file was moved); a non-matching file sits beside it.
        (self.repo / "addons" / "sale").mkdir(parents=True)
        (self.repo / "addons" / "sale" / "order.py").write_text(f"x = '{MATCH}'\n" + "\n" * 80, encoding="utf-8")
        (self.repo / "addons" / "sale" / "unrelated.py").write_text("y = 'nothing to see'\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t",
                        "commit", "-q", "-m", "fixture"], check=True, capture_output=True)
        self.rev = _git(self.repo, "rev-parse", "HEAD")

    def _loc(self, path: str, match: str = MATCH) -> dict:
        # Line 1 of the old path does not carry the match, and the file is gone from the window, so only the
        # candidate search can find it.
        return {"kind": "present", "path": path, "line": 1, "match": match, "branch": "17.0", "revision": self.rev}

    def test_matching_candidate_is_returned_for_same_basename(self):
        verdict = rf.classify_location(self.repo, self._loc("odoo/addons/sale/order.py"), self.rev,
                                       search_candidates=True)
        self.assertEqual(verdict["result"], "missing")
        self.assertEqual(verdict["candidates"], ["addons/sale/order.py"])

    def test_non_matching_file_is_not_returned(self):
        verdict = rf.classify_location(self.repo, self._loc("odoo/addons/sale/unrelated.py", match="NO_SUCH_TEXT_X"),
                                       self.rev, search_candidates=True)
        self.assertEqual(verdict["result"], "missing")
        self.assertEqual(verdict["candidates"], [])

    def test_match_in_file_with_other_basename_is_not_returned(self):
        verdict = rf.classify_location(self.repo, self._loc("odoo/addons/sale/elsewhere.py"), self.rev,
                                       search_candidates=True)
        self.assertEqual(verdict["result"], "missing")
        self.assertEqual(verdict["candidates"], [])

    def test_search_is_opt_in(self):
        verdict = rf.classify_location(self.repo, self._loc("odoo/addons/sale/order.py"), self.rev,
                                       search_candidates=False)
        self.assertEqual(verdict["candidates"], [])


if __name__ == "__main__":
    unittest.main()
