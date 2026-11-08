"""TST-011-034 (REQ-KAP-010, REQ-KAP-013): snapshot builder (manifest, digest, excluded list with reasons).

Builds snapshots of plain directory trees in temporary folders. Offline, stdlib only. The synthetic git repo
(T030) is not needed here: git and directory snapshots must match, which T036 checks.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge import validator as v
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

SOURCE_ID = "odoo-community-17.0"
REV = "2" * 40
CREATED = "2026-11-08T10:00:00Z"
SCHEMA = json.loads((KNOWLEDGE_ROOT / "schemas" / "snapshot.schema.json").read_text(encoding="utf-8"))

FILES = {
    "addons/base/__manifest__.py": b"{'name': 'Base', 'version': '17.0'}\n",
    "addons/base/models/res_users.py": b"class ResUsers(models.Model):\n    pass\n",
    "addons/base/views/users.xml": b"<odoo><record id='u'/></odoo>\n",
    "addons/sale/migrations/17.0.1.1/pre-migrate.py": b"def migrate(cr, version):\n    pass\n",
    "addons/base/tests/test_users.py": b"def test_x():\n    pass\n",
}


def _write_tree(root: Path, files: dict, order=None) -> None:
    keys = list(files) if order is None else order
    for rel in keys:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[rel])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _tree(self, name: str, files: dict = FILES, order=None) -> Path:
        root = self.base / name
        root.mkdir()
        _write_tree(root, files, order)
        return root

    def _build(self, root: Path, store_dir: str = "store", **kwargs) -> dict:
        store = BlobStore(self.base / store_dir)
        return build_snapshot(root, SOURCE_ID, REV, store, created_at=CREATED, **kwargs)

    def test_snapshot_deterministic(self):
        first_root = self._tree("first")
        # same content, created in reverse order, different folder name, different store
        second_root = self._tree("second", order=list(reversed(list(FILES))))
        a = self._build(first_root, "store-a")
        b = self._build(second_root, "store-b")
        self.assertEqual(a["entries"], b["entries"])
        self.assertEqual(a["snapshot_digest"], b["snapshot_digest"])
        self.assertEqual(a["snapshot_id"], b["snapshot_id"])
        self.assertEqual(a["snapshot_id"], "ss-" + a["snapshot_digest"][:12])
        paths = [e["path"] for e in a["entries"]]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(set(paths), set(FILES))  # no exclusions without a scope rule
        self.assertEqual(v.check(a, SCHEMA), [])
        # the digest covers content: one changed byte changes it
        changed = dict(FILES)
        changed["addons/base/models/res_users.py"] = b"class ResUsers(models.Model):\n    x = 1\n"
        c = self._build(self._tree("third", changed), "store-c")
        self.assertNotEqual(c["snapshot_digest"], a["snapshot_digest"])
        # and it covers the source identity
        other = build_snapshot(first_root, "odoo-community-18.0", REV, BlobStore(self.base / "store-a"),
                               created_at=CREATED)
        self.assertNotEqual(other["snapshot_digest"], a["snapshot_digest"])

    def test_entries_kinds_and_blobs(self):
        root = self._tree("kinds")
        snap = self._build(root)
        kinds = {e["path"]: e["kind"] for e in snap["entries"]}
        self.assertEqual(kinds["addons/base/__manifest__.py"], "manifest")
        self.assertEqual(kinds["addons/base/models/res_users.py"], "python")
        self.assertEqual(kinds["addons/base/views/users.xml"], "xml")
        self.assertEqual(kinds["addons/sale/migrations/17.0.1.1/pre-migrate.py"], "migration")
        store = BlobStore(self.base / "store")
        for entry in snap["entries"]:
            data = (root / entry["path"]).read_bytes()
            self.assertEqual(store.get(entry["sha256"]), data)
            self.assertEqual(entry["size"], len(data))

    def test_scope_exclusion_reason(self):
        root = self._tree("scoped")
        snap = self._build(root, scope_exclude=[{"pattern": "*/tests/*", "reason": "test code is not extracted"}])
        self.assertNotIn("addons/base/tests/test_users.py", [e["path"] for e in snap["entries"]])
        self.assertIn({"path": "addons/base/tests/test_users.py", "reason": "test code is not extracted"},
                      snap["limits"]["excluded"])

    def test_symlink_escape_excluded(self):
        root = self._tree("links")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.py").write_bytes(b"SECRET = 1\n")
        (root / "addons" / "base" / "escape.py").symlink_to(outside / "secret.py")
        (root / "addons" / "escape_dir").symlink_to(outside)
        snap = self._build(root)
        paths = [e["path"] for e in snap["entries"]]
        self.assertNotIn("addons/base/escape.py", paths)
        self.assertFalse(any(p.startswith("addons/escape_dir") for p in paths))
        excluded = {x["path"]: x["reason"] for x in snap["limits"]["excluded"]}
        self.assertEqual(excluded["addons/base/escape.py"], "SYMLINK_ESCAPE")
        self.assertEqual(excluded["addons/escape_dir"], "SYMLINK_ESCAPE")
        self.assertNotIn(b"SECRET", b"".join(
            BlobStore(self.base / "store").get(e["sha256"]) for e in snap["entries"]))

    def test_nonutf8_name_excluded_with_reason(self):
        root = self._tree("bytes")
        bad_name = os.fsencode(str(root / "addons" / "base")) + b"/caf\xe9.py"
        try:
            fd = os.open(bad_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except OSError as exc:  # filesystem refuses non-UTF-8 names: nothing to test here
            self.skipTest(f"filesystem does not allow raw byte names: {exc}")
        os.write(fd, b"x = 1\n")
        os.close(fd)
        snap = self._build(root)
        self.assertFalse(any("caf" in e["path"] for e in snap["entries"]))
        excluded = snap["limits"]["excluded"]
        reasons = {x["reason"] for x in excluded if "caf" in x["path"]}
        self.assertEqual(reasons, {"NON_UTF8_NAME"})
        self.assertEqual(v.check(snap, SCHEMA), [])  # the path is printable and valid JSON

    def test_root_must_be_directory(self):
        with self.assertRaises(SourceError) as ctx:
            self._build(self.base / "missing")
        self.assertEqual(ctx.exception.code, "IO_ERROR")


if __name__ == "__main__":
    unittest.main()
