"""TST-010-011 (REQ-ARC-003, REQ-REP-001): release gates.

Re-runs two earlier gate suites as part of the release candidate check:
the P2 synthetic-version (a new version needs no core edit) tests and the P8 cross-renderer count test.
"""

import unittest

SYNTHETIC_VERSION = ["tests.integration.test_adding_version_procedure", "tests.integration.test_add_version_with_rule"]
CROSS_RENDERER = ["tests.unit.reporting.test_cross_renderer_counts"]


def _run(names):
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TestResult()
    suite.run(result)
    return suite.countTestCases(), result


class ReleaseGateTests(unittest.TestCase):
    def _gate(self, names):
        count, result = _run(names)
        self.assertGreater(count, 0, "gate suite is empty: " + ", ".join(names))
        problems = [f"{t}: {tb}" for t, tb in result.failures + result.errors]
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertEqual(result.skipped, [], "a release gate must not be skipped")

    def test_synthetic_version_needs_no_core_edit(self):
        self._gate(SYNTHETIC_VERSION)

    def test_cross_renderer_counts_agree(self):
        self._gate(CROSS_RENDERER)


if __name__ == "__main__":
    unittest.main()
