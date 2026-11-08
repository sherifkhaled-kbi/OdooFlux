"""TST-007-010 (REQ-AI-003, REQ-TRF-005): FIXED only after re-scan; review_required caps at NEEDS_REVIEW."""

import json
import unittest

from tests.unit.ai import _helpers as h
from odooflux.ai.escalation import Escalator
from odooflux.ai.providers.fake import FakeProvider
from odooflux.ai.providers.types import ModelDescriptor

PY = h.corpus("sample_models.py.txt")
LEGACY = h.corpus("legacy_class.py.txt")


def provider(script_name="mixed", script=None):
    return FakeProvider(script or h.script(script_name), models=[ModelDescriptor("fake", "fake-model")])


def escalator(p, rescan=h.toy_rescan, validate=h.python_validate, **kw):
    return Escalator(p.complete, provider="fake", model="fake-model", step="s", validate=validate, rescan=rescan,
                     **kw)


def run(esc, text=PY, path="m.py"):
    return esc.escalate_file("mod", path, text, h.toy_findings(path, text), h.TOY_METAS)


def by_rule_line(result):
    return {o.finding_id: o for o in result.outcomes}


class EscalationTests(unittest.TestCase):
    def test_accepted_edit_fixes_only_after_rescan(self):
        rescans = []

        def rescan(path, text):
            rescans.append(text)
            return h.toy_rescan(path, text)
        result = run(escalator(provider(), rescan=rescan))
        line = next(i for i, ln in enumerate(PY.splitlines(), 1) if "def f_ok" in ln) + 1
        f_ok = next(o for o in result.outcomes if o.finding_id == f"toy.old-api:{line}")
        self.assertEqual((f_ok.status, f_ok.outcome), ("FIXED", "accepted"))
        self.assertIn("return new_api(self.name)", result.text)
        self.assertGreaterEqual(len(rescans), 2)  # initial scan + a re-scan of the candidate
        self.assertIn("new_api", rescans[-1])

    def test_unscripted_findings_stay_open_with_error(self):
        result = run(escalator(provider()))
        statuses = {o.status for o in result.outcomes}
        self.assertIn("OPEN", statuses)
        self.assertTrue(any(o.outcome.startswith("error:") for o in result.outcomes))

    def test_declined_stays_open(self):
        result = run(escalator(provider()))
        self.assertIn("skipped:model_declined", {o.outcome for o in result.outcomes})

    def test_extra_definition_rejected_out_of_region(self):
        result = run(escalator(provider()))
        self.assertIn("rejected:out_of_region", {o.outcome for o in result.outcomes})
        self.assertNotIn("sneaky", result.text)

    def test_protected_rename_rejected_and_text_untouched(self):
        result = run(escalator(provider("protected")), text=LEGACY, path="m.py")
        self.assertEqual(result.outcomes[0].outcome, "rejected:protected_identifier_changed")
        self.assertEqual(result.text, LEGACY)
        self.assertEqual(result.outcomes[0].status, "OPEN")

    def test_persisting_finding_is_not_fixed_and_edit_not_kept(self):
        script = {"entries": [{"match": {"contains": "def f_ok"}, "response": {
            "replacement": "    def f_ok(self):\n        return old_api(self.name)  # still\n", "notes": "",
            "cannot_fix": False}}]}
        text = "class A:\n    def f_ok(self):\n        return old_api(self.name)\n"
        result = run(escalator(provider(script=script)), text=text)
        self.assertEqual(result.outcomes[0].outcome, "rejected:finding_unresolved")
        self.assertEqual(result.text, text)

    def test_introduced_finding_rejects_the_edit(self):
        script = {"entries": [{"match": {"contains": "def f_ok"}, "response": {
            "replacement": "    def f_ok(self):\n        return legacy_call(self.name)\n", "notes": "",
            "cannot_fix": False}}]}
        text = "class A:\n    def f_ok(self):\n        return old_api(self.name)\n"
        result = run(escalator(provider(script=script)), text=text)
        self.assertEqual(result.outcomes[0].outcome, "rejected:introduced_findings")
        self.assertEqual(result.text, text)

    def test_review_required_rule_caps_status_at_needs_review(self):
        script = {"entries": [{"match": {"contains": "def f_ok"}, "response": {
            "replacement": "    def f_ok(self):\n        return fixed(self.name)\n", "notes": "", "cannot_fix": False}}]}
        text = "class A:\n    def f_ok(self):\n        return legacy_call(self.name)\n"
        result = run(escalator(provider(script=script)), text=text)
        self.assertEqual(result.outcomes[0].status, "FIXED")
        self.assertEqual(result.status_cap, "NEEDS_REVIEW")

    def test_plain_rule_has_no_status_cap(self):
        result = run(escalator(provider()))
        self.assertIsNone(result.status_cap)

    def test_ineligible_findings_cause_zero_requests(self):
        p = provider()
        esc = escalator(p)
        metas = {k: v for k, v in h.TOY_METAS.items()}
        from odooflux.ai.escalation import RuleMeta
        metas["toy.old-api"] = RuleMeta("toy.old-api", ai_eligible=True, has_fix=True, evidence=h.EVIDENCE)
        esc.escalate_file("mod", "m.py", PY, h.toy_findings("m.py", PY), metas)
        self.assertEqual(p.requests, [])

    def test_two_findings_in_one_file_apply_bottom_first_and_both_fix(self):
        text = "class A:\n    def f_ok(self):\n        return old_api(1)\n\n    def g_ok(self):\n        return old_api(2)\n"
        script = {"entries": [
            {"match": {"contains": "def f_ok"}, "response": {"replacement": "    def f_ok(self):\n        return new_api(1)\n", "notes": "", "cannot_fix": False}},
            {"match": {"contains": "def g_ok"}, "response": {"replacement": "    def g_ok(self):\n        return new_api(2)\n", "notes": "", "cannot_fix": False}}]}
        result = run(escalator(provider(script=script)), text=text)
        self.assertEqual([o.status for o in result.outcomes], ["FIXED", "FIXED"])
        self.assertEqual(result.text.count("new_api"), 2)
        self.assertNotIn("old_api", result.text)


if __name__ == "__main__":
    unittest.main()
