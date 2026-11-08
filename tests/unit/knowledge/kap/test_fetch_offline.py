"""TST-011-039 (REQ-KAP-001, REQ-KAP-009): `acquisition/fetch.py`, the only networked module (offline tests).

Every test here is offline: the opener is an injected fake, and sockets are patched to fail if touched. Live
retrieval is never part of the default run (see `ODOOFLUX_KAP_LIVE_TESTS`, not used here).
"""

import hashlib
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.acquisition import fetch as f
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError

ALLOW = ["https://github.com/odoo/odoo/", "https://github.com/odoo/documentation/"]
URL = "https://github.com/odoo/odoo/archive/0123.tar.gz"
PAYLOAD = b"synthetic archive bytes\n"


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, n=-1):
        return self._body if n is None or n < 0 else self._body[:n]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, body: bytes = PAYLOAD):
        self.body = body
        self.calls = []

    def open(self, url, timeout=None):
        self.calls.append((url, timeout))
        return FakeResponse(self.body)


class FetchOfflineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = BlobStore(Path(self._tmp.name) / "store")
        self.spec = {"source_id": "odoo-community-17.0", "kind": "GIT_COMMUNITY", "url": URL}

    def _no_socket(self):
        def boom(*args, **kwargs):
            raise AssertionError("a socket was opened")
        return mock.patch.multiple(socket, socket=boom, create_connection=boom)

    def _objects(self) -> int:
        root = Path(self._tmp.name) / "store" / "objects"
        return sum(1 for p in root.rglob("*") if p.is_file()) if root.exists() else 0

    def test_refuses_without_flag_no_socket(self):
        opener = FakeOpener()
        with self._no_socket(), self.assertRaises(SourceError) as ctx:
            f.fetch(self.spec, self.store, allow_network=False, opener=opener, allow_list=ALLOW)
        self.assertEqual(ctx.exception.code, "NETWORK_DISABLED")
        self.assertEqual(opener.calls, [])
        # the flag defaults to off: calling without it is refused the same way
        with self._no_socket(), self.assertRaises(SourceError) as ctx:
            f.fetch(self.spec, self.store, opener=opener, allow_list=ALLOW)
        self.assertEqual(ctx.exception.code, "NETWORK_DISABLED")
        self.assertEqual(opener.calls, [])
        self.assertEqual(self._objects(), 0)

    def test_not_allowlisted_rejected(self):
        opener = FakeOpener()
        bad = dict(self.spec, url="https://example.invalid/odoo/odoo/archive.tar.gz")
        with self.assertRaises(SourceError) as ctx:
            f.fetch(bad, self.store, allow_network=True, opener=opener, allow_list=ALLOW)
        self.assertEqual(ctx.exception.code, "NOT_ALLOWLISTED")
        http_only = dict(self.spec, url="http://github.com/odoo/odoo/archive.tar.gz")
        with self.assertRaises(SourceError) as ctx:
            f.fetch(http_only, self.store, allow_network=True, opener=opener, allow_list=ALLOW)
        self.assertEqual(ctx.exception.code, "NOT_ALLOWLISTED")
        local = dict(self.spec, url="local:/srv/odoo")
        with self.assertRaises(SourceError):
            f.fetch(local, self.store, allow_network=True, opener=opener, allow_list=ALLOW)
        self.assertEqual(opener.calls, [])
        # redirects are re-checked against the allow-list: a redirect off the list is refused
        handler = f.AllowListRedirect(ALLOW, "odoo-community-17.0")
        req = mock.Mock(full_url=URL)
        with self.assertRaises(SourceError) as ctx:
            handler.redirect_request(req, None, 302, "Found", {}, "https://example.invalid/evil.tar.gz")
        self.assertEqual(ctx.exception.code, "NOT_ALLOWLISTED")

    def test_checksum_mismatch_with_fake_opener(self):
        opener = FakeOpener()
        good = hashlib.sha256(PAYLOAD).hexdigest()
        with self.assertRaises(SourceError) as ctx:
            f.fetch(self.spec, self.store, allow_network=True, expected_sha256="0" * 64, opener=opener,
                    allow_list=ALLOW)
        self.assertEqual(ctx.exception.code, "CHECKSUM_MISMATCH")
        self.assertEqual(self._objects(), 0)  # nothing stored on mismatch
        result = f.fetch(self.spec, self.store, allow_network=True, expected_sha256=good, opener=opener,
                         allow_list=ALLOW)
        self.assertEqual(result["sha256"], good)
        self.assertEqual(result["size"], len(PAYLOAD))
        self.assertEqual(self.store.get(good), PAYLOAD)
        self.assertEqual(opener.calls[-1][0], URL)
        self.assertEqual(opener.calls[-1][1], f.FETCH_TIMEOUT)

    def test_size_cap_enforced(self):
        opener = FakeOpener(b"x" * 64)
        with mock.patch.object(f, "MAX_BYTES", 16), self.assertRaises(SourceError) as ctx:
            f.fetch(self.spec, self.store, allow_network=True, opener=opener, allow_list=ALLOW)
        self.assertEqual(ctx.exception.code, "IO_ERROR")
        self.assertEqual(self._objects(), 0)


if __name__ == "__main__":
    unittest.main()
