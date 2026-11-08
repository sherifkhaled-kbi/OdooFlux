"""TST-010-005 (T010; REQ-PRF-002, FR-004): an incremental re-run of an unchanged corpus parses 0 files and yields the
same report; the index is invalidated by a content change of one module, a rule-set digest change or a tool-version
change. Fix mode never reads the index."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from . import _support as sup
from odooflux.builtins import build_context
from odooflux.core.orchestrator import incremental
from odooflux.utils import parsecount


def digest(state, corpus) -> str:
    return hashlib.sha256(sup.normalised_json(state, [corpus]).encode("utf-8")).hexdigest()


class IncrementalIndexTests(unittest.TestCase):
    def setUp(self):
        self.corpus = sup.copy_corpus(4)
        self.state_dir = Path(tempfile.mkdtemp())

    def run_once(self, **kwargs):
        index = incremental.open_index(self.state_dir, **kwargs)
        before = parsecount.snapshot()
        _, state = sup.run_analysis(self.corpus, self.state_dir, incremental=index)
        return state, parsecount.snapshot() - before, index

    def test_unchanged_rerun_parses_zero_files_and_reports_the_same(self):
        first, parsed_first, _ = self.run_once()
        self.assertGreater(parsed_first, 0)
        second, parsed_second, index = self.run_once()
        self.assertEqual(parsed_second, 0)
        self.assertEqual(index.stats["skipped"], 4)
        self.assertEqual(index.stats["analyzed"], 0)
        self.assertEqual(digest(first, self.corpus), digest(second, self.corpus))

    def test_incremental_report_equals_a_fresh_report(self):
        self.run_once()
        incr, _, _ = self.run_once()
        _, fresh = sup.run_analysis(self.corpus, tempfile.mkdtemp())
        self.assertEqual(digest(incr, self.corpus), digest(fresh, self.corpus))

    def test_changed_module_is_reanalysed_and_others_are_not(self):
        self.run_once()
        target = self.corpus / "gen_mod_001" / "models" / "m0.py"
        target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
        state, parsed, index = self.run_once()
        self.assertGreater(parsed, 0)
        self.assertEqual((index.stats["analyzed"], index.stats["skipped"]), (1, 3))
        _, fresh = sup.run_analysis(self.corpus, tempfile.mkdtemp())
        self.assertEqual(digest(state, self.corpus), digest(fresh, self.corpus))

    def test_ruleset_digest_change_invalidates(self):
        self.run_once()
        _, parsed, index = self.run_once(ruleset_digest="a-different-rule-set")
        self.assertGreater(parsed, 0)
        self.assertEqual(index.stats["skipped"], 0)

    def test_tool_version_change_invalidates(self):
        self.run_once(tool_version="0.0.1")
        _, parsed_same, _ = self.run_once(tool_version="0.0.1")
        self.assertEqual(parsed_same, 0)
        _, parsed, index = self.run_once(tool_version="0.0.2")
        self.assertGreater(parsed, 0)
        self.assertEqual(index.stats["skipped"], 0)

    def test_new_file_in_a_module_invalidates_that_module(self):
        self.run_once()
        (self.corpus / "gen_mod_000" / "models" / "extra.py").write_text("x = 1\n", encoding="utf-8")
        _, parsed, index = self.run_once()
        self.assertGreater(parsed, 0)
        self.assertEqual(index.stats["analyzed"], 1)

    def test_fix_mode_never_uses_the_index(self):
        self.run_once()
        index = incremental.open_index(self.state_dir)
        _, state = sup.run_analysis(self.corpus, self.state_dir, mode="fix", incremental=index)
        self.assertEqual(index.stats, {"analyzed": 0, "skipped": 0})
        self.assertTrue(all(m["status"] in ("PROMOTED", "DONE", "FAILED", "BLOCKED") for m in state["modules"]))

    def test_corrupt_index_is_ignored_not_trusted(self):
        self.run_once()
        index_file = incremental.index_path(self.state_dir)
        index_file.write_text("{not json", encoding="utf-8")
        _, parsed, index = self.run_once()
        self.assertGreater(parsed, 0)
        self.assertEqual(index.stats["skipped"], 0)


class DigestTests(unittest.TestCase):
    def test_ruleset_digest_depends_on_rule_maturity_and_params(self):
        class Rule:
            def __init__(self, key, maturity, params=None):
                self.key, self.step, self.maturity, self.evidence = key, "17-18", maturity, ("EV-1",)
                self.review_required, self.fixes, self.params = False, False, params or {}

        ctx = build_context()
        a = incremental.ruleset_digest([Rule("r1", "DETECT_ONLY")], [], ctx.registries)
        b = incremental.ruleset_digest([Rule("r1", "FIX_ENABLED")], [], ctx.registries)
        c = incremental.ruleset_digest([Rule("r1", "DETECT_ONLY")], [], ctx.registries)
        self.assertNotEqual(a, b)
        self.assertEqual(a, c)

    def test_tool_digest_is_stable_and_versioned(self):
        self.assertEqual(incremental.tool_digest("1"), incremental.tool_digest("1"))
        self.assertNotEqual(incremental.tool_digest("1"), incremental.tool_digest("2"))


if __name__ == "__main__":
    unittest.main()
