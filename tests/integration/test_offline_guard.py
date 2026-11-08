"""TST-002-004 (REQ-TST-001, REQ-TST-006): the default suite never opens a network connection.

``socket.socket.connect`` is patched to raise while the analyze run executes on every indexed fixture (in-process).
"""

import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._support import fixtures
from tests.integration.helpers import run_cli_main


def _blocked(*args, **kwargs):
    raise AssertionError("network access attempted during the offline suite")


class OfflineGuardTests(unittest.TestCase):
    def test_guard_fires_on_connect(self):
        with mock.patch.object(socket.socket, "connect", _blocked):
            sock = socket.socket()
            self.addCleanup(sock.close)
            with self.assertRaises(AssertionError):
                sock.connect(("127.0.0.1", 9))

    def test_analyze_on_every_fixture_makes_no_connection(self):
        with mock.patch.object(socket.socket, "connect", _blocked):
            for item in fixtures.load_index():
                with self.subTest(fixture=item["id"]), tempfile.TemporaryDirectory() as tmp:
                    module = fixtures.copy_fixture(item["id"], tmp)
                    code, _ = run_cli_main(["migrate", "--module", module, "--from-version", item["source_version"],
                                            "--to-version", "18.0", "--state-dir", Path(tmp) / "state", "--no-color"])
                    self.assertIn(code, (0, 1, 2))


if __name__ == "__main__":
    unittest.main()
