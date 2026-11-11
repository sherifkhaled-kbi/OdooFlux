"""RC performance fix: while the prover phase runs, one module text is analysed once however many ledger changes cite
it. The cache holds only the watch-independent module analysis and exists only inside `module_view_cache()`; results
are identical with and without it."""

import unittest
from unittest import mock

from odooflux.knowledge.extract import proofs as P

OLD = ("import os\n\ndef old(a):\n    return a + 1\n\ndef other(b):\n    return old(b)\n")
NEW = ("import os\n\ndef new(a):\n    \"\"\"Replaces ``old``.\"\"\"\n    return a + 1\n\ndef other(b):\n    return new(b)\n")
KW = dict(ledger_class="REPLACEMENT_CANDIDATE", source_kind="docs", old="old", new="new",
          from_path="odoo/x/y.py", to_path="odoo/x/y.py", from_text=OLD, to_text=NEW)


class ModuleCacheTests(unittest.TestCase):
    def test_result_is_identical_with_and_without_the_cache(self):
        plain = P.prove(**KW)
        with P.module_view_cache():
            first, second = P.prove(**KW), P.prove(**KW)
        self.assertEqual(plain.witness_digest, first.witness_digest)
        self.assertEqual(first.witness_digest, second.witness_digest)

    def test_refusals_are_identical_too(self):
        bad = dict(KW, from_text="import os\nos.sep = 'x'\n" + OLD)
        plain = P.prove(**bad)
        with P.module_view_cache():
            cached = P.prove(**bad)
        self.assertEqual((plain.code, plain.detail), (cached.code, cached.detail))

    def test_a_module_text_is_parsed_once_inside_the_cache(self):
        with P.module_view_cache():
            with mock.patch.object(P.ast, "parse", wraps=P.ast.parse) as parse:
                for _ in range(5):
                    P.prove(**KW)
                P.function_proofs(NEW, "odoo/x/y.py")
            self.assertEqual(parse.call_count, 2)  # the old and the new text, once each

    def test_without_the_cache_every_call_parses_again(self):
        with mock.patch.object(P.ast, "parse", wraps=P.ast.parse) as parse:
            for _ in range(3):
                P.prove(**KW)
        self.assertEqual(parse.call_count, 6)

    def test_the_cache_is_gone_after_the_block_and_bounded(self):
        with P.module_view_cache(limit=2):
            for i in range(5):
                P.module_facts(f"def f{i}():\n    pass\n", f"odoo/m{i}.py")
            self.assertLessEqual(len(P._cache), 2)
        self.assertIsNone(P._cache)

    def test_watch_dependent_facts_are_not_cached_across_pairs(self):
        text = "import os\nx = os.path.join('old_name', 'new_name')\nfoo(old_name)\n\ndef old_name():\n    return 1\n"
        plain = P.module_facts(text, "odoo/z.py", ("old_name",))
        with P.module_view_cache():
            a = P.module_facts(text, "odoo/z.py", ("old_name",))
            b = P.module_facts(text, "odoo/z.py", ("other",))
        self.assertEqual(plain, a)
        self.assertEqual(b["statement_hits"], [])


if __name__ == "__main__":
    unittest.main()
