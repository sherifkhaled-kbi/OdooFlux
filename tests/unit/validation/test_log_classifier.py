"""TST-008-005 (REQ-VAL-004, REQ-ACL-002, FR-006): runtime log classifier on recorded log samples.

Samples live in tests/golden_fixtures/runtime/logs/ (see the README there for which are recorded from a real
opt-in run and which are synthesised from the EV-360..EV-367 source strings). Timeout and oom come from the
container state (killed_reason), never from a log pattern.
"""

import unittest
from pathlib import Path

from .._setup import SRC  # noqa: F401  (puts src/ first on sys.path)
from odooflux.validation.runtime import log_classifier as lc

SAMPLES = Path(__file__).resolve().parents[2] / "golden_fixtures" / "runtime" / "logs"
FR006_CLASSES = ("import_error", "registry", "view_validation", "access_rights", "data_load",
                 "asset_compile", "missing_python_dependency", "timeout", "oom", "unknown")
LOG_CLASSES = ("import_error", "registry", "view_validation", "access_rights", "data_load",
               "asset_compile", "missing_python_dependency")


def sample(name):
    return (SAMPLES / f"{name}.log").read_text(encoding="utf-8")


def classes_of(text, version="19.0", killed_reason=None):
    return [e.error_class for e in lc.classify_text(text, version, killed_reason=killed_reason)]


class SampleRecognitionTests(unittest.TestCase):
    def test_each_log_class_is_recognised_on_its_sample(self):
        for name in LOG_CLASSES:
            with self.subTest(sample=name):
                self.assertIn(name, classes_of(sample(name)))

    def test_unknown_lines_map_to_unknown_and_info_lines_are_not_reported(self):
        errors = lc.classify_text(sample("unknown"), "19.0")
        self.assertEqual([e.error_class for e in errors], ["unknown"])
        self.assertEqual(errors[0].level, "ERROR")

    def test_timeout_and_oom_come_from_killed_reason_not_from_patterns(self):
        self.assertEqual(classes_of("", killed_reason="timeout"), ["timeout"])
        self.assertEqual(classes_of("", killed_reason="oom"), ["oom"])
        self.assertEqual(classes_of(sample("unknown"), killed_reason="timeout")[0], "timeout")

    def test_no_pattern_claims_timeout_or_oom(self):
        for pattern in lc.load_patterns():
            self.assertNotIn(pattern["class"], ("timeout", "oom"), pattern["id"])

    def test_every_fr006_class_is_covered_by_the_test_matrix(self):
        covered = set(LOG_CLASSES) | {"timeout", "oom", "unknown"}
        self.assertEqual(covered, set(FR006_CLASSES))


class RecordSemanticsTests(unittest.TestCase):
    def test_records_split_on_timestamps_and_traceback_belongs_to_its_record(self):
        records = lc.split_records(sample("import_error"))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].level, "ERROR")
        self.assertIn("ModuleNotFoundError", records[0].text)

    def test_a_pattern_only_in_a_traceback_is_still_attributed_to_its_record(self):
        text = ("2026-11-07 10:00:00,000 1 ERROR odoo odoo.sql_db: unexpected failure\n"
                "Traceback (most recent call last):\n"
                "  Couldn't load module kbi_inside_traceback\n")
        self.assertEqual(classes_of(text), ["import_error"])

    def test_context_must_match_the_same_record(self):
        # "External ID not found" is an access_rights error only when the same record mentions ir.model.access.
        without_context = ("2026-11-07 10:00:00,000 1 ERROR odoo odoo.tools.convert: "
                           "while parsing /mnt/extra-addons/x/views/v.xml:4: External ID not found in the system: x.y\n")
        with_context = ("2026-11-07 10:00:00,000 1 ERROR odoo odoo.tools.convert: "
                        "while parsing /mnt/extra-addons/x/security/ir.model.access.csv:4, ir.model.access: "
                        "External ID not found in the system: x.y\n")
        self.assertEqual(classes_of(without_context), ["data_load"])
        self.assertEqual(classes_of(with_context), ["access_rights"])

    def test_first_matching_pattern_wins(self):
        # The ACL pattern precedes the generic data_load pattern in the knowledge file.
        self.assertEqual(classes_of(sample("access_rights"))[0], "access_rights")

    def test_patterns_outside_the_target_version_range_do_not_apply(self):
        self.assertEqual(classes_of(sample("registry"), version="19.0"), ["registry"])
        # The import_error pattern covers 16.0-19.0 only; an ERROR record for 20.0 is therefore unknown.
        self.assertEqual(classes_of(sample("import_error"), version="20.0"), ["unknown"])


class AttributionTests(unittest.TestCase):
    def test_view_error_is_attributed_to_the_view_file_line_and_xml_id(self):
        errors = [e for e in lc.classify_text(sample("view_validation"), "19.0") if e.error_class == "view_validation"]
        self.assertTrue(errors)
        self.assertEqual(errors[0].file, "broken_view/views/fixture_views.xml")
        self.assertEqual(errors[0].line, 3)
        self.assertEqual(errors[0].xml_id, "view_odooflux_fixture_form")

    def test_acl_error_is_attributed_to_the_security_file_being_loaded(self):
        # Odoo logs "loading <module>/<file>" before each data file; the failing record names only the SQL table.
        errors = [e for e in lc.classify_text(sample("access_rights"), "19.0") if e.error_class == "access_rights"]
        self.assertTrue(errors)
        self.assertEqual(errors[0].pattern_id, "access_rights.null-model-id")
        self.assertEqual(errors[0].file, "acl_missing_model/security/ir.model.access.csv")

    def test_external_id_error_carries_the_xml_id_and_line_from_the_record(self):
        text = ("2026-11-07 10:00:00,000 1 ERROR odoo odoo.tools.convert: "
                "while parsing /mnt/extra-addons/kbi_xml/views/views.xml:12: External ID not found in the system: "
                "kbi_xml.menu_missing\n")
        error = lc.classify_text(text, "19.0")[0]
        self.assertEqual(error.error_class, "data_load")
        self.assertEqual(error.file, "kbi_xml/views/views.xml")
        self.assertEqual(error.line, 12)
        self.assertEqual(error.xml_id, "kbi_xml.menu_missing")

    def test_to_dict_uses_the_contract_key_class(self):
        error = lc.classify_text(sample("registry"), "19.0")[0]
        self.assertEqual(error.to_dict()["class"], "registry")


class ExcerptTests(unittest.TestCase):
    def test_excerpt_is_bounded_by_the_requested_line_count(self):
        text = "\n".join(f"2026-11-07 10:00:00,000 1 INFO odoo odoo.x: line {n}" for n in range(500))
        self.assertEqual(len(lc.excerpt_for(text, 10).splitlines()), 10)


if __name__ == "__main__":
    unittest.main()
