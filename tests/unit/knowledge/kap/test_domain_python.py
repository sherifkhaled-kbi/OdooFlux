"""TST-011-048 (REQ-KAP-011): Python/ORM domain extractor on `parsers/python`.

The golden case runs the real driver over the synthetic 16.0 and 17.0 trees (`tests/fixtures/kap/make_synth_repo.py`)
with only the python_orm extractor registered. The decorator and signature case uses an inline module.
"""

import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.extract import driver as d
from odooflux.knowledge.extract.domains import python_orm
from tests.fixtures.kap import make_synth_repo as synth
from odooflux.builtins import build_registries  # composition root: the document adapters the KAP tests inject
REGISTRIES = build_registries()
TOOLKIT = REGISTRIES.extract_toolkit


def _write_tree(root: Path, files: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


class PythonGolden(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.store = BlobStore(base / "objects")
        _write_tree(base / "16", synth._TREE_16)
        _write_tree(base / "17", synth._TREE_17)
        self.before = build_snapshot(base / "16", "synth", "16", self.store, created_at="2026-01-01T00:00:00Z")
        self.after = build_snapshot(base / "17", "synth", "17", self.store, created_at="2026-01-01T00:00:00Z")
        self.result = d.extract_pair(self.before, self.after, None, python_orm.EXTRACTORS, store=self.store,
                                     step="16-17", toolkit=TOOLKIT)

    def tearDown(self):
        self._tmp.cleanup()

    def _python_changes(self):
        return {(c["class"], c["subject_key"]): c for c in self.result.drafts if c["domain"] == "python_orm"}

    def test_python_golden_extraction(self):
        changes = self._python_changes()
        self.assertEqual(changes[("ADDED", "sale.demo.order.priority")]["kind"], "field")
        self.assertEqual(changes[("SIGNATURE_CHANGED", "sale.demo.order.compute_total")]["kind"], "method")
        self.assertEqual(changes[("BEHAVIOUR_CHANGED", "sale.demo.order.check_amount")]["detail"]["basis"],
                         "body_digest")
        self.assertIn(("DEPRECATED", "sale.demo.order.compute_legacy_total"), changes)
        self.assertEqual(changes[("MOVED", "sale_demo.format_reference")]["detail"],
                         {"from_path": "addons/sale_demo/models/legacy_utils.py",
                          "to_path": "addons/sale_demo/models/sale_utils.py"})
        # replacement: the removed method is a candidate, never confirmed; the added twin is absorbed
        replacement = changes[("REPLACEMENT_CANDIDATE", "sale.demo.order.get_amount_old")]
        self.assertFalse(replacement["confirmed"])
        self.assertEqual(replacement["detail"]["to"], "sale.demo.order.get_amount")
        self.assertNotIn("sale.demo.order.get_amount", {c["subject_key"] for c in self.result.drafts})

    def test_unparsable_python_is_unknown_and_failed(self):
        # UNKNOWN drafts with reason UNSUPPORTED are files this domain does not claim (they are never silent).
        unknown = [c for c in self.result.drafts
                   if c["class"] == "UNKNOWN" and c["detail"].get("reason") != "UNSUPPORTED"]
        self.assertEqual([c["subject_key"] for c in unknown],
                         ["addons/sale_demo/models/broken_hooks.py"])
        self.assertEqual(unknown[0]["detail"]["reason"], "PARSE_FAILURE")
        states = {f["path"]: f for f in self.result.accounting["files"]}
        broken = states["addons/sale_demo/models/broken_hooks.py"]
        self.assertEqual((broken["state"], broken["reason_code"]), ("FAILED", "PARSE_ERROR"))
        self.assertEqual(states["addons/sale_demo/models/sale_order.py"]["state"], "ANALYZED")

    def test_removed_and_added_module_files_are_analysed(self):
        states = {f["path"]: f for f in self.result.accounting["files"]}
        self.assertEqual(states["addons/sale_demo/models/legacy_utils.py"]["state"], "ANALYZED")
        self.assertEqual(states["addons/sale_demo/models/sale_utils.py"]["state"], "ANALYZED")


class PythonFacts(unittest.TestCase):
    SAMPLE = '''from odoo import api, fields, models


class Sample(models.Model):
    _name = 'sample.model'

    total = fields.Float(compute='_compute_total', store=True, deprecated='use amount')

    @api.depends('amount')
    def _compute_total(self, *, scale=1, extra=None):
        return 1

    @api.constrains('total')
    def _check(self):
        pass

    def legacy(self):
        """Old helper.

        Replaces ``old_helper``.
        """
        warnings.warn('x', DeprecationWarning)
'''

    def setUp(self):
        self.facts = {(f["subject_key"], f["kind"]): f
                      for f in python_orm.EXTRACTORS[0].facts(self.SAMPLE, "addons/sample/models/sample.py", TOOLKIT)}

    def test_decorators_fields_signatures(self):
        field = self.facts[("sample.model.total", "field")]
        self.assertEqual(field["attrs"]["type"], "Float")
        self.assertEqual(field["attrs"]["keywords"]["compute"], "'_compute_total'")
        self.assertEqual(field["attrs"]["deprecated"], "'use amount'")

        method = self.facts[("sample.model._compute_total", "method")]
        self.assertEqual(method["attrs"]["args"], ["self", "scale", "extra"])
        self.assertEqual(method["attrs"]["defaults"], ["1", "None"])
        self.assertEqual(method["attrs"]["decorators"], ["api.depends('amount')"])
        self.assertNotIn("deprecated", method["attrs"])

        self.assertEqual(self.facts[("sample.model._check", "method")]["attrs"]["decorators"],
                         ["api.constrains('total')"])
        self.assertEqual(self.facts[("sample.model.legacy", "method")]["attrs"]["deprecated"],
                         "warnings.warn(DeprecationWarning)")

    def test_hint_from_docstring(self):
        hints = python_orm.EXTRACTORS[0].hints(self.SAMPLE, "addons/sample/models/sample.py", TOOLKIT)
        self.assertEqual(hints, [{"from": "sample.model.old_helper", "to": "sample.model.legacy", "source": "docs"}])

    def test_syntax_error_raises_parse_failure(self):
        with self.assertRaises(d.ParseFailure) as ctx:
            python_orm.EXTRACTORS[0].facts("def broken(:\n", "addons/x/models/bad.py", TOOLKIT)
        self.assertEqual(ctx.exception.code, "PARSE_ERROR")

    def test_token_cap_is_timeout(self):
        saved = python_orm.TOKEN_CAP
        python_orm.TOKEN_CAP = 3
        try:
            with self.assertRaises(d.ParseFailure) as ctx:
                python_orm.EXTRACTORS[0].facts(self.SAMPLE, "addons/sample/models/sample.py", TOOLKIT)
            self.assertEqual(ctx.exception.code, "TIMEOUT")
        finally:
            python_orm.TOKEN_CAP = saved

    def test_migration_scripts_are_not_python_orm(self):
        self.assertFalse(python_orm.EXTRACTORS[0].handles("addons/x/migrations/17.0.1.0.0/post-migrate.py", TOOLKIT))
        self.assertTrue(python_orm.EXTRACTORS[0].handles("addons/x/models/sale.py", TOOLKIT))


if __name__ == "__main__":
    unittest.main()
