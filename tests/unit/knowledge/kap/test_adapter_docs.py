"""TST-011-038 (REQ-KAP-007, REQ-KAP-011): docs adapter (rst headings, versionchanged, deprecated directives).

Offline. Parsing is line-oriented on `.rst` text. The adapter test builds a throwaway local git repository (local
paths only, no network) to check that the DOCS snapshot holds `.rst` files and nothing else.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.adapters.docs_rst import DocsAdapter, extract_rst, extract_snapshot
from odooflux.knowledge.acquisition.blobstore import BlobStore

GIT = shutil.which("git")

SAMPLE = """Sale Order
==========

.. versionchanged:: 17.0
   The field ``amount`` is now computed.

Methods
-------

.. deprecated:: 16.0
   Use ``compute_total`` instead.

.. code-block:: python

   x = 1

.. unknownthing:: foo
   with a body
"""


class DocsParserTests(unittest.TestCase):
    def test_directives_extracted(self):
        parsed = extract_rst(SAMPLE)
        self.assertEqual([(h["title"], h["underline"]) for h in parsed["headings"]],
                         [("Sale Order", "="), ("Methods", "-")])
        self.assertEqual(parsed["headings"][0]["line"], 1)
        known = {(d["name"], d["version"], d["text"]) for d in parsed["directives"]}
        self.assertEqual(known, {
            ("versionchanged", "17.0", "The field ``amount`` is now computed."),
            ("deprecated", "16.0", "Use ``compute_total`` instead."),
        })
        self.assertEqual(parsed["directives"][0]["line"], 4)

    def test_unknown_directive_recorded(self):
        parsed = extract_rst(SAMPLE)
        unknown = [(u["name"], u["line"]) for u in parsed["unknown"]]
        self.assertEqual(unknown, [("code-block", 13), ("unknownthing", 17)])  # nothing dropped silently

    def test_plain_text_has_no_directives(self):
        parsed = extract_rst("Just prose.\n\nNo markup here.\n")
        self.assertEqual(parsed, {"headings": [], "directives": [], "unknown": []})


@unittest.skipUnless(GIT, "git is not installed; the docs adapter test builds a local repository")
class DocsAdapterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "documentation"
        self.repo.mkdir()
        files = {
            "content/developer/orm.rst": SAMPLE,
            "content/developer/index.html": "<html></html>\n",
            "README.md": "# docs\n",
        }
        for rel, text in files.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text, encoding="utf-8")
        env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "HOME": str(self.base), "GIT_AUTHOR_NAME": "KAP", "GIT_AUTHOR_EMAIL": "kap@example.invalid",
               "GIT_COMMITTER_NAME": "KAP", "GIT_COMMITTER_EMAIL": "kap@example.invalid",
               "GIT_AUTHOR_DATE": "1700000000 +0000", "GIT_COMMITTER_DATE": "1700000000 +0000"}
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "docs"]):
            subprocess.run(["git", "-C", str(self.repo), *args], env=env, check=True, capture_output=True)
        self.sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()
        self.store = BlobStore(self.base / "store")

    def test_docs_snapshot_rst_only(self):
        spec = {
            "source_id": "odoo-documentation-17.0", "kind": "DOCS", "official": False,
            "url": "local:" + str(self.repo), "licence_access": "PUBLIC_OPEN", "licence_id": "CC-BY-SA-4.0",
            "branch": "17.0", "revision": self.sha,
            "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": ["rst"]},
            "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": False,
        }
        adapter = DocsAdapter(allow_list=["https://github.com/odoo/documentation/"])
        self.assertTrue(adapter.probe(spec)["available"])
        snap = adapter.snapshot(spec, self.store, created_at="2026-11-08T10:00:00Z")
        self.assertEqual([e["path"] for e in snap["entries"]], ["content/developer/orm.rst"])
        found = extract_snapshot(snap, self.store)
        self.assertEqual([f["path"] for f in found["files"]], ["content/developer/orm.rst"])
        self.assertEqual(found["files"][0]["directives"][0]["name"], "versionchanged")
        self.assertEqual(found["undecodable"], [])


if __name__ == "__main__":
    unittest.main()
