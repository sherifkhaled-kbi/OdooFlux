"""Feature 012 hardening (review item 5): the static soundness proofs refuse what they cannot see.

S1 refuses reflective or namespace-changing code anywhere in the module; S2 refuses non-immutable default values (they
are evaluated at definition time, separately for each function); S1, S2 and S3 refuse module-level statements, other
than imports, definitions, docstrings and simple constant assignments, that mention the old or the new name, and refuse
any module that touches the reflective names on the S1 and S3 paths. The derived witness carries `proof_side`, the side
whose file carries the proof, which L1 binds to the evidence location.
"""

import unittest

from odooflux.knowledge.extract import proofs as P

S1_HINT = '"""Replaces ``old``."""\n'


def prove(cls, old, new, from_text, to_text, *, source_kind=None, from_path="odoo/x/y.py", to_path="odoo/x/y.py"):
    if source_kind is None and cls == "REPLACEMENT_CANDIDATE":
        source_kind = "docs"
    result = P.prove(ledger_class=cls, source_kind=source_kind, old=old, new=None if cls == "REMOVED" else new,
                     from_path=from_path, to_path=to_path, from_text=from_text, to_text=to_text)
    return result.code if isinstance(result, P.Refusal) else result.derived_class


def s1_pair(from_body, to_body, module_extra_to="", module_extra_from=""):
    old_src = module_extra_from + "def old(a):\n" + from_body
    new_src = module_extra_to + "def new(a):\n    " + S1_HINT.strip() + "\n" + to_body
    return old_src, new_src


class S1ReflectionTests(unittest.TestCase):
    def test_plain_identical_bodies_still_prove(self):
        old_src, new_src = s1_pair("    return a + 1\n", "    return a + 1\n")
        self.assertEqual(prove("REPLACEMENT_CANDIDATE", "old", "new", old_src, new_src), "REPLACEMENT_CONFIRMED")

    def test_locals_and_globals_in_a_body_refuse(self):
        for name in ("locals", "globals", "vars"):
            with self.subTest(name=name):
                old_src, new_src = s1_pair(f"    return {name}()\n", f"    return {name}()\n")
                self.assertEqual(prove("REPLACEMENT_CANDIDATE", "old", "new", old_src, new_src), "S1_REFLECTIVE")

    def test_sys_frame_and_dunder_references_refuse(self):
        # `__file__`, `__name__` and `__builtins__` are free names too, so S1_GLOBAL_REF may answer first; either is
        # a refusal of the pair
        cases = ["    import sys\n    return sys._getframe(1)\n",
                 "    return __file__\n",
                 "    return __name__\n",
                 "    return __builtins__\n"]
        for body in cases:
            with self.subTest(body=body):
                old_src, new_src = s1_pair(body, body)
                self.assertIn(prove("REPLACEMENT_CANDIDATE", "old", "new", old_src, new_src),
                              ("S1_REFLECTIVE", "S1_GLOBAL_REF"))

    def test_reflection_elsewhere_in_the_module_refuses_s1(self):
        # module-wide: a helper in the same module can rebind or inspect the pair
        old_src, new_src = s1_pair("    return a + 1\n", "    return a + 1\n",
                                   module_extra_to="import inspect\n")
        self.assertEqual(prove("REPLACEMENT_CANDIDATE", "old", "new", old_src, new_src), "S1_REFLECTIVE")

    def test_getattr_and_eval_refuse(self):
        for body in ("    return getattr(a, 'x')\n", "    return eval('a')\n", "    return exec('a=1')\n"):
            with self.subTest(body=body):
                old_src, new_src = s1_pair(body, body)
                self.assertEqual(prove("REPLACEMENT_CANDIDATE", "old", "new", old_src, new_src), "S1_REFLECTIVE")


