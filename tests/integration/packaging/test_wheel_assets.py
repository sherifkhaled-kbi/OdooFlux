"""T025/T026 (FC A-10): a built wheel contains every runtime asset the loaders read."""

import sys
import unittest
from pathlib import Path

from . import _wheel

PKG = _wheel.REPO / "src" / "odooflux"
ASSET_SUFFIXES = {".json"}
REQUIRED_DIRS = ("knowledge/compatibility", "knowledge/evidence", "knowledge/compatibility/view_index",
                 "knowledge/schemas", "knowledge/official_sources")


def source_assets() -> set:
    """Every non-code data file under the package: all of them are runtime data (JSON)."""
    found = {p.relative_to(PKG.parent).as_posix() for p in PKG.rglob("*") if p.is_file()
             and "__pycache__" not in p.parts and p.suffix in ASSET_SUFFIXES}
    return found


def files_read_by_loaders() -> set:
    """Files under the package that the real loaders open (audit hook on ``open``), exercised end to end."""
    opened: set = set()
    active = [True]

    def hook(event, args):
        if active[0] and event == "open" and isinstance(args[0], (str, Path)):
            path = Path(args[0])
            try:
                opened.add(path.resolve().relative_to(PKG.parent.resolve()).as_posix())
            except ValueError:
                pass

    sys.addaudithook(hook)
    try:
        from odooflux.knowledge.loader import load_knowledge
        from odooflux.reporting.model.schema_check import SCHEMA_FILE
        from odooflux.validation.dependency.integrity import load_core_modules
        from odooflux.versions.registry.loader import KNOWLEDGE_FILE, load_version_data
        from odooflux.dependencies.core_modules import load_replaced_by
        load_knowledge()
        load_version_data(KNOWLEDGE_FILE)
        load_core_modules("18.0")
        load_replaced_by("16.0")
        SCHEMA_FILE.read_bytes()
    finally:
        active[0] = False
    return {n for n in opened if n.endswith(".json")}


@unittest.skipIf(_wheel.tooling_gap(), _wheel.tooling_gap() or "n/a")
class WheelAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.names = _wheel.wheel_names(_wheel.build_wheel())

    def test_every_source_asset_is_in_the_wheel(self):
        missing = sorted(a for a in source_assets() if a not in self.names)
        self.assertEqual(missing, [], f"{len(missing)} runtime assets missing from the wheel")

    def test_every_file_a_loader_reads_is_in_the_wheel(self):
        read = files_read_by_loaders()
        self.assertGreater(len(read), 50, "the loaders were expected to read the evidence and rule files")
        self.assertEqual(sorted(n for n in read if n not in self.names), [])

    def test_required_directories_are_populated(self):
        for directory in REQUIRED_DIRS:
            prefix = f"odooflux/{directory}/"
            self.assertTrue(any(n.startswith(prefix) and n.endswith(".json") for n in self.names), prefix)
        self.assertIn("odooflux/reporting/model/report.schema.json", self.names)
        self.assertIn("odooflux/knowledge/gaps.json", self.names)

    def test_no_bytecode_or_cache_in_the_wheel(self):
        self.assertEqual([n for n in self.names if "__pycache__" in n or n.endswith(".pyc")], [])


class AssetEnumerationTests(unittest.TestCase):
    def test_enumeration_is_not_empty(self):
        self.assertGreater(len(source_assets()), 200)


if __name__ == "__main__":
    unittest.main()
