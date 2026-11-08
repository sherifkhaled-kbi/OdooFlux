"""TST-011-077 (REQ-KAP-036, REQ-KAP-042): the L3 integrity reader takes an optional knowledge root. The default is the
built-in core and Enterprise lists. A release tree is mandatory-complete: a missing list file is an error, never a
silent fallback to the built-in list (L3 stays mandatory)."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.validation.dependency import integrity as integ

CORE_RELEASE = {"versions": [{"id": "19.0", "modules": ["base", "zzz_release_core"]}]}
ENTERPRISE_RELEASE = {"modules": ["zzz_release_enterprise"]}


def _write_tree(root: Path, core=None, enterprise=None):
    (root / "compatibility").mkdir(parents=True, exist_ok=True)
    if core is not None:
        (root / "compatibility" / "core_modules.json").write_text(json.dumps(core), encoding="utf-8")
    if enterprise is not None:
        (root / "compatibility" / "enterprise_modules.json").write_text(json.dumps(enterprise), encoding="utf-8")


class IntegrityReaderRootTests(unittest.TestCase):
    def test_default_path_unchanged(self):
        self.assertEqual(KNOWLEDGE_ROOT / "compatibility" / "core_modules.json", integ.CORE_MODULES_FILE)
        self.assertEqual(KNOWLEDGE_ROOT / "compatibility" / "enterprise_modules.json", integ.ENTERPRISE_MODULES_FILE)
        self.assertEqual(integ.load_core_modules("19.0"),
                         integ.load_core_modules("19.0", knowledge_root=KNOWLEDGE_ROOT))
        self.assertEqual(integ.load_enterprise_modules(),
                         integ.load_enterprise_modules(knowledge_root=KNOWLEDGE_ROOT))

    def test_release_root_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tree(root, CORE_RELEASE, ENTERPRISE_RELEASE)
            self.assertEqual(integ.load_core_modules("19.0", knowledge_root=root),
                             frozenset({"base", "zzz_release_core"}))
            self.assertIsNone(integ.load_core_modules("99.0", knowledge_root=root))
            self.assertEqual(integ.load_enterprise_modules(knowledge_root=root),
                             frozenset({"zzz_release_enterprise"}))
            self.assertNotIn("zzz_release_core", integ.load_core_modules("19.0") or frozenset())

            module = root / "addon"
            module.mkdir()
            (module / "__manifest__.py").write_text(
                "{'name': 'addon', 'version': '19.0.1.0.0', 'depends': ['zzz_release_core']}", encoding="utf-8")
            release_findings, _ = integ.check_integrity([module], target_version="19.0", knowledge_root=root)
            default_findings, _ = integ.check_integrity([module], target_version="19.0")
            self.assertEqual([], [f for f in release_findings if "zzz_release_core" in f.matched])
            self.assertTrue(any("zzz_release_core" in f.matched for f in default_findings))

    def test_missing_file_in_release_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tree(root, core=CORE_RELEASE)  # enterprise_modules.json missing from the release
            with self.assertRaises(KnowledgeReleaseError):
                integ.load_enterprise_modules(knowledge_root=root)
            module = root / "addon"
            module.mkdir()
            (module / "__manifest__.py").write_text("{'name': 'addon', 'version': '19.0.1.0.0', 'depends': []}",
                                                    encoding="utf-8")
            with self.assertRaises(KnowledgeReleaseError):
                integ.check_integrity([module], target_version="19.0", knowledge_root=root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tree(root, enterprise=ENTERPRISE_RELEASE)  # core_modules.json missing from the release
            with self.assertRaises(KnowledgeReleaseError):
                integ.load_core_modules("19.0", knowledge_root=root)


if __name__ == "__main__":
    unittest.main()
