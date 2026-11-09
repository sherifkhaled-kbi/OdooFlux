"""Feature 012 addendum F1: static soundness proofs (`knowledge/extract/proofs.py`). Stdlib unittest only.

Every F1 clause has a positive case and a refusal case. Refusals must return a Refusal with the exact reason code; a
proof is never returned for an ambiguous pair. The witness must stay structural (no source text), and the proof must
be deterministic.
"""

import ast
import sys
import textwrap
import unittest
from pathlib import Path

from odooflux.knowledge.extract import proofs as P

REPO = Path(__file__).resolve().parents[4]
PROOFS_PY = REPO / "src" / "odooflux" / "knowledge" / "extract" / "proofs.py"
PATH = "odoo/tools/helpers.py"

S1_HEAD = "def old_fn(x, digits=0):\n    \"\"\"Old.\"\"\"\n"
S1_NEW_HEAD = "def new_fn(x, digits=0):\n    \"\"\"Round.\n\n    Replaces ``old_fn``\n    \"\"\"\n"
BODY = "    return round(x, digits) + 0\n"


def _run(cls, old_src, new_src, *, old="old_fn", new="new_fn", source="docs", from_path=PATH, to_path=PATH):
    if cls == "REMOVED":
        new = None
    if cls != "REPLACEMENT_CANDIDATE":
        source = None  # a hint source belongs to replacement candidates only
    return P.prove(ledger_class=cls, source_kind=source, old=old, new=new, from_path=from_path, to_path=to_path,
                   from_text=textwrap.dedent(old_src), to_text=textwrap.dedent(new_src))


def _s1(old_src, new_src, **kw):
    return _run("REPLACEMENT_CANDIDATE", old_src, new_src, **kw)


def _s1_pair(old_extra="", new_extra="", old_body=BODY, new_body=BODY, old_head=S1_HEAD, new_head=S1_NEW_HEAD):
    return (old_extra + old_head + old_body, new_extra + new_head + new_body)


def _alias_pair(alias_body, *, new_head="def legacy(a, b):\n", new_sum_src="def new_sum(a, b):\n    return a + b\n",
                extra_to=""):
    """FROM: legacy has its own implementation. TO: legacy is the alias body under test."""
    old = "import warnings\n" + "def new_sum(a, b):\n    return a + b\n" + "def legacy(a, b):\n    return a + b\n"
    new = "import warnings\n" + new_sum_src + extra_to + new_head + alias_body
    return old, new


WARN = "    warnings.warn(\"legacy\", DeprecationWarning, stacklevel=2)\n"


def _assert_refused(test, result, code):
    test.assertIsInstance(result, P.Refusal, f"expected refusal {code}, got {result!r}")
    test.assertEqual(result.code, code)


