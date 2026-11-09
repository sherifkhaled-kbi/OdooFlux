"""Capability comparison (feature 012, plan addendum C3): lost, downgraded, changed, added, retired, unchanged."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.update.capability import (CapabilityError, DETECT_ONLY, DRAFT, FIX_ENABLED, RETIRED,
                                                   capabilities, compare)


def _row(rid, maturity=DETECT_ONLY, **extra):
    row = {"id": rid, "step": "16-17", "category": "python_runtime", "file_kinds": ["python"], "severity": "WARNING",
           "maturity": maturity, "risk": "LOW", "evidence": [], "detector_ref": "pkg.mod:detect",
           "fixer_ref": None, "params": {"callee": "x"}, "tests": {"positive": "T", "negative": "T",
                                                                  "idempotence": "T"},
           "message": "m", "suggestion": "s"}
    row.update(extra)
    return row


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self._n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def _release(self, rows) -> Path:
        """A release-shaped directory holding `rows` under <dir>/knowledge/compatibility/."""
        self._n += 1
        root = self.base / f"rel{self._n}"
        (root / "knowledge" / "compatibility").mkdir(parents=True)
        (root / "knowledge" / "compatibility" / "16-17.rules.json").write_text(json.dumps(rows) + "\n",
                                                                               encoding="utf-8")
        return root

    def test_identical_releases_are_all_unchanged(self):
        rows = [_row("16-17.python.a"), _row("16-17.python.b", FIX_ENABLED)]
        diff = compare(self._release(rows), self._release(rows))
        self.assertEqual(diff.to_dict(), {"lost": [], "downgraded": [], "changed": [], "added": [], "unchanged": 2})

    def test_lost_rule_is_reported(self):
        old = self._release([_row("16-17.python.a"), _row("16-17.python.b")])
        new = self._release([_row("16-17.python.a")])
        diff = compare(old, new)
        self.assertEqual(diff.lost, ("16-17.python.b",))
        self.assertEqual(diff.unchanged, 1)

    def test_downgrade_is_reported_with_from_and_to(self):
        old = self._release([_row("16-17.python.a", FIX_ENABLED)])
        new = self._release([_row("16-17.python.a", DETECT_ONLY)])
        diff = compare(old, new).to_dict()
        self.assertEqual(diff["downgraded"], [{"id": "16-17.python.a", "from": FIX_ENABLED, "to": DETECT_ONLY}])
        self.assertEqual(diff["changed"], [])

    def test_downgrade_with_other_field_change_names_only_the_other_field(self):
        old = self._release([_row("16-17.python.a", FIX_ENABLED)])
        new = self._release([_row("16-17.python.a", DETECT_ONLY, detector_ref="pkg.mod:other")])
        diff = compare(old, new).to_dict()
        self.assertEqual(len(diff["downgraded"]), 1)
        self.assertEqual(diff["changed"], [{"id": "16-17.python.a", "fields": ["detector_ref"]}])

    def test_changed_fields_are_named(self):
        old = self._release([_row("16-17.python.a", params={"callee": "x"})])
        new = self._release([_row("16-17.python.a", params={"callee": "y"}, file_kinds=["xml"])])
        diff = compare(old, new).to_dict()
        self.assertEqual(diff["changed"], [{"id": "16-17.python.a",
                                            "fields": ["detector_params", "fixer_params", "file_kinds"]}])
        self.assertEqual(diff["downgraded"], [])

    def test_non_executable_fields_do_not_count_as_changes(self):
        old = self._release([_row("16-17.python.a", message="old text")])
        new = self._release([_row("16-17.python.a", message="new text", severity="INFO")])
        self.assertEqual(compare(old, new).unchanged, 1)

    def test_upgrade_reports_maturity_in_changed_fields(self):
        old = self._release([_row("16-17.python.a", DETECT_ONLY)])
        new = self._release([_row("16-17.python.a", FIX_ENABLED)])
        diff = compare(old, new).to_dict()
        self.assertEqual(diff["changed"], [{"id": "16-17.python.a", "fields": ["maturity"]}])
        self.assertEqual(diff["downgraded"], [])

    def test_added_rule_is_reported(self):
        old = self._release([_row("16-17.python.a")])
        new = self._release([_row("16-17.python.a"), _row("16-17.python.new")])
        self.assertEqual(compare(old, new).added, ("16-17.python.new",))

    def test_prev_none_marks_everything_added(self):
        new = self._release([_row("16-17.python.a"), _row("16-17.python.b")])
        diff = compare(None, new)
        self.assertEqual(diff.added, ("16-17.python.a", "16-17.python.b"))
        self.assertEqual(diff.lost, ())
        self.assertEqual(diff.unchanged, 0)

    def test_explicit_retirement_counts_as_lost(self):
        old = self._release([_row("16-17.python.a", DETECT_ONLY)])
        new = self._release([_row("16-17.python.a", RETIRED, retired_reason="superseded upstream")])
        diff = compare(old, new).to_dict()
        self.assertEqual(diff["lost"], ["16-17.python.a"])
        self.assertEqual(diff["downgraded"], [])

    def test_rule_already_retired_and_absent_is_not_a_loss(self):
        old = self._release([_row("16-17.python.a", RETIRED, retired_reason="old")])
        new = self._release([])
        self.assertEqual(compare(old, new).lost, ())

    def test_swapped_rule_id_with_equal_counts_is_lost_plus_added(self):
        old = self._release([_row("16-17.python.a"), _row("16-17.python.b")])
        new = self._release([_row("16-17.python.a"), _row("16-17.python.c")])
        diff = compare(old, new)
        self.assertEqual(diff.lost, ("16-17.python.b",))
        self.assertEqual(diff.added, ("16-17.python.c",))
        self.assertEqual(diff.unchanged, 1)

    def test_draft_to_detect_only_is_an_upgrade_not_a_downgrade(self):
        old = self._release([_row("16-17.python.a", DRAFT)])
        new = self._release([_row("16-17.python.a", DETECT_ONLY)])
        self.assertEqual(compare(old, new).downgraded, ())

    def test_exec_digest_ignores_descriptive_fields(self):
        a = capabilities(self._release([_row("16-17.python.a", message="one")]))["16-17.python.a"]
        b = capabilities(self._release([_row("16-17.python.a", message="two")]))["16-17.python.a"]
        c = capabilities(self._release([_row("16-17.python.a", detector_ref="pkg.mod:z")]))["16-17.python.a"]
        self.assertEqual(a.exec_digest, b.exec_digest)
        self.assertNotEqual(a.exec_digest, c.exec_digest)

    def test_duplicate_rule_id_is_refused(self):
        release = self._release([_row("16-17.python.a"), _row("16-17.python.a")])
        with self.assertRaises(CapabilityError) as ctx:
            capabilities(release)
        self.assertEqual(ctx.exception.code, "capability.duplicate_rule_id")

    def test_unknown_maturity_is_refused(self):
        release = self._release([_row("16-17.python.a", "MYSTERY")])
        with self.assertRaises(CapabilityError) as ctx:
            capabilities(release)
        self.assertEqual(ctx.exception.code, "capability.unknown_maturity")

    def test_unreadable_rule_file_is_refused_not_read_as_lost(self):
        root = self.base / "broken"
        (root / "knowledge" / "compatibility").mkdir(parents=True)
        (root / "knowledge" / "compatibility" / "16-17.rules.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(CapabilityError) as ctx:
            capabilities(root)
        self.assertEqual(ctx.exception.code, "capability.rules_unreadable")


if __name__ == "__main__":
    unittest.main()
