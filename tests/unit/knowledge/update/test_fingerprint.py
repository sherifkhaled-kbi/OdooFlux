"""TST-012-T03 (feature 012, plan section 3): update fingerprints are deterministic, sensitive to every input, and reject
malformed input. `compare_fingerprints` and `explain_change` give the reports their vocabulary."""

import unittest

from odooflux.knowledge.update import fingerprint as fp
from odooflux.knowledge.update.fingerprint import FingerprintError, FingerprintInputs

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def _inputs(**overrides):
    base = {"source_shas": {"odoo-16.0": SHA_A, "odoo-17.0": SHA_B},
            "snapshot_digests": {"odoo-16.0": "d1", "odoo-17.0": "d2"},
            "catalog_digest": "catalog-digest",
            "extractor_version": "1",
            "rule_schema_version": "1",
            "build_config": {"steps": [1, 2, 3], "strict": True, "name": "x"},
            "parent_release_id": "kr-0123456789ab"}
    base.update(overrides)
    return base


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_same_fingerprint(self):
        self.assertEqual(fp.compute_fingerprint(**_inputs()), fp.compute_fingerprint(**_inputs()))

    def test_fingerprint_is_sha256_hex(self):
        value = fp.compute_fingerprint(**_inputs())
        self.assertRegex(value, r"^[0-9a-f]{64}$")

    def test_key_order_does_not_matter(self):
        forward = _inputs(source_shas={"odoo-16.0": SHA_A, "odoo-17.0": SHA_B},
                          build_config={"a": 1, "b": {"x": [1], "y": "z"}})
        reverse = _inputs(source_shas={"odoo-17.0": SHA_B, "odoo-16.0": SHA_A},
                          build_config={"b": {"y": "z", "x": [1]}, "a": 1})
        self.assertEqual(fp.compute_fingerprint(**forward), fp.compute_fingerprint(**reverse))

    def test_stored_form_recomputes_the_same_digest(self):
        inputs = FingerprintInputs(**_inputs())
        self.assertEqual(inputs.digest(), fp.compute_fingerprint(**_inputs()))
        self.assertEqual(FingerprintInputs.from_dict(inputs.to_dict()).digest(), inputs.digest())


class SensitivityTests(unittest.TestCase):
    def test_each_input_change_flips_the_fingerprint(self):
        base = fp.compute_fingerprint(**_inputs())
        changes = {
            "source_shas": {"odoo-16.0": SHA_C, "odoo-17.0": SHA_B},
            "snapshot_digests": {"odoo-16.0": "d9", "odoo-17.0": "d2"},
            "catalog_digest": "other-catalog",
            "extractor_version": "2",
            "rule_schema_version": "2",
            "build_config": {"steps": [1, 2, 3], "strict": False, "name": "x"},
            "parent_release_id": None,
        }
        self.assertEqual(set(changes), set(fp.INPUT_NAMES))
        for name, value in changes.items():
            with self.subTest(input=name):
                self.assertNotEqual(fp.compute_fingerprint(**_inputs(**{name: value})), base)

    def test_added_source_flips_the_fingerprint(self):
        base = fp.compute_fingerprint(**_inputs())
        more = _inputs(source_shas={"odoo-16.0": SHA_A, "odoo-17.0": SHA_B, "odoo-18.0": SHA_C})
        self.assertNotEqual(fp.compute_fingerprint(**more), base)

    def test_parent_none_and_parent_string_differ(self):
        self.assertNotEqual(fp.compute_fingerprint(**_inputs(parent_release_id=None)),
                            fp.compute_fingerprint(**_inputs(parent_release_id="kr-0123456789ab")))


    def test_planning_form_and_verified_form_never_collide(self):
        # An empty snapshot_digests (the planning form) and a verified digest map are different records.
        planning = fp.compute_fingerprint(**_inputs(snapshot_digests={}))
        verified = fp.compute_fingerprint(**_inputs(snapshot_digests={"odoo-16.0": "d" * 64, "odoo-17.0": "e" * 64}))
        self.assertNotEqual(planning, verified)


