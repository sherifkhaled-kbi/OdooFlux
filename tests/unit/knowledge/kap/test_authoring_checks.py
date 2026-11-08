"""TST-011-022 (REQ-KAP-020, REQ-KAP-005): authoring checks A001..A006 and the gated call in knowledge/checks.py.

Unit tests build an in-memory KnowledgeBase whose root is not the built-in tree, so the authoring checks run.
The built-in tree is only read (never written). Built-in output must not change unless `strict_builtin` is set.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge import checks
from odooflux.knowledge.authoring import checks as authoring
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, KnowledgeBase, load_knowledge

FAKE_ROOT = Path("/nonexistent/manual-tree")
DATA_DIRS = ("evidence", "compatibility", "official_sources")


def _rule(rid, **over):
    row = {
        "id": rid,
        "step": rid.split(".")[0],
        "category": "xml",
        "maturity": "DETECT_ONLY",
        "risk": "LOW",
        "evidence": [],
        "detector_ref": f"det.{rid}",
        "fixer_ref": None,
        "tests": [],
    }
    row.update(over)
    return row


def _kb(rules, evidence=None, root=FAKE_ROOT):
    kb = KnowledgeBase(root=root)
    kb.rules = list(rules)
    kb.evidence = dict(evidence or {})
    return kb


def _codes(findings):
    return sorted((f.code, f.pointer) for f in findings)


class AuthoringChecksTests(unittest.TestCase):
    def test_A001_duplicate_rule_id(self):
        kb = _kb([_rule("17-18.xml.a"), _rule("17-18.xml.a", detector_ref="det.other")])
        findings = authoring.check_authoring(kb)
        self.assertIn(("A001", "17-18.xml.a"), _codes(findings))
        self.assertTrue(all(f.severity == "ERROR" for f in findings if f.code == "A001"))

    def test_A001_unique_ids_pass(self):
        kb = _kb([_rule("17-18.xml.a"), _rule("17-18.xml.b")])
        self.assertEqual([f for f in authoring.check_authoring(kb) if f.code == "A001"], [])

    def test_A002_same_step_detector_and_params(self):
        kb = _kb([
            _rule("17-18.xml.a", detector_ref="det.same", params={"x": 1, "y": 2}, file_kinds=["xml"]),
            _rule("17-18.xml.b", detector_ref="det.same", params={"y": 2, "x": 1}, file_kinds=["py"]),
        ])
        self.assertIn(("A002", "17-18.xml.b"), _codes(authoring.check_authoring(kb)))

    def test_A002_different_params_pass(self):
        kb = _kb([
            _rule("17-18.xml.a", detector_ref="det.same", params={"x": 1}, file_kinds=["xml"]),
            _rule("17-18.xml.b", detector_ref="det.same", params={"x": 2}, file_kinds=["py"]),
        ])
        self.assertEqual([f for f in authoring.check_authoring(kb) if f.code == "A002"], [])

    def test_A003_unknown_conflicts_and_depends_reference(self):
        kb = _kb([
            _rule("17-18.xml.a", conflicts_with=["17-18.xml.missing"]),
            _rule("17-18.xml.b", depends_on=["17-18.xml.gone"]),
        ])
        codes = _codes(authoring.check_authoring(kb))
        self.assertIn(("A003", "17-18.xml.a"), codes)
        self.assertIn(("A003", "17-18.xml.b"), codes)

    def test_A004_depends_on_cycle(self):
        kb = _kb([
            _rule("17-18.xml.a", depends_on=["17-18.xml.b"]),
            _rule("17-18.xml.b", depends_on=["17-18.xml.a"]),
        ])
        self.assertTrue(any(f.code == "A004" for f in authoring.check_authoring(kb)))

    def test_A004_chain_without_cycle_passes(self):
        kb = _kb([
            _rule("17-18.xml.a", depends_on=["17-18.xml.b"]),
            _rule("17-18.xml.b", depends_on=["17-18.xml.c"]),
            _rule("17-18.xml.c"),
        ])
        self.assertEqual([f for f in authoring.check_authoring(kb) if f.code == "A004"], [])

    def test_A005_same_selector_overlapping_scope_is_warning_when_not_both_fix_enabled(self):
        kb = _kb([
            _rule("17-18.xml.a", detector_ref="det.same", params={"qualified": "q", "new_name": "A"},
                  file_kinds=["xml"]),
            _rule("17-18.xml.b", detector_ref="det.same", params={"qualified": "q", "new_name": "B"},
                  file_kinds=["xml", "py"]),
        ])
        findings = [f for f in authoring.check_authoring(kb) if f.code == "A005"]
        self.assertEqual([("A005", "17-18.xml.b", "WARNING")], [(f.code, f.pointer, f.severity) for f in findings])
        self.assertEqual([f for f in authoring.check_authoring(kb) if f.code == "A002"], [])

    def test_A005_same_selector_both_fix_enabled_is_error(self):
        kb = _kb([
            _rule("17-18.xml.a", detector_ref="det.same", params={"qualified": "q", "new_name": "A"},
                  file_kinds=["xml"], maturity="FIX_ENABLED"),
            _rule("17-18.xml.b", detector_ref="det.same", params={"qualified": "q", "new_name": "B"},
                  file_kinds=["xml"], maturity="FIX_ENABLED"),
        ])
        findings = [f for f in authoring.check_authoring(kb) if f.code == "A005"]
        self.assertEqual([("A005", "ERROR")], [(f.code, f.severity) for f in findings])

    def test_A005_one_fix_enabled_is_warning(self):
        kb = _kb([
            _rule("17-18.xml.a", detector_ref="det.same", params={"qualified": "q", "new_name": "A"},
                  file_kinds=["xml"], maturity="FIX_ENABLED"),
            _rule("17-18.xml.b", detector_ref="det.same", params={"qualified": "q", "new_name": "B"},
                  file_kinds=["xml"]),
        ])
        findings = [f for f in authoring.check_authoring(kb) if f.code == "A005"]
        self.assertEqual(["WARNING"], [f.severity for f in findings])

    def test_A005_different_selectors_pass_even_when_overlapping(self):
        kb = _kb([
            _rule("17-18.xml.a", detector_ref="det.same", params={"qualified": "a"}, file_kinds=["xml"],
                  maturity="FIX_ENABLED"),
            _rule("17-18.xml.b", detector_ref="det.same", params={"qualified": "b"}, file_kinds=["xml"],
                  maturity="FIX_ENABLED"),
        ])
        self.assertEqual([f for f in authoring.check_authoring(kb) if f.code == "A005"], [])

    def test_A005_unknown_param_key_is_a_selector(self):
        kb = _kb([
            _rule("17-18.xml.a", detector_ref="det.same", params={"brand_new": "a"}, file_kinds=["xml"]),
            _rule("17-18.xml.b", detector_ref="det.same", params={"brand_new": "b"}, file_kinds=["xml"]),
        ])
        self.assertEqual([f for f in authoring.check_authoring(kb) if f.code == "A005"], [])

    def test_A005_disjoint_file_kinds_pass(self):
        kb = _kb([
            _rule("17-18.xml.a", detector_ref="det.same", params={"qualified": "q", "new_name": "A"},
                  file_kinds=["xml"]),
            _rule("17-18.xml.b", detector_ref="det.same", params={"qualified": "q", "new_name": "B"},
                  file_kinds=["py"]),
        ])
        self.assertEqual([f for f in authoring.check_authoring(kb) if f.code == "A005"], [])

    def test_param_roles_classify_every_shipped_key(self):
        keys = set()
        for rule in load_knowledge(KNOWLEDGE_ROOT).rules:
            keys.update((rule.get("params") or {}).keys())
        self.assertTrue(keys)
        self.assertEqual(set(), keys - set(authoring.PARAM_ROLES), "unclassified shipped param keys")
        self.assertTrue(set(authoring.PARAM_ROLES.values()) <= {authoring.OUTPUT, authoring.SELECTOR})

    def test_selector_params_drop_output_keys_only(self):
        params = {"qualified": "q", "new_name": "A", "unknown_key": 1}
        self.assertEqual({"qualified": "q", "unknown_key": 1}, authoring.selector_params(params))

    def test_builtin_tree_has_no_a005_errors(self):
        kb = load_knowledge(KNOWLEDGE_ROOT)
        findings = authoring.check_authoring(kb)
        self.assertEqual([], [f for f in findings if f.code == "A005" and f.severity == "ERROR"])

    def test_A006_unknown_evidence(self):
        kb = _kb([_rule("17-18.xml.a", evidence=["EV-999"])], evidence={"EV-001": {"id": "EV-001"}})
        self.assertIn(("A006", "17-18.xml.a"), _codes(authoring.check_authoring(kb)))

    def test_A006_known_evidence_passes(self):
        kb = _kb([_rule("17-18.xml.a", evidence=["EV-001"])], evidence={"EV-001": {"id": "EV-001"}})
        self.assertEqual([f for f in authoring.check_authoring(kb) if f.code == "A006"], [])

    def test_retired_rules_do_not_count_as_active(self):
        kb = _kb([
            _rule("17-18.xml.a", maturity="RETIRED", retired_reason="superseded", detector_ref="det.same",
                  params={"x": 1}),
            _rule("17-18.xml.b", detector_ref="det.same", params={"x": 1}),
        ])
        self.assertEqual([f for f in authoring.check_authoring(kb) if f.code in ("A002", "A005")], [])

    def test_gate_skips_builtin_root_by_default(self):
        kb = _kb([_rule("17-18.xml.a", conflicts_with=["17-18.xml.missing"])], root=KNOWLEDGE_ROOT)
        self.assertEqual(authoring.authoring_findings(kb), [])
        self.assertTrue(authoring.authoring_findings(kb, strict_builtin=True))

    def test_gate_runs_on_manual_tree_by_default(self):
        kb = _kb([_rule("17-18.xml.a", conflicts_with=["17-18.xml.missing"])])
        self.assertIn(("A003", "17-18.xml.a"), _codes(authoring.authoring_findings(kb)))


class BuiltinOutputUnchangedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name) / "copy"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_builtin_output_unchanged(self):
        kb = load_knowledge(KNOWLEDGE_ROOT)
        findings = checks.validate_knowledge(kb)
        self.assertEqual([f for f in findings if f.code.startswith("A")], [])
        self.assertEqual(findings, checks.validate_knowledge(kb, strict_builtin=False))

    def test_strict_builtin_opens_the_gate(self):
        kb = load_knowledge(KNOWLEDGE_ROOT)
        strict = checks.validate_knowledge(kb, strict_builtin=True)
        for finding in authoring.check_authoring(kb):
            self.assertIn(finding, strict)

    def test_copied_tree_is_non_builtin_and_runs_checks(self):
        rules_file = self.tree / "compatibility" / "zz-manual.rules.json"
        rules_file.write_text(
            '[{"id": "17-18.manual.broken", "step": "17-18", "category": "xml", "maturity": "DRAFT",'
            ' "risk": "LOW", "evidence": [], "detector_ref": null, "fixer_ref": null, "tests": [],'
            ' "conflicts_with": ["17-18.manual.nowhere"]}]', encoding="utf-8")
        kb = load_knowledge(self.tree)
        codes = [f.code for f in checks.validate_knowledge(kb)]
        self.assertIn("A003", codes)


if __name__ == "__main__":
    unittest.main()
