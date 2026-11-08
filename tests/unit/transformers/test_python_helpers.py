"""TST-005-006 (REQ-PY-001, REQ-TRF-003): Python edit helpers over the golden corpus.

Each edit case must produce exactly ``expected.py`` through the edit engine, the output must compile,
and a second application must produce zero edits. Non-edit cases must produce zero edits.
"""

import ast
import json
import unittest

from odooflux.core.engine import documents as docs
from odooflux.core.engine import edits as eng
from odooflux.parsers.python import document as pydoc
from odooflux.transformers import python as pyx

from .. import _setup  # noqa: F401  (src first on sys.path)

CORPUS = _setup.REPO / "tests" / "golden_fixtures" / "transformations" / "python"
RULE = "python.test-rule"


def corpus_names():
    return sorted(p.name for p in CORPUS.iterdir() if (p / "meta.json").exists())


def run_ops(parsed, ops):
    edits = []
    for op in ops:
        kind = op["op"]
        if kind == "remove_decorator":
            edits += pyx.remove_decorator(parsed, op["name"], rule_id=RULE)
        elif kind == "remove_keyword":
            edits += pyx.remove_keyword(parsed, op["call"], op["keyword"], rule_id=RULE)
        elif kind == "rename_keyword":
            edits += pyx.rename_keyword(parsed, op["call"], op["keyword"], op["to"], rule_id=RULE)
        elif kind == "replace_call_name":
            edits += pyx.replace_call_name(parsed, op["from"], op["to"], rule_id=RULE)
        elif kind == "replace_attribute":
            edits += pyx.replace_attribute(parsed, op["from"], op["to"], rule_id=RULE)
        else:
            raise AssertionError(f"unknown op {kind}")
    return edits


class PythonHelperCorpusTests(unittest.TestCase):
    def test_corpus_edit_cases_match_expected_output(self):
        for name in corpus_names():
            case = CORPUS / name
            meta = json.loads((case / "meta.json").read_text(encoding="utf-8"))
            if meta["expect"] != "edit":
                continue
            with self.subTest(case=name):
                raw = (case / "input.py").read_bytes()
                expected_raw = (case / "expected.py").read_bytes()
                document = docs.Document.from_bytes(f"{name}.py", raw)
                parsed = pydoc.parse_document(document)
                self.assertIsNone(parsed.parse_error)
                result = eng.apply_edits(document, run_ops(parsed, meta["operations"]), precedence=[RULE])
                self.assertEqual(result.rejected, (), "edits rejected")
                self.assertTrue(result.preserved_ok)
                produced = document.with_text(result.text).encode()
                self.assertEqual(produced, expected_raw)
                ast.parse(result.text)

    def test_corpus_edit_cases_are_idempotent(self):
        for name in corpus_names():
            case = CORPUS / name
            meta = json.loads((case / "meta.json").read_text(encoding="utf-8"))
            if meta["expect"] != "edit":
                continue
            with self.subTest(case=name):
                raw = (case / "input.py").read_bytes()
                document = docs.Document.from_bytes(f"{name}.py", raw)
                first = eng.apply_edits(document, run_ops(pydoc.parse_document(document), meta["operations"]),
                                        precedence=[RULE])
                second_doc = document.with_text(first.text)
                second = run_ops(pydoc.parse_document(second_doc), meta["operations"])
                self.assertEqual(second, [])

    def test_non_edit_cases_produce_no_edits(self):
        for name in corpus_names():
            case = CORPUS / name
            meta = json.loads((case / "meta.json").read_text(encoding="utf-8"))
            if meta["expect"] == "edit":
                continue
            with self.subTest(case=name):
                raw = (case / "input.py").read_bytes()
                parsed = pydoc.parse_document(docs.Document.from_bytes(f"{name}.py", raw))
                self.assertEqual(run_ops(parsed, meta["operations"]), [])
                if meta["expect"] == "reject":
                    self.assertIsNotNone(parsed.parse_error)


class PythonHelperEditShapeTests(unittest.TestCase):
    def test_edits_carry_required_engine_fields(self):
        parsed = pydoc.parse("class A:\n    @api.multi\n    def f(self):\n        pass\n", path="m.py")
        (edit,) = pyx.remove_decorator(parsed, "api.multi", rule_id=RULE)
        self.assertEqual(edit.path, "m.py")
        self.assertEqual(edit.rule_id, RULE)
        self.assertEqual(edit.before, "    @api.multi\n")
        self.assertEqual(edit.after, "")
        self.assertEqual(edit.status, "PLANNED")

    def test_rename_rejects_non_identifier(self):
        parsed = pydoc.parse("f(select=1)\n")
        with self.assertRaises(ValueError):
            pyx.rename_keyword(parsed, "f", "select", "not valid", rule_id=RULE)

    def test_helpers_return_nothing_for_unparsable_source(self):
        parsed = pydoc.parse("def (:\n")
        self.assertEqual(pyx.remove_decorator(parsed, "api.multi", rule_id=RULE), [])


if __name__ == "__main__":
    unittest.main()