class PositiveProofs(unittest.TestCase):
    def test_s1_identical_bodies_with_official_hint(self):
        old, new = _s1_pair()
        result = _s1(old, new)
        self.assertIsInstance(result, P.Proof)
        self.assertEqual(result.derived_class, "REPLACEMENT_CONFIRMED")
        self.assertEqual(result.derived_params, {"module": "odoo.tools.helpers", "old": "old_fn", "new": "new_fn"})

    def test_s1_import_shared_by_both_versions_is_allowed(self):
        old, new = _s1_pair(old_extra="import math\n", new_extra="import math\n",
                            old_body="    return math.floor(x) + digits\n", new_body="    return math.floor(x) + digits\n")
        self.assertEqual(_s1(old, new).derived_class, "REPLACEMENT_CONFIRMED")

    def test_s1_comprehension_variable_is_local(self):
        old, new = _s1_pair(old_body="    return [i * digits for i in x]\n", new_body="    return [i * digits for i in x]\n")
        self.assertEqual(_s1(old, new).derived_class, "REPLACEMENT_CONFIRMED")

    def test_s2_alias_with_deprecation_warning(self):
        old, new = _alias_pair(WARN + "    return new_sum(a, b)\n")
        result = _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum")
        self.assertEqual(result.derived_class, "DELEGATING_ALIAS")
        self.assertEqual(result.derived_params, {"module": "odoo.tools.helpers", "old": "legacy", "new": "new_sum"})

    def test_s2_alias_without_warning_and_with_star_forwarding(self):
        old = ("def new_sum(*args, **kw):\n    return sum(args) + kw.get('x', 0)\n"
               "def legacy(*args, **kw):\n    return new_sum(*args, **kw)\n")
        new = ("def new_sum(*args, **kw):\n    return sum(args) + kw.get('x', 0)\n"
               "def legacy(*args, **kw):\n    return new_sum(*args, **kw)\n")
        result = _run("DEPRECATED", old, new, old="legacy", new="new_sum")
        self.assertEqual(result.derived_class, "DELEGATING_ALIAS")

    def test_s3_identity_decorator_removed(self):
        old = "def multi(method):\n    return method\n\ndef other(x):\n    return x\n"
        new = "def other(x):\n    return x\n"
        result = _run("REMOVED", old, new, old="multi")
        self.assertEqual(result.derived_class, "IDENTITY_DECORATOR_REMOVED")
        self.assertEqual(result.derived_params, {"module": "odoo.tools.helpers", "name": "multi"})


class ScopeAndNames(unittest.TestCase):
    def test_module_name_rules(self):
        self.assertEqual(P.module_name("odoo/x/y.py"), "odoo.x.y")
        self.assertEqual(P.module_name("odoo/x/__init__.py"), "odoo.x")
        self.assertEqual(P.module_name("odoo/addons/sale/models/a.py"), "odoo.addons.sale.models.a")
        self.assertIsNone(P.module_name("odoo/bad-name.py"))
        self.assertIsNone(P.module_name("odoo/x/y.txt"))
        self.assertIsNone(P.module_name("odoo//y.py"))

    def test_module_mismatch_refused(self):
        old, new = _s1_pair()
        _assert_refused(self, _run("REPLACEMENT_CANDIDATE", old, new, from_path=PATH, to_path="odoo/tools/other.py"),
                        "MODULE_MISMATCH")

    def test_keyword_name_refused(self):
        old, new = _s1_pair()
        _assert_refused(self, _run("REPLACEMENT_CANDIDATE", old, new, old="class", new="new_fn"), "NAME_INVALID")

    def test_same_name_refused(self):
        old, new = _s1_pair()
        _assert_refused(self, _run("REPLACEMENT_CANDIDATE", old, new, old="old_fn", new="old_fn"), "NAME_INVALID")

    def test_parse_failure_refused(self):
        old, _ = _s1_pair()
        _assert_refused(self, _run("REPLACEMENT_CANDIDATE", old, "def new_fn(:\n"), "PARSE_FAILED")

    def test_unknown_ledger_class_refused(self):
        old, new = _s1_pair()
        _assert_refused(self, _run("RENAMED_CANDIDATE", old, new), "UNSUPPORTED_CLASS")

    def test_similarity_only_rename_is_not_a_replacement(self):
        # identical bodies but no official hint: a score never qualifies
        old, new = _s1_pair(new_head="def new_fn(x, digits=0):\n    return round(x, digits) + 0\n")
        _assert_refused(self, _run("REPLACEMENT_CANDIDATE", old, new, source=None), "LEDGER_SOURCE")

    def test_hint_must_name_old(self):
        old, new = _s1_pair(new_head="def new_fn(x, digits=0):\n    \"\"\"Round.\"\"\"\n")
        _assert_refused(self, _s1(old, new), "S1_HINT_MISSING")

    def test_hint_from_score_refused(self):
        old, new = _s1_pair()
        _assert_refused(self, _s1(old, new, source="score"), "LEDGER_SOURCE")


