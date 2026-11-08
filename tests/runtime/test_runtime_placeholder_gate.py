"""TST-002-010 (REQ-TST-006): placeholder for the opt-in runtime suite; skipped unless ODOOFLUX_RUNTIME_TESTS=1."""

import shutil
import unittest

from tests._support.optin import requires_runtime


class RuntimePlaceholderGate(unittest.TestCase):
    @requires_runtime
    def test_docker_on_path(self):
        self.assertIsNotNone(shutil.which("docker"), "docker is required for runtime validation tests")


if __name__ == "__main__":
    unittest.main()
