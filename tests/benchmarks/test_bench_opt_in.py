"""TST-003-036 (REQ-PRF-001): the benchmark harness generates and analyses a repository.

Opt-in: runs only when ODOOFLUX_BENCH=1 (the 300-module run takes minutes). Budgets are not
enforced in P2 (P9 sets them)."""

import os
import tempfile
import unittest
from pathlib import Path

from .bench_analyze import measure
from .generate_repo import generate


@unittest.skipUnless(os.environ.get("ODOOFLUX_BENCH") == "1", "set ODOOFLUX_BENCH=1 to run")
class BenchmarkHarnessTests(unittest.TestCase):
    def test_generates_and_measures_300_modules(self):
        repo = Path(tempfile.mkdtemp()) / "repo"
        generate(repo, 300)
        result = measure(repo)
        self.assertEqual(result["modules"], 300)
        self.assertEqual(result["exit_code"], 1)  # legacy findings present: exit 1 at --fail-on critical
        self.assertGreater(result["wall_seconds"], 0)
        self.assertGreater(result["peak_rss_mib"], 0)


class GeneratorTests(unittest.TestCase):
    def test_generator_is_deterministic_and_small_when_asked(self):
        a = Path(tempfile.mkdtemp())
        b = Path(tempfile.mkdtemp())
        generate(a, 3, seed=7)
        generate(b, 3, seed=7)
        from odooflux.utils.hashing import digest_tree
        self.assertEqual(digest_tree(a), digest_tree(b))
        self.assertGreaterEqual(len(digest_tree(a / "gen_mod_000")), 25)


if __name__ == "__main__":
    unittest.main()
