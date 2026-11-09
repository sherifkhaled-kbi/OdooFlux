"""Feature 012 hardening (review item 6): the certified transformer identity covers the code path that actually runs.

`FixCertifier.transformer_identity` hashes the bound fixer, the primitive and the module that holds the primitive. The
certified code also runs through the parser (`parsers.python.spans`, `parsers.python.document`), `apply_edits`
(`core.engine.edits`), the `KnowledgeRule.fix` path (`core.orchestrator.knowledge_rules`) and the loader's binding
(`rules.shared.loader`). A change in any of those modules must change the identity.
"""

import hashlib
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins as composition_root
from odooflux.knowledge.update import certification as cert
from odooflux.transformers import certify_exec

EXECUTED_MODULES = (
    "odooflux.parsers.python.spans",
    "odooflux.parsers.python.document",
    "odooflux.core.engine.edits",
    "odooflux.core.orchestrator.knowledge_rules",
    "odooflux.rules.shared.loader",
)


def _file_sha(module_name: str) -> str:
    module = __import__(module_name, fromlist=["_"])
    return hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()


class TransformerIdentityTests(unittest.TestCase):
    def setUp(self):
        cert._reset_for_tests()
        composition_root.build_context()
        self.executor = cert.trusted_executor()

    def tearDown(self):
        cert._reset_for_tests()
        composition_root.build_context()

    def test_identity_covers_every_executed_module_with_its_file_digest(self):
        # the record's `transformer` object holds only qualified_name and source_digest (schema, additionalProperties
        # false), so the module digests are folded into source_digest; the file digests are checked directly here
        identity = self.executor.transformer_identity("python.rewrite_imported_symbol")
        self.assertEqual(set(identity), {"qualified_name", "source_digest"})
        for name in EXECUTED_MODULES:
            with self.subTest(module=name):
                self.assertEqual(certify_exec._module_digest(name), _file_sha(name))

    def test_a_change_in_the_span_parser_changes_the_identity(self):
        before = self.executor.transformer_identity("python.rewrite_imported_symbol")["source_digest"]
        real = certify_exec._module_digest
        with mock.patch.object(certify_exec, "_module_digest",
                               side_effect=lambda name: "0" * 64 if name.endswith(".spans") else real(name)):
            after = self.executor.transformer_identity("python.rewrite_imported_symbol")["source_digest"]
        self.assertNotEqual(before, after)

    def test_a_change_in_apply_edits_changes_the_identity(self):
        before = self.executor.transformer_identity("python.remove_imported_decorator")["source_digest"]
        real = certify_exec._module_digest
        with mock.patch.object(certify_exec, "_module_digest",
                               side_effect=lambda name: "1" * 64 if name.endswith(".edits") else real(name)):
            after = self.executor.transformer_identity("python.remove_imported_decorator")["source_digest"]
        self.assertNotEqual(before, after)

    def test_a_change_in_the_fix_path_changes_the_identity(self):
        before = self.executor.transformer_identity("python.rewrite_imported_symbol")["source_digest"]
        real = certify_exec._module_digest
        with mock.patch.object(certify_exec, "_module_digest",
                               side_effect=lambda name: "2" * 64 if name.endswith("knowledge_rules") else real(name)):
            after = self.executor.transformer_identity("python.rewrite_imported_symbol")["source_digest"]
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
