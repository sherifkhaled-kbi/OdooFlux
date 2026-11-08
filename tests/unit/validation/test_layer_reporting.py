"""TST-008-002 (REQ-VAL-006, FR-002): layers that did not run carry a reason and never serialise as PASS."""

import unittest

from odooflux.core.contracts.records import ValidationResult
from odooflux.validation.status import serialise_layers, skipped, unavailable

from .._setup import SRC  # noqa: F401


class LayerReportingTests(unittest.TestCase):
    def test_unavailable_and_skipped_carry_reasons(self):
        self.assertEqual(unavailable(4, "docker_unavailable").reason, "docker_unavailable")
        self.assertEqual(skipped(4, "enterprise_dependency").outcome, "SKIPPED")
        with self.assertRaises(ValueError):
            unavailable(4, "")
        with self.assertRaises(ValueError):
            skipped(5, "")

    def test_serialised_unrun_layers_never_read_pass(self):
        results = {1: ValidationResult(layer=1, outcome="PASS"),
                   4: skipped(4, "enterprise_dependency"),
                   5: unavailable(5, "image_unavailable")}
        serial = serialise_layers(results)
        self.assertEqual(serial["L1"]["outcome"], "PASS")
        for key in ("L4", "L5"):
            self.assertNotEqual(serial[key]["outcome"], "PASS")
            self.assertTrue(serial[key]["reason"])

    def test_pass_has_no_reason_requirement_and_non_pass_needs_one(self):
        self.assertEqual(ValidationResult(layer=2, outcome="PASS").outcome, "PASS")
        with self.assertRaises(ValueError):
            ValidationResult(layer=4, outcome="UNAVAILABLE")

    def test_serialised_layers_are_never_pass_without_a_result(self):
        serial = serialise_layers({})
        for layer in range(1, 6):
            self.assertNotEqual(serial[f"L{layer}"]["outcome"], "PASS")
            self.assertTrue(serial[f"L{layer}"]["reason"])


if __name__ == "__main__":
    unittest.main()
