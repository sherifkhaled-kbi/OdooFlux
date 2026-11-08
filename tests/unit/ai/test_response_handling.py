"""TST-007-007 (REQ-AI-003, REQ-AI-005, FR-005): each rejection has its documented reason code."""

import json
import unittest

from . import _helpers as h
from odooflux.ai.escalation import review_response
from odooflux.ai.prompts.builder import select_region
from odooflux.ai.providers.types import AIResponse, Usage, error_response, parse_structured
from odooflux.core.engine.documents import Document

PY = h.corpus("sample_models.py.txt")
LINE = next(i for i, ln in enumerate(PY.splitlines(), 1) if "def f_ok" in ln) + 1
CLS = h.corpus("legacy_class.py.txt")
GOOD = "    def f_ok(self):\n        return new_api(self.name)\n"


def resp(replacement, **kw):
    text = json.dumps({"replacement": replacement, "notes": "", "cannot_fix": kw.pop("cannot_fix", False)})
    return AIResponse(text=text, parsed=parse_structured(text), usage=Usage(10, 5), **kw)


def review(response, text=PY, line=LINE, validate=h.python_validate):
    region = select_region("m.py", text, line)
    doc = Document.from_text("m.py", text)
    return review_response(response, region, doc, provider="fake", model="fake-model", step="s",
                           finding_ids=("f1",), validate=validate)


class ResponseHandlingTests(unittest.TestCase):
    def test_accepted_builds_edit_with_ai_rule_id(self):
        v = review(resp(GOOD))
        self.assertEqual((v.outcome, v.reason), ("accepted", ""))
        self.assertEqual(v.edit.rule_id, "ai:fake/fake-model")
        self.assertEqual(v.edit.before, "    def f_ok(self):\n        return old_api(self.name)\n")
        self.assertEqual(v.edit.after, GOOD)
        self.assertEqual(v.edit.finding_ids, ("f1",))

    def test_truncated(self):
        v = review(resp(GOOD, stop_reason="max_tokens"))
        self.assertEqual(v.outcome, "rejected:truncated")
        self.assertIsNone(v.edit)

    def test_provider_error(self):
        self.assertEqual(review(error_response("rate_limit")).outcome, "error:rate_limit")

    def test_schema_mismatch(self):
        r = AIResponse(text='{"replacement": 5}', parsed=None)
        self.assertEqual(review(r).outcome, "rejected:schema_mismatch")
        self.assertEqual(review(AIResponse(text="no json at all", parsed=None)).outcome,
                         "rejected:schema_mismatch")

    def test_cannot_fix_is_skipped_not_rejected(self):
        self.assertEqual(review(resp("", cannot_fix=True)).outcome, "skipped:model_declined")

    def test_syntax_invalid(self):
        v = review(resp("    def f_ok(self):\n        return new_api(self.name\n"))
        self.assertEqual(v.outcome, "rejected:syntax_invalid")

    def test_out_of_region_extra_definition(self):
        v = review(resp(GOOD + "\n    def sneaky(self):\n        return 2\n"))
        self.assertEqual(v.outcome, "rejected:out_of_region")

    def test_out_of_region_renamed_function(self):
        v = review(resp(GOOD.replace("f_ok", "g_ok")))
        self.assertEqual(v.outcome, "rejected:out_of_region")

    def test_protected_identifier_changed(self):
        line = next(i for i, ln in enumerate(CLS.splitlines(), 1) if "legacy_defaults" in ln)
        renamed = ('class Legacy(models.Model):\n    _name = "kbi.renamed"\n    _inherit = ["mail.thread"]\n\n'
                   '    name = fields.Char()\n')
        v = review(resp(renamed), text=CLS, line=line)
        self.assertEqual(v.outcome, "rejected:protected_identifier_changed")

    def test_no_change_is_rejected(self):
        self.assertEqual(review(resp("    def f_ok(self):\n        return old_api(self.name)\n")).outcome,
                         "rejected:no_change")

    def test_before_text_mismatch_when_document_moved_on(self):
        region = select_region("m.py", PY, LINE)
        moved = Document.from_text("m.py", PY.replace("return old_api(self.name)\n\n    def f_syntax",
                                                       "return old_api(self.name) # x\n\n    def f_syntax"))
        v = review_response(resp(GOOD), region, moved, provider="fake", model="fake-model", step="s",
                            finding_ids=("f1",), validate=h.python_validate)
        self.assertEqual(v.outcome, "rejected:before_text_mismatch")

    def test_validation_failure_names_the_validator(self):
        v = review(resp(GOOD), validate=lambda p, t: ("xml-syntax", "bad"))
        self.assertEqual(v.outcome, "rejected:validation_failed:xml-syntax")

    def test_fixture_scripts_cover_documented_codes(self):
        # the scripted fixtures feed the fake provider in the integration tests
        for name in ("mixed", "truncated", "protected", "syntax"):
            self.assertTrue(h.script(name)["entries"])


class RetryBoundTests(unittest.TestCase):
    def test_rate_limit_retries_are_bounded(self):
        from odooflux.ai.providers.transport import call_with_retries
        calls = []

        def attempt():
            calls.append(1)
            return error_response("rate_limit")
        sleeps = []
        result = call_with_retries(attempt, max_retries=2, sleep=sleeps.append)
        self.assertEqual(len(calls), 3)  # one try + 2 retries, never more
        self.assertEqual(result.error_kind, "rate_limit")
        self.assertEqual(sleeps, [1.0, 2.0])  # exponential backoff

    def test_non_transient_errors_are_not_retried(self):
        from odooflux.ai.providers.transport import call_with_retries
        for kind in ("auth", "invalid_request", "unknown"):
            calls = []
            call_with_retries(lambda: (calls.append(1), error_response(kind))[1], max_retries=5, sleep=lambda s: None)
            self.assertEqual(len(calls), 1, kind)

    def test_transient_then_success(self):
        from odooflux.ai.providers.transport import call_with_retries
        seq = [error_response("transient"), AIResponse(text="ok")]
        result = call_with_retries(lambda: seq.pop(0), max_retries=2, sleep=lambda s: None)
        self.assertEqual(result.text, "ok")

    def test_on_attempt_hook_sees_every_attempt(self):
        from odooflux.ai.providers.transport import call_with_retries
        seen = []
        seq = [error_response("transient"), error_response("transient"), AIResponse(text="ok")]
        call_with_retries(lambda: seq.pop(0), max_retries=2, sleep=lambda s: None, on_attempt=seen.append)
        self.assertEqual(len(seen), 3)

    def test_before_retry_can_stop_the_loop(self):
        from odooflux.ai.providers.transport import call_with_retries
        calls = []
        result = call_with_retries(lambda: (calls.append(1), error_response("transient"))[1], max_retries=5,
                                   sleep=lambda s: None, before_retry=lambda: False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.error_kind, "transient")


if __name__ == "__main__":
    unittest.main()
