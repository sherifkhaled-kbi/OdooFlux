"""TST-003-037 (REQ-ARC-002): top-level directories of src/odooflux match PROJECT_STRUCTURE.md."""

import unittest

from ._setup import SRC

ALLOWED = {"ai", "analyzers", "cli", "core", "dependencies", "discovery", "knowledge", "parsers",
           "reporting", "rules", "transformers", "utils", "validation", "versions"}
FILES = {"__init__.py", "__main__.py", "builtins.py"}


def unknown_entries(names) -> list:
    return sorted(n for n in names if n not in ALLOWED | FILES and not n.startswith((".", "__pycache__")))


class StructureTests(unittest.TestCase):
    def test_top_level_matches_project_structure(self):
        present = [p.name for p in (SRC / "odooflux").iterdir()]
        self.assertEqual(unknown_entries(present), [])

    def test_unknown_directory_fails(self):
        self.assertEqual(unknown_entries(["core", "experiments"]), ["experiments"])


if __name__ == "__main__":
    unittest.main()