class S1Refusals(unittest.TestCase):
    def test_shadowed_old_name_in_new_version_refused(self):
        old, new = _s1_pair(new_extra="old_fn = None\n")
        _assert_refused(self, _s1(old, new), "BINDING_CONFLICT")

    def test_old_still_defined_in_new_version_refused(self):
        old, new = _s1_pair()
        new = new + "\n" + S1_HEAD + BODY
        _assert_refused(self, _s1(old, new), "BINDING_CONFLICT")

    def test_rebound_name_in_old_version_refused(self):
        old, new = _s1_pair(old_extra="def old_fn(x):\n    return x\n")
        _assert_refused(self, _s1(old, new), "BINDING_CONFLICT")

    def test_old_listed_in_all_refused(self):
        old, new = _s1_pair(new_extra="__all__ = ['old_fn']\n")
        _assert_refused(self, _s1(old, new), "BINDING_CONFLICT")

    def test_star_import_refused(self):
        old, new = _s1_pair(new_extra="from os.path import *\n")
        _assert_refused(self, _s1(old, new), "STAR_IMPORT")

    def test_module_getattr_refused(self):
        old, new = _s1_pair(new_extra="def __getattr__(name):\n    raise AttributeError(name)\n")
        _assert_refused(self, _s1(old, new), "MODULE_GETATTR")

    def test_differing_body_refused(self):
        old, new = _s1_pair(new_body="    return round(x, digits) + 1\n")
        _assert_refused(self, _s1(old, new), "S1_NOT_IDENTICAL")

    def test_differing_default_refused(self):
        old, new = _s1_pair(new_head="def new_fn(x, digits=2):\n    \"\"\"Round.\n\n    Replaces ``old_fn``\n    \"\"\"\n")
        _assert_refused(self, _s1(old, new), "S1_NOT_IDENTICAL")

    def test_keyword_rename_refused(self):
        old, new = _s1_pair(new_head="def new_fn(x, ndigits=0):\n    \"\"\"Round.\n\n    Replaces ``old_fn``\n    \"\"\"\n",
                            new_body="    return round(x, ndigits) + 0\n")
        _assert_refused(self, _s1(old, new), "S1_NOT_IDENTICAL")

    def test_method_attribute_change_refused(self):
        old, new = _s1_pair(old_body="    return x.old_fn(digits)\n", new_body="    return x.new_fn(digits)\n")
        _assert_refused(self, _s1(old, new), "S1_NOT_IDENTICAL")

    def test_module_constant_not_shared_refused(self):
        old, new = _s1_pair(old_extra="FACTOR = 10\n", new_extra="FACTOR = 100\n",
                            old_body="    return x * FACTOR\n", new_body="    return x * FACTOR\n")
        _assert_refused(self, _s1(old, new), "S1_GLOBAL_REF")

    def test_recursion_by_name_refused(self):
        old, new = _s1_pair(old_body="    return old_fn(x) if digits else x\n",
                            new_body="    return old_fn(x) if digits else x\n")
        _assert_refused(self, _s1(old, new), "S1_GLOBAL_REF")

    def test_import_with_different_alias_refused(self):
        old, new = _s1_pair(old_extra="import math\n", new_extra="import math as m\n",
                            old_body="    return math.floor(x)\n", new_body="    return math.floor(x)\n")
        _assert_refused(self, _s1(old, new), "S1_GLOBAL_REF")

    def test_builtin_shadowed_by_module_refused(self):
        old, new = _s1_pair(new_extra="def round(v, n=0):\n    return v\n")
        _assert_refused(self, _s1(old, new), "S1_GLOBAL_REF")

    def test_global_declaration_refused(self):
        old, new = _s1_pair(old_body="    global COUNTER\n    return x\n", new_body="    global COUNTER\n    return x\n")
        _assert_refused(self, _s1(old, new), "NOT_PLAIN_DEF")

    def test_decorator_with_side_effects_refused(self):
        old, new = _s1_pair(old_head="@register\n" + S1_HEAD)
        _assert_refused(self, _s1(old, new), "NOT_PLAIN_DEF")

    def test_async_refused(self):
        old, new = _s1_pair(old_head="async " + S1_HEAD)
        _assert_refused(self, _s1(old, new), "NOT_PLAIN_DEF")

    def test_nested_definition_named_new_refused(self):
        old, new = _s1_pair(new_extra="def helper():\n    def new_fn():\n        return 1\n    return new_fn\n")
        _assert_refused(self, _s1(old, new), "NESTED_DEFINITION")

    def test_class_method_named_old_is_not_a_top_level_function(self):
        old = "class Model:\n    def old_fn(self, x):\n        return x\n"
        new = "def new_fn(x):\n    \"\"\"Replaces ``old_fn``\"\"\"\n    return x\n"
        _assert_refused(self, _s1(old, new), "NESTED_DEFINITION")


