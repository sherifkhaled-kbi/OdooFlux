"""TST-011-025 (REQ-KAP-018, REQ-KAP-027): the `promote` verb (T025).

`promote` moves a manual rule to FIX_ENABLED only when promotion gates 1 to 5 (release/safety.py, provenance-backed)
pass and a non-empty approval reference is given that is not the promoter's own identity. A success writes one
`promote` revision to the history sidecar. A refusal changes nothing. Every test works on a copy of the built-in data
directories inside a temporary directory; the repository copy is only read.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.authoring import history as h
from odooflux.knowledge.authoring import ops
from odooflux.knowledge.authoring import promote as p
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge

DATA_DIRS = ("evidence", "compatibility", "official_sources")
RULE_ID = "17-18.manual.promote-example"
EVIDENCE_ID = "EV-901"
APPROVAL = "APR-2026-001"
AUTHOR = "maintainer"
AT = "2026-11-08T10:00:00Z"
SOURCE_REVISION = "9ef8d62331b128bcd288528e4639e0901d85fcc8"


def _snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _evidence_record() -> dict:
    template = json.loads((KNOWLEDGE_ROOT / "evidence" / "EV-112.json").read_text(encoding="utf-8"))
    template.update({
        "id": EVIDENCE_ID,
        "rule_ids": [],
        "official": True,
        "source_id": "odoo-community-17.0",
        "url": f"https://github.com/odoo/odoo/blob/{SOURCE_REVISION}/odoo/addons/base/models/ir_ui_view.py#L163",
        "status": "DOCUMENTED_NOT_TESTED",
    })
    for location in template["locations"]:
        location["content_sha256"] = "d" * 64
    return template


def _provenance() -> list:
    return [{
        "source_id": "odoo-community-17.0",
        "revision": SOURCE_REVISION,
        "snapshot_digest": "sha256:" + "e" * 64,
        "official": True,
        "status": "VERIFIED",
        "kind": "GIT_COMMUNITY",
        "url": "https://github.com/odoo/odoo/",
    }]


def _rule_row() -> dict:
    return {
        "id": RULE_ID,
        "step": "17-18",
        "category": "python_orm",
        "file_kinds": ["python"],
        "severity": "WARNING",
        "risk": "LOW",
        "evidence": [EVIDENCE_ID],
        "detector_ref": "odooflux.rules.python.generic:flag_name",
        "fixer_ref": "odooflux.rules.python.generic:rename_name",
        "review_required": False,
        "params": {"qualified": "odoo.exceptions.Warning", "new_name": "UserError"},
        "tests": {"positive": "TST-PROMO-1", "negative": "TST-PROMO-2", "idempotence": "TST-PROMO-3"},
        "conflicts_with": [],
        "message": "promote test rule",
    }


class PromoteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.tree = self.base / "tree"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")
        (self.base / "provenance").mkdir()
        (self.base / "provenance" / "sources.json").write_text(json.dumps(_provenance()), encoding="utf-8")
        (self.tree / "evidence" / f"{EVIDENCE_ID}.json").write_text(json.dumps(_evidence_record()), encoding="utf-8")
        ops.create_rule(self.tree, _rule_row(), evidence=[EVIDENCE_ID], author=AUTHOR, at=AT)

    def tearDown(self):
        self._tmp.cleanup()

    def _rule_file(self) -> Path:
        return self.tree / "compatibility" / "17-18.rules.json"

    def _mutate_rule(self, **changes):
        path = self._rule_file()
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            if row["id"] == RULE_ID:
                for key, value in changes.items():
                    if value is _DROP:
                        row.pop(key, None)
                    else:
                        row[key] = value
        path.write_text(json.dumps(rows), encoding="utf-8")

    def _promote(self, approval=APPROVAL, author=AUTHOR):
        return p.promote(self.tree, RULE_ID, approval=approval, author=author, at=AT)

    def _refused_unchanged(self, before, expected_gate=None):
        with self.assertRaises(p.PromoteError) as ctx:
            self._promote()
        if expected_gate is not None:
            gates = {f["gate"] for f in ctx.exception.findings}
            self.assertIn(expected_gate, gates, ctx.exception.findings)
        self.assertEqual(before, _snapshot(self.tree), "a refused promotion must change nothing")

    def test_baseline_rule_is_promotable(self):
        result = self._promote()
        self.assertEqual("FIX_ENABLED", result["maturity"])

    def test_promote_gates(self):
        # one case per gate: each mutation breaks exactly one gate on an otherwise promotable rule
        other_fix = next(r["id"] for r in load_knowledge(KNOWLEDGE_ROOT).rules if r.get("maturity") == "FIX_ENABLED")
        cases = {
            1: lambda: self._mutate_rule(evidence=[]),
            2: lambda: self._drop_evidence_field("target_applicability"),
            3: lambda: self._mutate_rule(tests={"positive": "a", "negative": "b"}),
            4: lambda: self._mutate_rule(conflicts_with=[other_fix]),
            5: lambda: self._mutate_rule(fixer_ref=None),
        }
        for gate, break_it in cases.items():
            with self.subTest(gate=gate):
                self._tmp.cleanup()
                self.setUp()
                break_it()
                self._refused_unchanged(_snapshot(self.tree), expected_gate=gate)

    def _drop_evidence_field(self, field):
        path = self.tree / "evidence" / f"{EVIDENCE_ID}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record.pop(field, None)
        path.write_text(json.dumps(record), encoding="utf-8")

    def test_gate1_unsupported_official_claim_refused(self):
        (self.base / "provenance" / "sources.json").unlink()
        self._refused_unchanged(_snapshot(self.tree), expected_gate=1)

    def test_promote_writes_revision(self):
        before = h.load_history(self.tree, RULE_ID)["entries"]
        result = self._promote()
        self.assertEqual("FIX_ENABLED", result["maturity"])
        rows = json.loads(self._rule_file().read_text(encoding="utf-8"))
        self.assertEqual("FIX_ENABLED", next(r for r in rows if r["id"] == RULE_ID)["maturity"])
        doc = h.load_history(self.tree, RULE_ID)
        self.assertEqual(len(before) + 1, len(doc["entries"]))
        last = doc["entries"][-1]
        self.assertEqual("promote", last["action"])
        self.assertEqual(APPROVAL, last["provenance"]["approval"])
        self.assertEqual(AUTHOR, doc["created_by"])
        self.assertEqual(before[-1]["rev"] + 1, last["rev"])

    def test_no_approval_refused(self):
        before = _snapshot(self.tree)
        for approval in (None, "", "   "):
            with self.subTest(approval=approval):
                with self.assertRaises(p.PromoteError):
                    self._promote(approval=approval)
                self.assertEqual(before, _snapshot(self.tree))

    def test_self_approval_refused(self):
        before = _snapshot(self.tree)
        with self.assertRaises(p.PromoteError):
            self._promote(approval=AUTHOR)
        self.assertEqual(before, _snapshot(self.tree))

    def test_builtin_rule_is_not_promoted_here(self):
        builtin = next(r["id"] for r in load_knowledge(KNOWLEDGE_ROOT).rules
                       if r.get("maturity") == "DETECT_ONLY" and r.get("origin") is None)
        with self.assertRaises(p.PromoteError):
            p.promote(self.tree, builtin, approval=APPROVAL, author=AUTHOR, at=AT)


_DROP = object()


if __name__ == "__main__":
    unittest.main()