class ValidationTests(unittest.TestCase):
    def assertRejected(self, **overrides):
        with self.assertRaises(FingerprintError):
            fp.compute_fingerprint(**_inputs(**overrides))

    def test_uppercase_short_and_non_hex_shas_rejected(self):
        for bad in ("A" * 40, "a" * 39, "a" * 41, "g" * 40, "", None, 12):
            with self.subTest(sha=bad):
                self.assertRejected(source_shas={"odoo-16.0": bad})

    def test_empty_digests_rejected(self):
        self.assertRejected(snapshot_digests={"odoo-16.0": ""})
        self.assertRejected(catalog_digest="")
        self.assertRejected(catalog_digest=None)

    def test_non_json_build_config_rejected(self):
        self.assertRejected(build_config={"ratio": 0.5})
        self.assertRejected(build_config={"items": {1, 2}})
        self.assertRejected(build_config={1: "non-string key"})
        self.assertRejected(build_config=["not", "a", "dict"])

    def test_bad_version_and_parent_rejected(self):
        self.assertRejected(extractor_version="")
        self.assertRejected(rule_schema_version=None)
        self.assertRejected(parent_release_id="")

    def test_missing_input_is_a_type_error(self):
        kwargs = _inputs()
        del kwargs["catalog_digest"]
        with self.assertRaises(TypeError):
            fp.compute_fingerprint(**kwargs)

    def test_stored_inputs_are_copied(self):
        source = {"odoo-16.0": SHA_A}
        inputs = FingerprintInputs(**_inputs(source_shas=source))
        source["odoo-16.0"] = SHA_C
        self.assertEqual(inputs.source_shas, {"odoo-16.0": SHA_A})

    def test_from_dict_requires_exact_keys(self):
        data = FingerprintInputs(**_inputs()).to_dict()
        data["extra"] = 1
        with self.assertRaises(FingerprintError):
            FingerprintInputs.from_dict(data)


class CompareTests(unittest.TestCase):
    def test_no_previous(self):
        self.assertEqual(fp.compare_fingerprints(None, "f" * 64), "NO_PREVIOUS")

    def test_unchanged_and_changed(self):
        self.assertEqual(fp.compare_fingerprints("a" * 64, "a" * 64), "UNCHANGED")
        self.assertEqual(fp.compare_fingerprints("a" * 64, "b" * 64), "CHANGED")

    def test_malformed_fingerprints_rejected(self):
        with self.assertRaises(FingerprintError):
            fp.compare_fingerprints("a" * 64, "not-a-fingerprint")
        with self.assertRaises(FingerprintError):
            fp.compare_fingerprints("", "a" * 64)


class ExplainChangeTests(unittest.TestCase):
    def test_names_exactly_the_changed_inputs(self):
        previous = FingerprintInputs(**_inputs()).to_dict()
        current = FingerprintInputs(**_inputs(catalog_digest="new", extractor_version="2")).to_dict()
        self.assertEqual(fp.explain_change(previous, current), ["catalog_digest", "extractor_version"])

    def test_nested_change_names_the_top_level_input(self):
        previous = FingerprintInputs(**_inputs()).to_dict()
        current = FingerprintInputs(**_inputs(source_shas={"odoo-16.0": SHA_C})).to_dict()
        self.assertEqual(fp.explain_change(previous, current), ["source_shas"])

    def test_identical_inputs_name_nothing(self):
        inputs = FingerprintInputs(**_inputs()).to_dict()
        self.assertEqual(fp.explain_change(inputs, dict(inputs)), [])

    def test_no_previous_inputs_names_everything(self):
        current = FingerprintInputs(**_inputs()).to_dict()
        self.assertEqual(fp.explain_change(None, current), sorted(fp.INPUT_NAMES))

    def test_none_to_string_counts_as_changed(self):
        previous = FingerprintInputs(**_inputs(parent_release_id=None)).to_dict()
        current = FingerprintInputs(**_inputs(parent_release_id="kr-0123456789ab")).to_dict()
        self.assertEqual(fp.explain_change(previous, current), ["parent_release_id"])


class ConstantsTests(unittest.TestCase):
    def test_versions_are_non_empty_strings(self):
        self.assertIsInstance(fp.EXTRACTOR_VERSION, str)
        self.assertTrue(fp.EXTRACTOR_VERSION)
        self.assertIsInstance(fp.RULE_SCHEMA_VERSION, str)
        self.assertTrue(fp.RULE_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
