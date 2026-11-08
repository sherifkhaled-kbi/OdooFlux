"""TST-011-053 (REQ-KAP-014, REQ-KAP-012, REQ-KAP-013): `knowledge extract` and `knowledge ledger` commands.

Runs `odooflux.cli.knowledge.main` on snapshot files written from in-memory trees (real `build_snapshot`, `BlobStore`).
Covers the extract output (ledger and accounting files, determinism), disposition rationale rules, and confirm, which is
manual only: an AI actor or an automatic run never confirms, and confirm always records the reviewer.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from odooflux.cli import knowledge
from odooflux.cli.kap_extract import full_registry
from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.extract import driver
from odooflux.knowledge.extract.accounting import check_document
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.parsers.javascript import treesitter_adapter
from odooflux.builtins import build_registries  # composition root: the document adapters the KAP tests inject
REGISTRIES = build_registries()
TOOLKIT = REGISTRIES.extract_toolkit

ADDON = "addons/sale_demo"
MODEL = "models/sale_order.py"

BEFORE = '''from odoo import fields, models


class SaleDemoOrder(models.Model):
    _name = 'sale.demo.order'

    name = fields.Char(string='Name')

    def compute_total(self, tax=0.0):
        return tax

    def get_amount_old(self):
        """Return the amount."""
        return 0
'''
AFTER = '''from odoo import fields, models


class SaleDemoOrder(models.Model):
    _name = 'sale.demo.order'

    name = fields.Char(string='Name')
    priority = fields.Integer(string='Priority', default=0)

    def compute_total(self, tax=0.0, currency=None):
        return tax

    def get_amount(self):
        """Return the amount.

        .. versionchanged:: 17.0
           Replaces ``get_amount_old``.
        """
        return 0
'''


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = knowledge.main(argv, registries=REGISTRIES)
        except SystemExit as exc:  # argparse usage errors
            code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue()


class ExtractCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "objects")
        self.from_file = self._snapshot_file("from", BEFORE)
        self.to_file = self._snapshot_file("to", AFTER)

    def tearDown(self):
        self._tmp.cleanup()

    def _snapshot_file(self, name, model_text):
        root = self.base / f"tree-{name}"
        target = root / ADDON / MODEL
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(model_text.encode("utf-8"))
        snapshot = build_snapshot(root, "src", f"rev-{name}", self.store, created_at="2026-01-01T00:00:00Z")
        path = self.base / f"{name}.snapshot.json"
        path.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
        return path

    def extract(self, out_name):
        out = self.base / out_name
        return _run(["extract", "--from", str(self.from_file), "--to", str(self.to_file), "--step", "01-02",
                     "--blobs", str(self.base / "objects"), "--out", str(out)]), out / "01-02.ledger.json"

    def find(self, ledger_path, subject):
        for record in Ledger.load(ledger_path).records():
            if record["subject_key"] == subject:
                return record
        raise AssertionError(f"no ledger record for {subject}")


class TestExtract(ExtractCase):
    def test_extract_cli_writes_ledger_and_accounting(self):
        (code, _, err), ledger_path = self.extract("out")
        self.assertEqual(code, 0, err)
        ledger = Ledger.load(ledger_path)
        self.assertEqual(ledger.verify(), [])
        classes = {r["class"] for r in ledger.records()}
        self.assertIn("SIGNATURE_CHANGED", classes)
        self.assertIn("ADDED", classes)
        self.assertIn("REPLACEMENT_CANDIDATE", classes)
        accounting = json.loads((self.base / "out" / "01-02.accounting.json").read_text(encoding="utf-8"))
        self.assertEqual(check_document(accounting), [])
        self.assertEqual(accounting["totals"]["PENDING"], 0)

    def test_extract_cli_deterministic(self):
        (code_a, _, _), first = self.extract("run-a")
        (code_b, _, _), second = self.extract("run-b")
        self.assertEqual((code_a, code_b), (0, 0))
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_cli_changed_unsupported_js_is_unknown_in_ledger(self):
        if treesitter_adapter.available():
            self.skipTest("the JavaScript adapter is present, so the file is analysed, not unsupported")
        js = ADDON + "/static/src/js/demo.js"
        root = self.base / "tree-js"
        for rel, text in ((ADDON + "/" + MODEL, AFTER), (js, "export const A = 1;\n")):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
        snapshot = build_snapshot(root, "src", "rev-js", self.store, created_at="2026-01-01T00:00:00Z")
        to_js = self.base / "js.snapshot.json"
        to_js.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
        out = self.base / "js-out"
        code, _, err = _run(["extract", "--from", str(self.from_file), "--to", str(to_js), "--step", "01-02",
                             "--blobs", str(self.base / "objects"), "--out", str(out)])
        self.assertEqual(code, 0, err)
        record = self.find(out / "01-02.ledger.json", js)
        self.assertEqual((record["class"], record["disposition"], record["domain"]), ("UNKNOWN", "UNRESOLVED",
                                                                                     "js_owl"))
        self.assertIn("NO_JS_ADAPTER", record["detail"]["detail"])

    def test_full_registry_is_the_default_registry(self):
        self.assertEqual(sorted(type(e).__name__ for e in full_registry()),
                         sorted(type(e).__name__ for e in driver.default_registry()))

    def test_rerun_keeps_manual_disposition(self):
        self.extract("out")
        ledger_path = self.base / "out" / "01-02.ledger.json"
        cid = self.find(ledger_path, "sale.demo.order.compute_total")["change_id"]
        code, _, err = _run(["ledger", "set-disposition", cid, "NO_CUSTOM_MODULE_IMPACT", "--actor", "alice",
                             "--rationale", "reviewed", "--ledger", str(ledger_path)])
        self.assertEqual(code, 0, err)
        self.extract("out")  # second run merges into the existing ledger
        record = self.find(ledger_path, "sale.demo.order.compute_total")
        self.assertEqual(record["disposition"], "NO_CUSTOM_MODULE_IMPACT")

    def test_extract_refuses_missing_blobs_option(self):
        code, _, _ = _run(["extract", "--from", str(self.from_file), "--to", str(self.to_file), "--step", "01-02",
                            "--out", str(self.base / "x")])
        self.assertEqual(code, 2)


class TestLedgerCommands(ExtractCase):
    def setUp(self):
        super().setUp()
        self.extract("out")
        self.ledger_path = self.base / "out" / "01-02.ledger.json"

    def test_list_and_show(self):
        code, out, _ = _run(["ledger", "list", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 0)
        self.assertIn("SIGNATURE_CHANGED", out)
        cid = self.find(self.ledger_path, "sale.demo.order.compute_total")["change_id"]
        code, out, _ = _run(["ledger", "show", cid, "--ledger", str(self.ledger_path), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["change_id"], cid)
        code, _, _ = _run(["ledger", "show", "CH-0000000000000000", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 1)

    def test_set_disposition_rationale_rules(self):
        cid = self.find(self.ledger_path, "sale.demo.order.compute_total")["change_id"]
        base = ["ledger", "set-disposition", cid, "NO_CUSTOM_MODULE_IMPACT", "--actor", "alice",
                "--ledger", str(self.ledger_path)]
        code, _, _ = _run(base)
        self.assertEqual(code, 1)  # rationale required
        code, _, _ = _run(base + ["--rationale", "checked by hand"])
        self.assertEqual(code, 0)
        self.assertEqual(self.find(self.ledger_path, "sale.demo.order.compute_total")["disposition"],
                         "NO_CUSTOM_MODULE_IMPACT")

    def test_rule_disposition_needs_known_rule(self):
        cid = self.find(self.ledger_path, "sale.demo.order.compute_total")["change_id"]
        code, _, _ = _run(["ledger", "set-disposition", cid, "EXISTING_RULE_LINKED", "--actor", "alice",
                           "--rule-id", "R-1", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 1)  # no --known-rules: the rule is not in the tree

    def test_ai_actor_may_only_request_human_review(self):
        cid = self.find(self.ledger_path, "sale.demo.order.compute_total")["change_id"]
        code, _, _ = _run(["ledger", "set-disposition", cid, "NO_CUSTOM_MODULE_IMPACT", "--actor", "AI",
                           "--rationale", "looks fine", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 1)
        code, _, _ = _run(["ledger", "set-disposition", cid, "HUMAN_REVIEW", "--actor", "AI",
                           "--rationale", "needs a person", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 0)

    def test_confirm_cli_manual_only(self):
        candidate = self.find(self.ledger_path, "sale.demo.order.get_amount_old")["change_id"]
        added = self.find(self.ledger_path, "sale.demo.order.priority")["change_id"]
        # an ADDED change is never a candidate
        code, _, _ = _run(["ledger", "confirm", added, "--reviewer", "alice", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 1)
        # AI never confirms, even for a candidate
        code, _, _ = _run(["ledger", "confirm", candidate, "--reviewer", "AI", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 1)
        self.assertFalse(self.find(self.ledger_path, "sale.demo.order.get_amount_old")["confirmed"])
        # a disposition does not confirm
        _run(["ledger", "set-disposition", candidate, "HUMAN_REVIEW", "--actor", "alice", "--rationale", "x",
              "--ledger", str(self.ledger_path)])
        self.assertFalse(self.find(self.ledger_path, "sale.demo.order.get_amount_old")["confirmed"])
        # a named reviewer confirms once and is recorded
        code, _, err = _run(["ledger", "confirm", candidate, "--reviewer", "alice", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 0, err)
        record = self.find(self.ledger_path, "sale.demo.order.get_amount_old")
        self.assertTrue(record["confirmed"])
        self.assertEqual(record["history"][-1]["actor"], "alice")
        code, _, _ = _run(["ledger", "confirm", candidate, "--reviewer", "alice", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 1)  # already confirmed

    def test_confirm_requires_reviewer(self):
        candidate = self.find(self.ledger_path, "sale.demo.order.get_amount_old")["change_id"]
        code, _, _ = _run(["ledger", "confirm", candidate, "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 2)

    def test_verify_detects_tampered_history(self):
        code, _, _ = _run(["ledger", "verify", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 0)
        raw = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        raw["entries"][0]["history"][0]["actor"] = "mallory"
        self.ledger_path.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")
        code, _, _ = _run(["ledger", "verify", "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
