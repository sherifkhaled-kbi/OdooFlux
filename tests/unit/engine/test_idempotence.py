"""TST-005-003 (REQ-TRF-003): idempotence_check on an idempotent and a non-idempotent toy rule."""

import unittest

from odooflux.core.engine import documents as docs
from odooflux.core.engine import edits as eng

from .. import _setup  # noqa: F401  (src first on sys.path)


def occurrences(text: str, needle: str) -> list:
    found, start = [], text.find(needle)
    while start != -1:
        found.append(start)
        start = text.find(needle, start + 1)
    return found


class ReplaceFooWithBar:
    """Idempotent: after the fix, no 'foo' remains to detect."""
    rule_id = "toy.foo"
    severity = "WARNING"

    def detect(self, document, context):
        return occurrences(document.text, "foo")

    def fix(self, document, finding, context):
        return [eng.Edit(id=f"{self.rule_id}:{finding}", rule_id=self.rule_id, path=document.path,
                         start=finding, end=finding + 3, before="foo", after="bar",
                         severity=self.severity, step="toy", validation=())]


class DoubleEveryA:
    """Not idempotent: 'a' becomes 'aa', which still contains 'a' and is detected again."""
    rule_id = "toy.grow"
    severity = "WARNING"

    def detect(self, document, context):
        return occurrences(document.text, "a")

    def fix(self, document, finding, context):
        return [eng.Edit(id=f"{self.rule_id}:{finding}", rule_id=self.rule_id, path=document.path,
                         start=finding, end=finding + 1, before="a", after="aa",
                         severity=self.severity, step="toy", validation=())]


class IdempotenceTests(unittest.TestCase):
    def test_idempotent_rule_has_no_second_pass_edits(self):
        doc = docs.Document.from_bytes("m.py", b"foo and foo\n")
        self.assertEqual(eng.idempotence_check([ReplaceFooWithBar()], doc, None), [])

    def test_non_idempotent_rule_reports_second_pass_edits(self):
        doc = docs.Document.from_bytes("m.py", b"abc\n")
        second = eng.idempotence_check([DoubleEveryA()], doc, None)
        self.assertTrue(second)
        self.assertTrue(all(edit.rule_id == "toy.grow" for edit in second))

    def test_check_does_not_mutate_the_document(self):
        doc = docs.Document.from_bytes("m.py", b"foo\n")
        eng.idempotence_check([ReplaceFooWithBar()], doc, None)
        self.assertEqual(doc.text, "foo\n")


if __name__ == "__main__":
    unittest.main()
