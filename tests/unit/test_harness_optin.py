"""TST-002-003 (REQ-TST-006): opt-in decorators skip when the flag is unset and run when it is 1."""

import os
import unittest
from unittest import mock

from tests._support import optin


class OptInTests(unittest.TestCase):
    def _run(self, decorator, env):
        calls = []

        @decorator
        def body(self_):
            calls.append(1)

        with mock.patch.dict(os.environ, env, clear=False):
            try:
                body(None)
                return bool(calls)
            except unittest.SkipTest as skip:
                self.last_reason = str(skip)
                return False

    def test_runtime_skips_when_unset_and_names_flag(self):
        env = {k: v for k, v in os.environ.items() if k != optin.RUNTIME_FLAG}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(self._run(optin.requires_runtime, {}))
        self.assertIn(optin.RUNTIME_FLAG, self.last_reason)

    def test_runtime_runs_when_one(self):
        self.assertTrue(self._run(optin.requires_runtime, {optin.RUNTIME_FLAG: "1"}))

    def test_ai_skips_when_unset_and_runs_when_one(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(optin.AI_FLAG, None)
            self.assertFalse(self._run(optin.requires_ai, {}))
        self.assertIn(optin.AI_FLAG, self.last_reason)
        self.assertTrue(self._run(optin.requires_ai, {optin.AI_FLAG: "1"}))

    def test_other_values_do_not_enable(self):
        self.assertFalse(self._run(optin.requires_runtime, {optin.RUNTIME_FLAG: "true"}))


if __name__ == "__main__":
    unittest.main()
