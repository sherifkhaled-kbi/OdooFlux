"""TST-011-056 (REQ-KAP-016): extraction templates and their loader (T056).

Contract: contracts/candidate-rule-generation.md ("Template (data, not code)"). Templates map a change class to a
candidate rule skeleton. Every `detector_ref` must name an existing bindable detector under `odooflux.rules`; a
template naming a missing detector, a fixer, or a parameter the detector does not accept is an error. Skeletons are
DETECT_ONLY with `review_required`, never FIX_ENABLED, and a replacement is written only from a confirmed ledger entry.
Everything here is pure: no network, no AI, no database. Temporary template directories are used for negative cases.
"""

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.candidates import templates as t
from odooflux.knowledge.candidates.templates import TemplateError
from odooflux.builtins import build_registries  # composition root: the verified detector table

KNOWN_DETECTORS = build_registries().extract_toolkit.detectors

CHANGE = {
    "change_id": "CH-0123456789abcdef",
    "step": "12-13",
    "domain": "python_orm",
    "kind": "method",
    "subject_key": "res.partner.do_thing",
    "class": "REMOVED",
    "confirmed": False,
    "detail": {},
}


def _template(**overrides) -> dict:
    base = {
        "template_id": "probe-removed-method",
        "match": {"domain": "python_orm", "class": "REMOVED", "kind": "method"},
        "rule": {"category": "python_orm", "detector_ref": "odooflux.rules.python.generic:flag_method_override",
                 "fixer_ref": None, "params_from": {"method": "subject.name"}, "risk": "MEDIUM",
                 "review_required": True},
        "confidence": "MEDIUM",
        "tests": {"generate_skeleton": True},
    }
    for key, value in overrides.items():
        base[key] = value
    return base


class _DirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name: str, data) -> None:
        (self.dir / name).write_text(json.dumps(data), encoding="utf-8")


class TestShippedTemplates(unittest.TestCase):
    def test_shipped_templates_load(self):
        """Every shipped template loads, names a verified detector, has no fixer and is review_required."""
        loaded = t.load_templates(known_detectors=KNOWN_DETECTORS)
        self.assertTrue(loaded)
        for template in loaded:
            with self.subTest(template=template["template_id"]):
                self.assertIsNone(template["rule"]["fixer_ref"])
                self.assertIs(template["rule"]["review_required"], True)
                func = t.verify_detector_ref(template["rule"]["detector_ref"], KNOWN_DETECTORS)
                self.assertTrue(callable(func))
                self.assertIsNone(t.detector_params_problem(template["rule"]["detector_ref"],
                                                            set(template["rule"]["params_from"]), KNOWN_DETECTORS))

    def test_shipped_detector_refs_exist_in_rules(self):
        """The shipped templates name only generic detectors that exist under odooflux.rules (grep-verified)."""
        for template in t.load_templates(known_detectors=KNOWN_DETECTORS):
            ref = template["rule"]["detector_ref"]
            module, _, func = ref.partition(":")
            self.assertTrue(module.startswith("odooflux.rules."), ref)
            self.assertFalse(func.startswith(("remove_", "rename_", "rewrite_")), ref)


class TestTemplateValidation(_DirCase):
    def test_template_unknown_detector_ref_error(self):
        """A template naming a detector that does not exist is a template error."""
        self.write("bad.json", _template(rule={**_template()["rule"],
                                               "detector_ref": "odooflux.rules.python.generic:no_such_detector"}))
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir, known_detectors=KNOWN_DETECTORS)

    def test_fixer_is_not_a_detector(self):
        """A fixer function named as detector_ref is refused (templates never produce fixers)."""
        self.write("bad.json", _template(rule={**_template()["rule"],
                                               "detector_ref": "odooflux.rules.python.generic:remove_decorator",
                                               "params_from": {"decorator": "subject.name"}}))
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir, known_detectors=KNOWN_DETECTORS)

    def test_fixer_ref_must_be_null(self):
        self.write("bad.json", _template(rule={**_template()["rule"], "fixer_ref": "odooflux.rules.python.generic:"
                                                                                   "remove_decorator"}))
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir, known_detectors=KNOWN_DETECTORS)

    def test_params_must_match_detector(self):
        """params_from keys must be exactly the keyword parameters the detector requires (or accepts)."""
        self.write("bad.json", _template(rule={**_template()["rule"], "params_from": {"not_a_param": "subject.name"}}))
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir, known_detectors=KNOWN_DETECTORS)

    def test_unknown_domain_or_class_error(self):
        self.write("bad.json", _template(match={"domain": "nope", "class": "REMOVED"}))
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir, known_detectors=KNOWN_DETECTORS)
        self.write("bad.json", _template(match={"domain": "python_orm", "class": "VANISHED"}))
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir, known_detectors=KNOWN_DETECTORS)

    def test_review_required_must_be_true(self):
        self.write("bad.json", _template(rule={**_template()["rule"], "review_required": False}))
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir, known_detectors=KNOWN_DETECTORS)

    def test_duplicate_template_id_error(self):
        self.write("a.json", _template())
        self.write("b.json", _template())
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir, known_detectors=KNOWN_DETECTORS)