class ModuleStatementTests(unittest.TestCase):
    def test_registering_the_old_function_at_module_level_refuses_s1(self):
        # t6: REG.append(old) mentions the old name at module level (the registry sees the pair differently)
        old_src = "def old(a):\n    return a\nREG.append(old)\n"
        new_src = '"""x."""\ndef new(a):\n    """Replaces ``old``."""\n    return a\nREG.append(new)\n'
        self.assertEqual(prove("REPLACEMENT_CANDIDATE", "old", "new", old_src, new_src), "MODULE_STATEMENT")

    def test_setattr_on_the_old_name_refuses_s3(self):
        # t6: `old.x = 1` at module level, in the FROM version
        self.assertEqual(prove("REMOVED", "old", None, "def old(p):\n    return p\nold.x = 1\n", "X = 1\n"),
                         "MODULE_STATEMENT")

    def test_globals_mutation_of_the_old_name_refuses_s3(self):
        # t6 / t2: rebinding through globals() is reflection in the TO module
        self.assertEqual(prove("REMOVED", "old", None, "def old(p):\n    return p\n",
                               "globals()['old'] = wrap\n"), "S3_REFLECTIVE")

    def test_exec_rebinding_the_name_in_the_target_refuses_s3(self):
        self.assertEqual(prove("REMOVED", "old", None, "def old(p):\n    return p\n", "exec('old = 1')\n"),
                         "S3_REFLECTIVE")

    def test_setattr_rebinding_the_name_in_the_target_refuses_s3(self):
        self.assertEqual(prove("REMOVED", "old", None, "def old(p):\n    return p\n",
                               "import sys\nsetattr(sys.modules[__name__], 'old', 1)\n"), "S3_REFLECTIVE")

    def test_simple_constant_assignment_is_still_allowed(self):
        self.assertEqual(prove("REMOVED", "old", None, "def old(p):\n    return p\n", "X = 1\nLABEL = 'x'\n"),
                         "IDENTITY_DECORATOR_REMOVED")


class S2DefaultTests(unittest.TestCase):
    def test_mutable_default_refuses_s2(self):
        # t2 s2_defaults_mutable: each function gets its own list object, so the alias is not the same behaviour
        base = "def old(a=[]):\n    return new(a)\n"
        new_src = "def new(a=[]):\n    a.append(1)\n    return a\n"
        new_src += "def old(a=[]):\n    return new(a)\n"
        self.assertEqual(prove("BEHAVIOUR_CHANGED", "old", "new", base, new_src), "S2_DEFAULT_NOT_IMMUTABLE")

    def test_call_default_refuses_s2(self):
        base = "import time\ndef old(a=time.time()):\n    return new(a)\n"
        new_src = "import time\ndef new(a=time.time()):\n    return a\ndef old(a=time.time()):\n    return new(a)\n"
        self.assertEqual(prove("BEHAVIOUR_CHANGED", "old", "new", base, new_src), "S2_DEFAULT_NOT_IMMUTABLE")

    def test_immutable_literal_defaults_still_prove(self):
        base = "def old(a, b=2, k=(1, 'x'), *, m=None):\n    return new(a, b, k, m=m)\n"
        new_src = ("def new(a, b=2, k=(1, 'x'), *, m=None):\n    return (a, b, k, m)\n"
                   "def old(a, b=2, k=(1, 'x'), *, m=None):\n    return new(a, b, k, m=m)\n")
        self.assertEqual(prove("BEHAVIOUR_CHANGED", "old", "new", base, new_src), "DELEGATING_ALIAS")


class ProofSideTests(unittest.TestCase):
    def test_witness_names_the_side_that_carries_the_proof(self):
        old_src, new_src = s1_pair("    return a + 1\n", "    return a + 1\n")
        result = P.prove(ledger_class="REPLACEMENT_CANDIDATE", source_kind="docs", old="old", new="new",
                         from_path="odoo/x/y.py", to_path="odoo/x/y.py", from_text=old_src, to_text=new_src)
        self.assertEqual(result.witness["proof_side"], "to")
        removed = P.prove(ledger_class="REMOVED", old="old", from_path="odoo/x/y.py", to_path="odoo/x/y.py",
                          from_text="def old(p):\n    return p\n", to_text="X = 1\n")
        self.assertEqual(removed.witness["proof_side"], "from")

    def test_a_witness_with_the_wrong_proof_side_is_refused(self):
        old_src, new_src = s1_pair("    return a + 1\n", "    return a + 1\n")
        result = P.prove(ledger_class="REPLACEMENT_CANDIDATE", source_kind="docs", old="old", new="new",
                         from_path="odoo/x/y.py", to_path="odoo/x/y.py", from_text=old_src, to_text=new_src)
        forged = dict(result.witness, proof_side="from")
        self.assertIsInstance(P.check_witness(forged), P.Refusal)


if __name__ == "__main__":
    unittest.main()
