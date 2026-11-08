"""TST-011-002 (REQ-KAP-024, REQ-KAP-022): canonical JSON bytes, digests, and the repo file convention."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.release.canonical import CanonicalError, canonical_bytes, digest_obj, write_json_file


class CanonicalTests(unittest.TestCase):
    def test_key_order_independent(self):
        a = {"b": [1, 2, {"y": "x", "a": True}], "a": None}
        b = {"a": None, "b": [1, 2, {"a": True, "y": "x"}]}
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual(digest_obj(a), digest_obj(b))
        self.assertEqual(canonical_bytes(a), b'{"a":null,"b":[1,2,{"a":true,"y":"x"}]}')

    def test_float_rejected(self):
        for bad in ({"x": 1.5}, [0.0], {"n": {"deep": [1, 2.25]}}, 3.0):
            with self.subTest(value=bad):
                with self.assertRaises(CanonicalError):
                    canonical_bytes(bad)
                with self.assertRaises(CanonicalError):
                    digest_obj(bad)
        # integers and booleans are fine
        self.assertEqual(canonical_bytes({"n": 3, "ok": False}), b'{"n":3,"ok":false}')

    def test_file_format_matches_repo_convention(self):
        obj = {"schema": 1, "items": ["é", {"k": 2}]}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub.json"
            write_json_file(target, obj)
            data = target.read_bytes()
            expected = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")
            self.assertEqual(data, expected)
            self.assertTrue(data.endswith(b"\n"))
            # a float in a file write is refused before anything is written
            other = Path(tmp) / "bad.json"
            with self.assertRaises(CanonicalError):
                write_json_file(other, {"x": 0.5})
            self.assertFalse(other.exists())

    def test_digest_stable(self):
        obj = {"release": "x", "files": [{"path": "a", "sha256": "0" * 64, "size": 3}]}
        expected = hashlib.sha256(
            json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.assertEqual(digest_obj(obj), expected)
        self.assertEqual(digest_obj(obj), digest_obj(json.loads(json.dumps(obj))))
        self.assertEqual(len(digest_obj(obj)), 64)


if __name__ == "__main__":
    unittest.main()