class S2Refusals(unittest.TestCase):
    def test_signature_mismatch_refused(self):
        old, new = _alias_pair(WARN + "    return new_sum(a, b)\n", new_head="def legacy(a, b=1):\n")
        _assert_refused(self, _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum"), "S2_SIGNATURE")

    def test_extra_statement_is_not_an_alias(self):
        old, new = _alias_pair("    total = 0\n    return new_sum(a, b)\n")
        _assert_refused(self, _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum"), "S2_NOT_ALIAS")

    def test_reordered_forward_refused(self):
        old, new = _alias_pair("    return new_sum(b, a)\n")
        _assert_refused(self, _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum"), "S2_NOT_ALIAS")

    def test_extra_argument_forward_refused(self):
        old, new = _alias_pair("    return new_sum(a, b, 1)\n")
        _assert_refused(self, _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum"), "S2_NOT_ALIAS")

    def test_forward_to_other_function_refused(self):
        old, new = _alias_pair("    return other(a, b)\n", extra_to="def other(a, b):\n    return a\n")
        _assert_refused(self, _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum"), "S2_NOT_ALIAS")

    def test_chain_of_aliases_refused(self):
        old, new = _alias_pair("    return new_sum(a, b)\n", new_sum_src="def new_sum(a, b):\n    return inner(a, b)\n",
                               extra_to="def inner(a, b):\n    return a + b\n")
        _assert_refused(self, _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum"), "S2_CHAIN")

    def test_cycle_refused(self):
        old, new = _alias_pair("    return new_sum(a, b)\n", new_sum_src="def new_sum(a, b):\n    return legacy(a, b) + 0\n")
        _assert_refused(self, _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum"), "S2_CYCLE")

    def test_warning_with_non_constant_message_refused(self):
        body = "    warnings.warn(MSG, DeprecationWarning)\n    return new_sum(a, b)\n"
        old, new = _alias_pair(body, extra_to="MSG = 'x'\n")
        _assert_refused(self, _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum"), "S2_NOT_ALIAS")

    def test_async_alias_refused(self):
        old, new = _alias_pair("    return new_sum(a, b)\n", new_head="async def legacy(a, b):\n")
        _assert_refused(self, _run("BEHAVIOUR_CHANGED", old, new, old="legacy", new="new_sum"), "NOT_PLAIN_DEF")


class S3Refusals(unittest.TestCase):
    def test_identity_with_extra_work_refused(self):
        old = "def multi(method):\n    method.wrapped = True\n    return method\n"
        _assert_refused(self, _run("REMOVED", old, "x = 1\n", old="multi"), "S3_NOT_IDENTITY")

    def test_identity_with_default_refused(self):
        old = "def multi(method=None):\n    return method\n"
        _assert_refused(self, _run("REMOVED", old, "x = 1\n", old="multi"), "S3_NOT_IDENTITY")

    def test_still_bound_by_assignment_refused(self):
        old = "def multi(method):\n    return method\n"
        _assert_refused(self, _run("REMOVED", old, "multi = None\n", old="multi"), "S3_STILL_BOUND")

    def test_still_bound_by_import_refused(self):
        old = "def multi(method):\n    return method\n"
        _assert_refused(self, _run("REMOVED", old, "from api import multi\n", old="multi"), "S3_STILL_BOUND")

    def test_decorated_identity_refused(self):
        old = "@keep\ndef multi(method):\n    return method\n"
        _assert_refused(self, _run("REMOVED", old, "x = 1\n", old="multi"), "NOT_PLAIN_DEF")

    def test_replacement_name_with_removed_class_refused(self):
        old = "def multi(method):\n    return method\n"
        result = P.prove(ledger_class="REMOVED", old="multi", new="other", from_path=PATH, to_path=PATH,
                         from_text=old, to_text="x = 1\n")
        _assert_refused(self, result, "NAME_INVALID")


class WitnessAndScope(unittest.TestCase):
    def test_nested_definition_of_watched_name_in_old_version_refused(self):
        old, new = _s1_pair(old_extra="def wrap():\n    def old_fn():\n        return 1\n    return old_fn\n")
        _assert_refused(self, _s1(old, new), "NESTED_DEFINITION")

    def test_witness_holds_no_source_text(self):
        old, new = _s1_pair(new_extra="import math\n", old_extra="import math\n",
                            old_body="    return math.floor(x) + digits\n", new_body="    return math.floor(x) + digits\n")
        result = _s1(old, new)
        for text in P._strings(result.witness):
            self.assertIsNone(P._SOURCE_HINT.search(text), text)
        self.assertNotIn("floor", repr(result.witness))

    def test_witness_containing_source_text_refused(self):
        old, new = _s1_pair()
        witness = _s1(old, new).witness
        witness["from"]["defs"]["old_fn"]["free_names"] = ["return x"]
        _assert_refused(self, P.check_witness(witness), "WITNESS_SOURCE_TEXT")

    def test_witness_with_extra_key_refused(self):
        witness = _s1(*_s1_pair()).witness
        witness["body"] = "return x"
        _assert_refused(self, P.check_witness(witness), "WITNESS_INVALID")

    def test_witness_digest_is_deterministic(self):
        old, new = _s1_pair()
        self.assertEqual(_s1(old, new).witness_digest, _s1(old, new).witness_digest)

    def test_tampered_witness_fact_is_refused(self):
        old, new = _s1_pair()
        witness = _s1(old, new).witness
        witness["to"]["bindings"]["old_fn"] = ["def"]
        _assert_refused(self, P.check_witness(witness), "BINDING_CONFLICT")

    def test_extractor_proof_fields_exist_and_are_stable(self):
        old, new = _s1_pair()
        first = P.function_proofs(old, PATH)
        self.assertEqual(first, P.function_proofs(old, PATH))
        self.assertEqual(set(first["old_fn"]), {
            "module", "def_digest", "free_names", "import_digests", "top_level_bindings_digest", "is_async",
            "forward_shape", "identity_shape", "docstring_replaces", "signature", "decorator_count", "nested_scope",
            "declares_global", "star_import", "module_getattr"})
        self.assertEqual(P.function_proofs(new, PATH)["new_fn"]["def_digest"], first["old_fn"]["def_digest"])

    def test_extractor_refuses_unparsable_or_unscoped_files(self):
        self.assertIsNone(P.function_proofs("def f(:\n", PATH))
        self.assertIsNone(P.function_proofs("x = 1\n", "odoo/bad-name.py"))

    def test_proofs_module_imports_stay_stdlib_or_odooflux(self):
        tree = ast.parse(PROOFS_PY.read_text(encoding="utf-8"))
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.append(node.module or "")
        for name in names:
            top = name.split(".")[0]
            self.assertTrue(top == "odooflux" or top in sys.stdlib_module_names, name)
        self.assertNotIn("parsers", " ".join(names))
        self.assertNotIn("transformers", " ".join(names))


if __name__ == "__main__":
    unittest.main()
