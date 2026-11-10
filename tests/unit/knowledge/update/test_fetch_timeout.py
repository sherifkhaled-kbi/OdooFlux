import os
import unittest
from unittest import mock

from odooflux.knowledge.update import remote_git as rg


class FetchTimeoutTests(unittest.TestCase):
    def value(self, raw):
        env = {} if raw is None else {rg.FETCH_TIMEOUT_ENV: raw}
        with mock.patch.dict(os.environ, env, clear=False):
            if raw is None:
                os.environ.pop(rg.FETCH_TIMEOUT_ENV, None)
            return rg._fetch_timeout()

    def test_default_and_valid_override(self):
        self.assertEqual(self.value(None), 300)
        self.assertEqual(self.value("3000"), 3000)

    def test_invalid_or_out_of_range_values_are_ignored(self):
        for raw in ("", "abc", "-5", "10", "99999", "1e3"):
            self.assertEqual(self.value(raw), 300, raw)


if __name__ == "__main__":
    unittest.main()
