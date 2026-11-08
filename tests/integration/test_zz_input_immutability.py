"""TST-002-008 (REQ-TST-003, REQ-SAF-001): fixture inputs are unchanged.

The name sorts late so it runs after the other integration tests in the same process. Each fixture module (without
``expected/`` and the PROVISIONAL marker) is compared with the ``input_digest`` recorded in INDEX.json.
"""

import unittest

from tests._support import fixtures


class InputImmutabilityTests(unittest.TestCase):
    def test_zz_fixture_inputs_match_recorded_digests(self):
        for item in fixtures.load_index():
            with self.subTest(fixture=item["id"]):
                self.assertIn("input_digest", item, "run tools/update_expectations.py --force once")
                self.assertEqual(fixtures.input_digest(item), item["input_digest"])


if __name__ == "__main__":
    unittest.main()
