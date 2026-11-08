"""TST-011-080 (REQ-KAP-036, REQ-KAP-005): only the modules listed in ALLOW may reference `KNOWLEDGE_ROOT` (the built-in
knowledge tree) directly. Every other reader receives a knowledge root as an argument, so an installed release is
never silently ignored. A new module that needs the built-in path must be added here with a reason.

The allow-list must also stay exact: an entry whose module no longer references `KNOWLEDGE_ROOT` fails the test, so
the list cannot go stale.
"""

import re
import tempfile
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[4] / "src" / "odooflux"
REFERENCE = re.compile(r"\bKNOWLEDGE_ROOT\b")

# path relative to src/odooflux -> one-line reason
ALLOW = {
    "knowledge/loader.py": "defines KNOWLEDGE_ROOT and the default root of load_knowledge",
    "knowledge/release/model.py": "default root of builtin_handle (the implicit built-in release)",
    "knowledge/release/builtin.py": "default root of builtin_digest and builtin_descriptor",
    "knowledge/view_index.py": "VIEW_INDEX_DIR default for the view-index reader (root argument is optional)",
    "knowledge/runtime_runs.py": "loads the runtime_runs schema shipped with the package (not a data reader)",
    "knowledge/checks.py": "loads the knowledge schemas shipped with the package (not a data reader)",
    "knowledge/extract/accounting.py": "loads the file_accounting schema shipped with the package",
    "knowledge/acquisition/sources.py": "loads the source_registry schema and the built-in allow-list",
    "knowledge/package/validate.py": "loads the schemas shipped with the package for package validation",
    "knowledge/candidates/evidence_builder.py": "evidence schema path shipped with the package (re-exported)",
    "knowledge/authoring/history.py": "loads the rule_history schema shipped with the package",
    "knowledge/authoring/checks.py": "decides whether a tree is the built-in tree (strict-builtin gate)",
    "knowledge/authoring/rule_store.py": "loads the rule_metadata schema shipped with the package",
    "knowledge/coverage/manifest.py": "loads the coverage_manifest schema shipped with the package",
    "knowledge/ledger/ledger.py": "loads the change_ledger schema shipped with the package",
    "validation/static/rng.py": "default RNG map file when no knowledge root is given (T075)",
    "validation/runtime/docker_env.py": "default runtime_images.json when no knowledge root is given (T076)",
    "validation/dependency/integrity.py": "default core and Enterprise list files when no knowledge root is given (T077)",
    "cli/knowledge.py": "default --path of the knowledge CLI commands (the built-in tree)",
    "cli/kap_rule.py": "identifies the built-in tree for the --strict-builtin rule (REQ-KAP-020)",
    "cli/support_statement.py": "default statement input and repository root (T078)",
}


def find_references(pkg: Path) -> set:
    """Relative posix paths of every .py file under `pkg` that mentions KNOWLEDGE_ROOT as a name."""
    found = set()
    for file in pkg.rglob("*.py"):
        if REFERENCE.search(file.read_text(encoding="utf-8")):
            found.add(file.relative_to(pkg).as_posix())
    return found


class KnowledgeRootGuardTests(unittest.TestCase):
    def test_guard_no_stray_references(self):
        found = find_references(PKG)
        stray = sorted(found - set(ALLOW))
        stale = sorted(set(ALLOW) - found)
        self.assertEqual(stray, [], "modules outside the allow-list reference KNOWLEDGE_ROOT")
        self.assertEqual(stale, [], "allow-list entries that no longer reference KNOWLEDGE_ROOT")

    def test_guard_flags_a_planted_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "planted.py").write_text("from odooflux.knowledge.loader import KNOWLEDGE_ROOT\n", encoding="utf-8")
            (root / "clean.py").write_text("X = 1\n", encoding="utf-8")
            self.assertEqual(find_references(root), {"planted.py"})


if __name__ == "__main__":
    unittest.main()
