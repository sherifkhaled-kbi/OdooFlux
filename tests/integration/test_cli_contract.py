"""TST-003-028, TST-003-038, TST-003-039 (contracts/cli.md): options, plan writes nothing, versions."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from odooflux.utils.hashing import digest_tree

from .helpers import REPO, make_module, new_tmp

LEGACY_OPTIONS = ["--module", "--modules", "--addons-path", "--from-version", "--to-version", "--fix",
                  "--backup", "--dry-run", "--report", "--no-color", "--skip", "--show-fixed",
                  "--filter-severity", "--ai-fix", "--api-key", "--ai-verbose", "--fail-on", "--state-dir",
                  "--allow-unverified", "--plugin", "--report-format", "--no-backup"]


def _cli(args, env=None):
    proc = subprocess.run([sys.executable, str(REPO / "odooflux.py"), *map(str, args)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300,
                          env=env or os.environ.copy())
    return proc.returncode, proc.stdout


class CliContractTests(unittest.TestCase):
    def test_options_and_exit_codes(self):
        code, help_text = _cli(["migrate", "--help"])
        self.assertEqual(code, 0)
        for option in LEGACY_OPTIONS:
            self.assertIn(option, help_text)
        code, out = _cli(["--module", "/nonexistent-odooflux-path", "--from-version", "14"])
        self.assertEqual(code, 4)  # tool error
        code, out = _cli(["--from-version", "14", "--module", "/nonexistent", "--backup", "--no-backup"])
        self.assertEqual(code, 2)  # usage error (argparse-style exit)

    def test_plan_command_writes_nothing(self):
        root = new_tmp()
        module = make_module(root / "addons", "kbi_demo")
        before = digest_tree(root / "addons")
        cache = root / "cache"
        env = os.environ.copy()
        env["XDG_CACHE_HOME"] = str(cache)
        code, out = _cli(["plan", "--from", "14", "--to", "19", "--addons-path", root / "addons"], env=env)
        self.assertEqual(code, 0, out)
        self.assertIn("Plan 14.0 -> 19.0: READY", out)
        self.assertIn("kbi_demo", out)
        self.assertEqual(digest_tree(root / "addons"), before)
        self.assertFalse(cache.exists(), "plan must not create a state directory")

    def test_plan_below_registry_range_exits_4(self):
        root = new_tmp()
        make_module(root / "addons", "kbi_demo")
        code, out = _cli(["plan", "--from", "11", "--to", "19", "--addons-path", root / "addons"])
        self.assertEqual(code, 4, out)
        self.assertIn("BLOCKED", out)

    def test_rollback_and_resume_subcommands(self):
        root = new_tmp()
        module = make_module(root, "kbi_demo")
        original = digest_tree(module)
        state = root / "state"
        code, _ = _cli(["--module", module, "--from-version", "14", "--fix", "--no-color", "--state-dir", state])
        self.assertEqual(code, 1)  # legacy criticals remain after the fix
        (run_id,) = [p.name for p in (state / "runs").iterdir()]
        code, out = _cli(["rollback", run_id, "--state-dir", state])
        self.assertEqual(code, 0, out)
        self.assertEqual(digest_tree(module), original)
        code, out = _cli(["resume", run_id, "--state-dir", state])
        self.assertEqual(code, 4)  # a rolled-back run is not resumed
        self.assertIn("rolled back", out)

    def test_versions_command_lists_registry(self):
        code, out = _cli(["versions"])
        self.assertEqual(code, 0)
        for version in ("12.0", "13.0", "14.0", "19.0"):
            self.assertIn(version, out)
        self.assertIn("RESEARCH_SEEDED", out)


if __name__ == "__main__":
    unittest.main()
