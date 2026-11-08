"""TST-011-030 (REQ-KAP-044, REQ-KAP-011): deterministic synthetic repository builder.

Verifies that two independent builds produce identical commit SHAs and that the
expected-changes manifest matches what git itself reports for the version pair.
Offline only; the synthetic repository lives in temporary directories.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.fixtures.kap.make_synth_repo import build_synth_repo

GIT = shutil.which("git")


def _git_status_map(repo: Path, from_sha: str, to_sha: str) -> dict:
    out = subprocess.run(
        ["git", "-C", str(repo), "diff-tree", "-r", "-M", "--name-status", from_sha, to_sha],
        check=True, capture_output=True, text=True,
    ).stdout
    result = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0].startswith("R"):
            result[parts[2]] = ("R", parts[1])
        else:
            result[parts[1]] = (parts[0], None)
    return result


@unittest.skipUnless(GIT, "git is not installed; synthetic repository builder requires git")
class SynthRepoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_shas_deterministic(self):
        first = build_synth_repo(self.root / "run1")
        second = build_synth_repo(self.root / "run2")
        self.assertEqual(first.from_sha, second.from_sha)
        self.assertEqual(first.to_sha, second.to_sha)
        self.assertNotEqual(first.from_sha, first.to_sha)
        self.assertRegex(first.from_sha, r"^[0-9a-f]{40}$")
        self.assertRegex(first.to_sha, r"^[0-9a-f]{40}$")

    def test_expected_changes_manifest_present(self):
        repo = build_synth_repo(self.root / "repo")
        manifest = repo.expected_changes
        self.assertTrue(manifest, "expected-changes manifest must not be empty")

        domains = {entry["domain"] for entry in manifest}
        for required in ("python_orm", "xml_view", "security", "manifest", "js_owl", "migration_script"):
            self.assertIn(required, domains)

        kinds = {entry["kind"] for entry in manifest}
        for required in ("rename", "unparsable", "added", "removed", "modified"):
            self.assertIn(required, kinds)

        # The manifest must agree with what git reports for the pair.
        status = _git_status_map(Path(repo.path), repo.from_sha, repo.to_sha)
        for entry in manifest:
            got = status.get(entry["path"])
            self.assertIsNotNone(got, f"git reports no change for {entry['path']}")
            self.assertEqual(got[0], entry["file_change"], entry["path"])
            if entry["kind"] == "rename":
                self.assertEqual(got[1], entry["old_path"])

if __name__ == "__main__":
    unittest.main()
