"""Release-candidate hardening: S1/S2/S3 proofs refuse modules with unverified module-level side effects.

The proof reads module text, so any import-time statement outside a small explicit safe subset (imports, definitions,
docstring, assignments to plain names from effect-free expressions, allow-listed framework calls) defeats it, whether
or not it mentions the pair.
"""

import unittest

from odooflux.knowledge.extract import proofs as P
from tests.unit.knowledge.kap.test_proofs_hardening import prove, s1_pair

HINT_PAIR = ("    return a + 1\n", "    return a + 1\n")


def s1(extra_to="", extra_from=""):
    old_src, new_src = s1_pair(*HINT_PAIR, module_extra_to=extra_to, module_extra_from=extra_from)
    return prove("REPLACEMENT_CANDIDATE", "old", "new", old_src, new_src)


UNSAFE = [
    "import os\nos.sep = 'x'\n",
    "import os\nos.environ['A'] = 'b'\n",
    "import os\nos.environ.update({'A': 'b'})\n",
    "import os\n_ = os.environ.update({'A': 'b'})\n",
    "import os\nfor _i in range(1):\n    os.sep = 'x'\n",
    "import os\nwith open('f') as _f:\n    pass\n",
    "import os\nif os.name:\n    os.sep = 'x'\n",
    "import os\n_x = (os.system('true'))\n",
    "global_flag = 1\ndel global_flag\n",
    "class C:\n    import os\n    os.sep = 'x'\n",
    "import os\n@os.system('true')\ndef helper():\n    pass\n",
    "import os\ndef helper(a=os.system('true')):\n    pass\n",
]
SAFE = [
    "import logging\n_logger = logging.getLogger(__name__)\n".replace("__name__", "'m'"),
    "from odoo import api, fields, models\n\nclass M(models.Model):\n    _name = 'm'\n"
    "    f = fields.Char(string='x')\n\n    @api.depends('f')\n    def _c(self):\n        pass\n",
    "try:\n    import json\nexcept ImportError:\n    json = None\n",
    "X = 1\nY = (X, 'a')\n",
]


class ModuleEffectTests(unittest.TestCase):
    def test_baseline_proves(self):
        self.assertEqual(s1(), "REPLACEMENT_CONFIRMED")

    def test_unsafe_module_statements_refuse_on_either_side(self):
        for src in UNSAFE:
            for where in ("extra_to", "extra_from"):
                with self.subTest(src=src, where=where):
                    self.assertEqual(s1(**{where: src}), "MODULE_EFFECT")

    def test_safe_subset_still_proves(self):
        for src in SAFE:
            with self.subTest(src=src):
                self.assertEqual(s1(extra_to=src, extra_from=src), "REPLACEMENT_CONFIRMED")

    def test_s3_refuses_effects_too(self):
        old_src = "import os\nos.sep = 'x'\ndef old(a):\n    return a\n"
        self.assertEqual(prove("REMOVED", "old", None, old_src, "X = 1\n"), "MODULE_EFFECT")

    def test_forged_witness_without_effect_fact_is_invalid(self):
        old_src, new_src = s1_pair(*HINT_PAIR)
        proof = P.prove(ledger_class="REPLACEMENT_CANDIDATE", source_kind="docs", old="old", new="new",
                        from_path="odoo/x/y.py", to_path="odoo/x/y.py", from_text=old_src, to_text=new_src)
        w = proof.witness
        del w["to"]["module_effects"]
        self.assertEqual(P.check_witness(w).code, "WITNESS_INVALID")
        w["to"]["module_effects"] = ["Expr"]
        self.assertEqual(P.check_witness(w).code, "MODULE_EFFECT")
        w["to"]["module_effects"] = "none"
        self.assertEqual(P.check_witness(w).code, "WITNESS_INVALID")


if __name__ == "__main__":
    unittest.main()
