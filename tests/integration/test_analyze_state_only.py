"""TST-003-030 (REQ-SAF-007, REQ-SAF-001): analyze and dry-run create only state.json and log/."""

import unittest
from pathlib import Path

from .helpers import make_module, new_tmp, run_cli_main as run_main, tree


class AnalyzeStateOnlyTests(unittest.TestCase):
    def _run_dir(self, state):
        (run,) = list((state / "runs").iterdir())
        return run

    def test_analyze_and_dry_run_touch_only_state(self):
        for extra in ([], ["--fix", "--dry-run"]):
            with self.subTest(extra=extra):
                root = new_tmp()
                module = make_module(root, "kbi_demo")
                before = tree(module)
                state = root / "state"
                run_main(["--module", module, "--from-version", "14", "--no-color",
                          "--state-dir", state, *extra])
                self.assertEqual(tree(module), before)
                self.assertEqual(sorted(p.name for p in self._run_dir(state).iterdir()), ["log", "state.json"])


if __name__ == "__main__":
    unittest.main()
