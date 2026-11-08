"""TST-011-033 (REQ-KAP-010): content-addressed blob store with verify-on-read.

Blobs live at `<root>/objects/sha256/<aa>/<hex>`. Reads recompute the hash and raise `SourceError` with code
`SNAPSHOT_CORRUPT` on mismatch. Stdlib only, no network.
"""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError


class BlobStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "blobs"
        self.store = BlobStore(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_blob_roundtrip(self):
        data = b"def f():\n    return 1\n"
        digest = self.store.put(data)
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        self.assertEqual(self.store.get(digest), data)
        expected = self.root / "objects" / "sha256" / digest[:2] / digest[2:]
        self.assertTrue(expected.is_file())
        self.assertTrue(self.store.has(digest))
        self.assertFalse(self.store.has("0" * 64))

    def test_blob_tamper_detected(self):
        digest = self.store.put(b"original bytes")
        path = self.root / "objects" / "sha256" / digest[:2] / digest[2:]
        path.write_bytes(b"tampered bytes")
        with self.assertRaises(SourceError) as ctx:
            self.store.get(digest)
        self.assertEqual(ctx.exception.code, "SNAPSHOT_CORRUPT")

    def test_dedupe(self):
        data = b"shared content"
        first = self.store.put(data)
        path = self.root / "objects" / "sha256" / first[:2] / first[2:]
        mtime_before = os.stat(path).st_mtime_ns
        second = self.store.put(data)
        self.assertEqual(first, second)
        self.assertEqual(os.stat(path).st_mtime_ns, mtime_before)  # not rewritten
        files = [p for p in (self.root / "objects").rglob("*") if p.is_file()]
        self.assertEqual(len(files), 1)

    def test_missing_blob_raises(self):
        with self.assertRaises(SourceError) as ctx:
            self.store.get("f" * 64)
        self.assertEqual(ctx.exception.code, "SNAPSHOT_CORRUPT")

    def test_bad_digest_rejected(self):
        for bad in ("A" * 64, "abc", "../" + "a" * 61):
            with self.subTest(digest=bad):
                with self.assertRaises(ValueError):
                    self.store.get(bad)


if __name__ == "__main__":
    unittest.main()
