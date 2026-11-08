"""AR-R3-3 (rollback idempotency): a second ``odooflux rollback`` of an already restored run reports
"already rolled back" and exits 0; it never overwrites user edits made after the restore. A file that matches
neither the backup nor the fixed state is still a conflict (exit 1), and its bytes are kept."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "golden_fixtures" / "17.0" / "kbi_demo"


def _cli(*args) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    return subprocess.run([sys.executable, "-m", "odooflux", *args], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=300)


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file() and "expected" not in p.relative_to(root).parts}


class FixRollbackIdempotencyTests(unittest.TestCase):
    """AR-R3-3: repeated rollback must not report restored files as conflicts."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="odooflux-rb-"))
        self.module = self.tmp / "kbi_demo"
        shutil.copytree(FIXTURE, self.module, ignore=shutil.ignore_patterns("expected"))
        self.original = _tree(self.module)
        self.state = self.tmp / "state"
        fix = _cli("migrate", "--module", str(self.module), "--from-version", "17", "--to-version", "18",
                   "--fix", "--state-dir", str(self.state), "--no-color")
        self.assertEqual(fix.returncode, 0, fix.stdout + fix.stderr)
        self.assertNotEqual(_tree(self.module), self.original, "the fix run must change the copy")
        runs = sorted((self.state / "runs").iterdir())
        self.assertEqual(len(runs), 1)
        self.run_id = runs[0].name

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_rollback_says_already_rolled_back_and_exits_zero(self):
        first = _cli("rollback", self.run_id, "--state-dir", str(self.state))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(_tree(self.module), self.original)

        second = _cli("rollback", self.run_id, "--state-dir", str(self.state))
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("already rolled back", second.stdout)
        self.assertNotIn("conflict", second.stdout)
        self.assertEqual(_tree(self.module), self.original)

    def test_user_edit_after_restore_is_still_a_conflict_and_is_kept(self):
        first = _cli("rollback", self.run_id, "--state-dir", str(self.state))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

        edited = self.module / "models" / "demo.py"
        user_bytes = b"# the user edited this after the restore\n"
        edited.write_bytes(user_bytes)

        second = _cli("rollback", self.run_id, "--state-dir", str(self.state))
        self.assertEqual(second.returncode, 1, second.stdout + second.stderr)
        conflict_lines = [line for line in second.stdout.splitlines() if line.startswith("conflict")]
        self.assertEqual(conflict_lines, [f"conflict  {edited}  (changed after the run; skipped)"])
        self.assertEqual(edited.read_bytes(), user_bytes)
        others = {k: v for k, v in _tree(self.module).items() if k != "models/demo.py"}
        expected = {k: v for k, v in self.original.items() if k != "models/demo.py"}
        self.assertEqual(others, expected)


if __name__ == "__main__":
    unittest.main()
