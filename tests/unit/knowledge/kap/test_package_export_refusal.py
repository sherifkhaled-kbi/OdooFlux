"""Regression: `knowledge package export` refuses an internal or Enterprise-derived release with an explicit message that
says no public or Community-only projection exists. A Community-only release still exports. There is no `--public`.

Fixtures come from test_internal_release_export (sealed release trees). Only temporary directories are used.
"""

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from odooflux.cli.kap_common import EXIT_OK, EXIT_PACKAGE_REJECTED
from odooflux.cli.kap_package import EXPORT_REFUSED_NOTE
from odooflux.cli.knowledge import main as knowledge_main
from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.release.manifest import MANIFEST_NAME as RELEASE_MANIFEST
from odooflux.knowledge.release.model import ReleaseState
from odooflux.knowledge.release.store import ensure_layout, set_release_state
from tests.unit.knowledge.kap.test_internal_release_export import ENTERPRISE_PROVENANCE, PUBLIC_FILES, _seal


class PackageExportRefusalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _install(self, root: Path):
        home = self.tmp / "kb"
        ensure_layout(home)
        release_id = json.loads((root / RELEASE_MANIFEST).read_text(encoding="utf-8"))["release_id"]
        shutil.copytree(root, home / "releases" / release_id)
        set_release_state(home, release_id, ReleaseState.INSTALLED)
        return home, release_id

    def _cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = knowledge_main(list(argv))
            except SystemExit as exc:  # argparse usage errors
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_note_says_no_projection_exists(self):
        self.assertIn("no public or Community-only projection", EXPORT_REFUSED_NOTE)

    def test_internal_release_export_is_refused_with_the_explicit_message(self):
        root = _seal(self.tmp / "internal", extra={"confidentiality": "internal"})
        home, release_id = self._install(root)
        out = self.tmp / "out" / "internal.ofkp"
        code, _, err = self._cli("package", "export", release_id, "-o", str(out), "--kb-home", str(home))
        self.assertEqual(code, EXIT_PACKAGE_REJECTED)
        self.assertIn("EXPORT_REFUSED", err)
        self.assertIn("no public or Community-only projection of this release exists", err)
        self.assertFalse(out.exists())
        self.assertFalse((self.tmp / "out").exists())

    def test_enterprise_derived_release_export_is_refused_with_the_explicit_message(self):
        root = _seal(self.tmp / "enterprise", files={**PUBLIC_FILES, "provenance/sources.json": ENTERPRISE_PROVENANCE})
        home, release_id = self._install(root)
        out = self.tmp / "out" / "ent.ofkp"
        code, _, err = self._cli("package", "export", release_id, "-o", str(out), "--kb-home", str(home))
        self.assertEqual(code, EXIT_PACKAGE_REJECTED, err)
        self.assertIn("EXPORT_REFUSED", err)
        self.assertIn("Enterprise-derived", err)
        self.assertIn("no public or Community-only projection", err)
        self.assertFalse(out.exists())
        self.assertFalse((self.tmp / "out").exists())

    def test_builder_refusal_is_still_an_export_refusal(self):
        root = _seal(self.tmp / "internal", extra={"confidentiality": "internal"})
        with self.assertRaises(PackageError) as ctx:
            export_package(root, self.tmp / "out" / "internal.ofkp")
        self.assertEqual(ctx.exception.code, "EXPORT_REFUSED")
        self.assertFalse((self.tmp / "out").exists())

    def test_community_only_release_still_exports(self):
        root = _seal(self.tmp / "community")
        home, release_id = self._install(root)
        out = self.tmp / "out" / "community.ofkp"
        code, _, err = self._cli("package", "export", release_id, "-o", str(out), "--kb-home", str(home))
        self.assertEqual(code, EXIT_OK, err)
        self.assertTrue(out.is_file())

    def test_public_flag_does_not_exist(self):
        root = _seal(self.tmp / "community")
        home, release_id = self._install(root)
        out = self.tmp / "out" / "public.ofkp"
        code, _, err = self._cli("package", "export", release_id, "-o", str(out), "--kb-home", str(home), "--public")
        self.assertEqual(code, 2)  # argparse usage error: there is no projection export
        self.assertIn("unrecognized arguments", err)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