class TestDetectorVerification(_DirCase):
    """The detector table is injected: without it the load fails closed; verify=False is recorded, never silent."""

    def test_missing_table_fails_closed(self):
        self.write("ok.json", _template())
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir)

    def test_verify_false_is_recorded(self):
        self.write("ok.json", _template())
        loaded = t.load_templates(self.dir, verify=False)
        self.assertIs(loaded.detectors_verified, False)
        self.assertEqual(len(loaded), 1)

    def test_verified_load_records_true(self):
        self.write("ok.json", _template())
        self.assertIs(t.load_templates(self.dir, known_detectors=KNOWN_DETECTORS).detectors_verified, True)

    def test_detector_refused_when_absent_from_injected_table(self):
        """The table is the only source of truth: a detector that is not in it is refused."""
        self.write("ok.json", _template())
        with self.assertRaises(TemplateError):
            t.load_templates(self.dir, known_detectors={})


class TestSelection(unittest.TestCase):
    def test_most_specific_wins(self):
        """A template with more matching keys beats a broader one for the same change."""
        broad = _template(template_id="broad", match={"domain": "python_orm", "class": "REMOVED"})
        narrow = _template(template_id="narrow")
        chosen = t.select_template(CHANGE, [broad, narrow])
        self.assertEqual(chosen["template_id"], "narrow")

    def test_tie_is_error(self):
        """Two equally specific templates matching one change are an error, never a silent pick."""
        first = _template(template_id="first")
        second = _template(template_id="second")
        with self.assertRaises(TemplateError):
            t.select_template(CHANGE, [first, second])

    def test_no_match_returns_none(self):
        other = _template(match={"domain": "xml_view", "class": "REMOVED", "kind": "method"})
        self.assertIsNone(t.select_template(CHANGE, [other]))


class TestSkeleton(unittest.TestCase):
    def test_skeleton_is_detect_only_review_required(self):
        skeleton = t.build_skeleton(_template(), CHANGE, known_detectors=KNOWN_DETECTORS)
        rule = skeleton["rule"]
        self.assertEqual(rule["maturity"], "DETECT_ONLY")
        self.assertIsNone(rule["fixer_ref"])
        self.assertIs(rule["review_required"], True)
        self.assertNotEqual(rule["maturity"], "FIX_ENABLED")
        self.assertEqual(rule["params"], {"method": "do_thing"})
        self.assertIn("candidate", rule["message"].lower())
        self.assertRegex(skeleton["candidate_id"], r"^CR-[0-9a-f]{16}$")
        self.assertRegex(rule["id"], r"^12-13\.python_orm\.[a-z0-9-]+$")
        self.assertEqual(skeleton["status"], "PROPOSED")
        self.assertEqual(skeleton["origin"], "DETERMINISTIC")

    def test_skeleton_deterministic(self):
        first = t.build_skeleton(_template(), CHANGE, known_detectors=KNOWN_DETECTORS)
        second = t.build_skeleton(_template(), CHANGE, known_detectors=KNOWN_DETECTORS)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_replacement_requires_confirmed_ledger_entry(self):
        """A replacement suggestion is written only from a CONFIRMED ledger entry; otherwise it is refused."""
        template = _template(
            template_id="probe-replacement",
            match={"domain": "python_orm", "class": "REPLACEMENT_CANDIDATE", "kind": "method"},
            replacement_suggestion=True,
        )
        change = {**CHANGE, "class": "REPLACEMENT_CANDIDATE", "detail": {"replacement": "res.partner.new_thing"}}
        with self.assertRaises(TemplateError):
            t.build_skeleton(template, change, known_detectors=KNOWN_DETECTORS)
        with self.assertRaises(TemplateError):
            t.build_skeleton(template, change, ledger_entry={**change, "confirmed": False}, known_detectors=KNOWN_DETECTORS)
        confirmed = t.build_skeleton(template, change, ledger_entry={**change, "confirmed": True}, known_detectors=KNOWN_DETECTORS)
        self.assertIn("res.partner.new_thing", confirmed["rule"]["suggestion"])

    def test_no_replacement_invented_without_template_request(self):
        skeleton = t.build_skeleton(_template(), {**CHANGE, "detail": {"replacement": "x.y"}}, known_detectors=KNOWN_DETECTORS)
        self.assertNotIn("x.y", skeleton["rule"]["suggestion"])


if __name__ == "__main__":
    unittest.main()
