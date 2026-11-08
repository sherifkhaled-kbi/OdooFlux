"""T060 (FR-017, ADR-018 D-A1): ``bind_rule(run_params=...)`` and the per-run version-prefix bind (FR-019)."""

import copy
import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import BindingError, bind_rule

from .. import _setup  # noqa: F401

PY = "odooflux.rules.python.generic:"
HYG = "odooflux.rules.manifest.hygiene:"

STATIC = {
    "id": "17-18.python.group-operator-renamed", "step": "17-18", "severity": "WARNING",
    "maturity": "FIX_ENABLED", "review_required": False,
    "detector_ref": PY + "keyword_in_call", "fixer_ref": PY + "rename_keyword",
    "params": {"callee": "fields.", "keyword": "group_operator", "new_keyword": "aggregator"},
    "tests": {"positive": "T", "negative": "T", "idempotence": "T"},
}
NEEDS_TARGET = {
    "id": "*.manifest.version-prefix", "step": "*", "severity": "INFO", "maturity": "DETECT_ONLY",
    "review_required": True, "detector_ref": HYG + "flag_version_prefix", "params": {},
    "tests": {"positive": "T", "negative": "T"}, "message": "m", "suggestion": "s",
}
MANIFEST = "{'name': 'x', 'version': '16.0.1.0.0'}\n"


def doc():
    return Document.from_text("mod/__manifest__.py", MANIFEST)


class RunParamsTests(unittest.TestCase):
    def test_none_equals_current_behaviour(self):
        a = bind_rule(STATIC, BINDABLE_MODULES)
        b = bind_rule(STATIC, BINDABLE_MODULES, run_params=None)
        self.assertEqual((a.detector_params, a.fixer_params), (b.detector_params, b.fixer_params))
        self.assertFalse(b.gap)

    def test_undeclared_run_key_is_not_passed(self):
        bound = bind_rule(STATIC, BINDABLE_MODULES, run_params={"target": "18.0", "other": 1})
        self.assertNotIn("target", bound.detector_params)
        self.assertNotIn("other", bound.fixer_params)
        self.assertEqual(bound.detector_params, bind_rule(STATIC, BINDABLE_MODULES).detector_params)

    def test_declared_run_key_is_passed(self):
        bound = bind_rule(NEEDS_TARGET, BINDABLE_MODULES, run_params={"target": "18.0"})
        self.assertEqual(bound.detector_params, {"target": "18.0"})
        self.assertEqual(len(bound.detect(doc())), 1)
        same = bind_rule(NEEDS_TARGET, BINDABLE_MODULES, run_params={"target": "16.0"})
        self.assertEqual(same.detect(doc()), [])

    def test_static_and_run_key_conflict(self):
        meta = copy.deepcopy(NEEDS_TARGET)
        meta["params"] = {"target": "17.0"}
        with self.assertRaises(BindingError) as caught:
            bind_rule(meta, BINDABLE_MODULES, run_params={"target": "18.0"})
        self.assertIn("target", str(caught.exception))

    def test_conflict_is_strict_even_for_undeclared_key(self):
        meta = copy.deepcopy(STATIC)
        meta["params"] = dict(meta["params"], target="17.0")
        with self.assertRaises(BindingError) as caught:
            bind_rule(meta, BINDABLE_MODULES, run_params={"target": "18.0"})
        self.assertIn("both statically and by the run", str(caught.exception))

    def test_missing_required_run_key_skips_with_info_gap(self):
        for run in (None, {}, {"other": 1}):
            with self.subTest(run=run):
                bound = bind_rule(NEEDS_TARGET, BINDABLE_MODULES, run_params=run)
                self.assertIn("target", bound.gap)
                self.assertEqual(bound.detect(doc()), [])
                self.assertIsNone(bound.detector)

    def test_missing_required_static_param_still_errors(self):
        meta = copy.deepcopy(STATIC)
        meta["params"] = {}
        with self.assertRaises(BindingError):
            bind_rule(meta, BINDABLE_MODULES, run_params={"target": "18.0"})


class NonRegressionTests(unittest.TestCase):
    def test_every_existing_rule_binds_identically(self):
        rules = [r for r in load_knowledge().rules if r.get("detector_ref")]
        self.assertGreater(len(rules), 40)
        for meta in rules:
            plain = bind_rule(meta, BINDABLE_MODULES, run_params=None)
            if plain.gap:
                continue  # needs a run key; covered above
            with self.subTest(rule=meta["id"]):
                with_target = bind_rule(meta, BINDABLE_MODULES, run_params={"target": "99.0"})
                self.assertEqual(plain.detector_params, with_target.detector_params)
                self.assertEqual(plain.fixer_params, with_target.fixer_params)
                self.assertEqual((plain.detector, plain.fixer), (with_target.detector, with_target.fixer))
                self.assertEqual(plain.context, with_target.context)
                self.assertEqual(plain.maturity, with_target.maturity)
                self.assertEqual(plain.gap, "")


class VersionPrefixPerRunTests(unittest.TestCase):
    """T061 (FR-019): the catalogue entry binds per run with ``target``; DETECT_ONLY, review_required, no fixer."""

    def meta(self):
        return next(r for r in load_knowledge().rules if r["id"] == "*.manifest.version-prefix")

    def bind(self, run):
        return bind_rule(self.meta(), BINDABLE_MODULES, run_params=run)

    def test_entry_is_detect_only_review_without_fixer(self):
        meta = self.meta()
        self.assertEqual(meta["maturity"], "DETECT_ONLY")
        self.assertTrue(meta["review_required"])
        self.assertIsNone(meta["fixer_ref"])

    def test_target_equal_reports_nothing(self):
        self.assertEqual(self.bind({"target": "16.0"}).detect(doc()), [])

    def test_target_different_reports_the_version(self):
        findings = self.bind({"target": "18.0"}).detect(doc())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "*.manifest.version-prefix")

    def test_no_context_is_skipped_with_info_gap(self):
        bound = self.bind(None)
        self.assertIn("target", bound.gap)
        self.assertEqual(bound.detect(doc()), [])


if __name__ == "__main__":
    unittest.main()
