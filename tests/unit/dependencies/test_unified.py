"""TST-012-W3d-U (feature 012, plan addendum B3/B5): unified Community + Enterprise dependency coverage.

Inventories are merged from hand-built parts through the real `inventory.merge`
(manifests are data here, never executed).
Covers: Community-only closure, custom -> Enterprise -> Community, Enterprise-dependent with and without the Enterprise
inventory for the version pair, unresolved, conflict, cycle, a tampered inventory failing closed, and no inventory
giving {}. Stdlib unittest; no network.
"""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.dependencies import unified as u
from odooflux.knowledge.update import inventory as inv

SRC, TGT = "17.0", "18.0"
PUBLIC_17, ENTERPRISE_17 = "odoo-17.0", "enterprise-17.0"
PUBLIC_18, ENTERPRISE_18 = "odoo-18.0", "enterprise-18.0"
DIGEST = "a" * 64


def record(depends):
    return {"depends": sorted(depends), "installable": True, "auto_install": False,
            "manifest_digest": DIGEST, "path_digest": "b" * 64}


def part(source_id, confidentiality, modules):
    return {"source_id": source_id, "confidentiality": confidentiality,
            "modules": {name: record(deps) for name, deps in modules.items()},
            "skipped": 0, "skipped_nested": 0, "parse_errors": []}


COMMUNITY = {"base": [], "account": ["base"], "sale": ["account", "base"]}
ENTERPRISE = {"sale_subscription": ["sale"]}


def inventory(version_pair_parts):
    return inv.merge(version_pair_parts)


def community_only(source_id):
    return inventory([part(source_id, "public", COMMUNITY)])


def with_enterprise(public_id, enterprise_id):
    return inventory([part(public_id, "public", COMMUNITY), part(enterprise_id, "enterprise", ENTERPRISE)])


class ResolveCustomTests(unittest.TestCase):
    def test_community_only_closure_is_complete(self):
        inventories = {SRC: community_only(PUBLIC_17), TGT: community_only(PUBLIC_18)}
        result = u.resolve_custom(inventories, SRC, TGT, {"mine": ["sale"]})
        cov = result.modules["mine"]
        self.assertEqual(cov.verdict, u.COMPLETE)
        self.assertEqual(cov.reasons, ())
        self.assertEqual(cov.by_family[SRC], {"public": ("account", "base", "sale")})
        self.assertFalse(cov.enterprise_dependent)
        self.assertEqual(cov.enterprise_reached, 0)

    def test_custom_to_enterprise_to_community_is_complete_with_both_inventories(self):
        inventories = {SRC: with_enterprise(PUBLIC_17, ENTERPRISE_17), TGT: with_enterprise(PUBLIC_18, ENTERPRISE_18)}
        result = u.resolve_custom(inventories, SRC, TGT, {"top": ["second"], "second": ["sale_subscription"]})
        top = result.modules["top"]
        self.assertEqual(top.verdict, u.COMPLETE, top.reasons)
        self.assertTrue(top.enterprise_dependent)
        self.assertEqual(top.enterprise_reached, 1)
        self.assertEqual(top.by_family[TGT]["enterprise"], ("sale_subscription",))
        self.assertIn("sale", top.by_family[TGT]["public"])
        self.assertEqual(result.modules["second"].verdict, u.COMPLETE)

    def test_enterprise_dependent_without_enterprise_inventory_for_target_is_incomplete(self):
        inventories = {SRC: with_enterprise(PUBLIC_17, ENTERPRISE_17), TGT: community_only(PUBLIC_18)}
        cov = u.resolve_custom(inventories, SRC, TGT, {"mine": ["sale_subscription"]}).modules["mine"]
        self.assertEqual(cov.verdict, u.INCOMPLETE)
        self.assertIn("UNRESOLVED:18.0", cov.reasons)
        self.assertIn("ENTERPRISE_INVENTORY_MISSING:18.0", cov.reasons)
        self.assertEqual(cov.unresolved, {"18.0": ("sale_subscription",)})
        self.assertTrue(cov.enterprise_dependent)

    def test_enterprise_dependent_without_enterprise_inventory_for_source_is_incomplete(self):
        inventories = {SRC: community_only(PUBLIC_17), TGT: with_enterprise(PUBLIC_18, ENTERPRISE_18)}
        cov = u.resolve_custom(inventories, SRC, TGT, {"mine": ["sale_subscription"]}).modules["mine"]
        self.assertEqual(cov.verdict, u.INCOMPLETE)
        self.assertIn("UNRESOLVED:17.0", cov.reasons)
        self.assertIn("ENTERPRISE_INVENTORY_MISSING:17.0", cov.reasons)

    def test_unresolved_dependency_is_listed_and_incomplete(self):
        inventories = {SRC: community_only(PUBLIC_17), TGT: community_only(PUBLIC_18)}
        cov = u.resolve_custom(inventories, SRC, TGT, {"mine": ["ghost_module"]}).modules["mine"]
        self.assertEqual(cov.verdict, u.INCOMPLETE)
        self.assertEqual(cov.unresolved, {SRC: ("ghost_module",), TGT: ("ghost_module",)})
        self.assertEqual(cov.reasons, ("UNRESOLVED:17.0", "UNRESOLVED:18.0"))

    def test_conflicted_dependency_is_incomplete(self):
        clash = inv.merge([part(PUBLIC_17, "public", {"shared": []}),
                           part(ENTERPRISE_17, "enterprise", {"shared": []})])
        inventories = {SRC: clash, TGT: community_only(PUBLIC_18)}
        cov = u.resolve_custom(inventories, SRC, TGT, {"mine": ["shared"]}).modules["mine"]
        self.assertEqual(cov.verdict, u.INCOMPLETE)
        self.assertIn("CONFLICTED:17.0", cov.reasons)
        self.assertEqual(cov.conflicted[SRC], ("shared",))

    def test_cycle_is_reported_without_blocking_a_complete_verdict(self):
        inventories = {SRC: community_only(PUBLIC_17), TGT: community_only(PUBLIC_18)}
        result = u.resolve_custom(inventories, SRC, TGT, {"a": ["b"], "b": ["a"]})
        for name in ("a", "b"):
            self.assertTrue(result.modules[name].in_cycle)
            self.assertEqual(result.modules[name].verdict, u.COMPLETE)

    def test_missing_inventory_for_one_side_is_incomplete(self):
        result = u.resolve_custom({TGT: community_only(PUBLIC_18)}, SRC, TGT, {"mine": ["sale"]})
        self.assertEqual(result.modules["mine"].verdict, u.INCOMPLETE)
        self.assertEqual(result.modules["mine"].reasons, ("INVENTORY_MISSING:17.0",))

    def test_module_name_outside_the_inventory_form_is_incomplete(self):
        inventories = {SRC: community_only(PUBLIC_17), TGT: community_only(PUBLIC_18)}
        result = u.resolve_custom(inventories, SRC, TGT, {"Bad-Name": ["sale"], "ok": ["sale"]})
        self.assertEqual(result.modules["Bad-Name"].reasons, ("BAD_MODULE_NAME",))
        self.assertEqual(result.modules["ok"].verdict, u.COMPLETE)

    def test_withheld_records_and_messages_name_only_dependencies_and_counts(self):
        inventories = {SRC: with_enterprise(PUBLIC_17, ENTERPRISE_17), TGT: community_only(PUBLIC_18)}
        result = u.resolve_custom(inventories, SRC, TGT, {"mine": ["sale_subscription", "ghost"], "fine": ["sale"]})
        records = u.withheld_records(result)
        self.assertEqual(sorted(records), ["mine"])
        message = records["mine"]["message"]
        self.assertIn("ghost", message)
        self.assertIn("1 Enterprise module(s) reached", message)
        self.assertNotIn(DIGEST, message)
        self.assertNotIn("manifest", message.lower())
        self.assertIn("Auto-fix edits are withheld", message)


class LoadInventoriesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "knowledge"

    def write(self, label, document):
        directory = self.root / "inventory"
        directory.mkdir(parents=True, exist_ok=True)
        text = json.dumps(document, sort_keys=True, indent=2) + "\n"
        (directory / f"{label}.json").write_text(text, encoding="utf-8")

    def test_no_inventory_returns_empty_mapping(self):
        self.assertEqual(u.load_inventories(self.root), {})
        (self.root / "inventory").mkdir(parents=True)
        self.assertEqual(u.load_inventories(self.root), {})

    def test_verified_inventories_are_loaded_by_version_label(self):
        self.write(SRC, community_only(PUBLIC_17))
        loaded = u.load_inventories(self.root)
        self.assertEqual(sorted(loaded), [SRC])
        self.assertEqual(loaded[SRC]["digest"], community_only(PUBLIC_17)["digest"])

    def test_tampered_inventory_fails_closed(self):
        document = community_only(PUBLIC_17)
        document["modules"]["sale"]["depends"] = ["base"]  # content changed, digest not recomputed
        self.write(SRC, document)
        with self.assertRaises(u.UnifiedError) as ctx:
            u.load_inventories(self.root)
        self.assertEqual(ctx.exception.code, "INVENTORY_INVALID")
        self.assertIn("DIGEST_MISMATCH", str(ctx.exception))
        self.assertNotIn("sale", str(ctx.exception))  # no inventory content in the error

    def test_unexpected_entry_fails_closed(self):
        self.write(SRC, community_only(PUBLIC_17))
        (self.root / "inventory" / "notes.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(u.UnifiedError) as ctx:
            u.load_inventories(self.root)
        self.assertEqual(ctx.exception.code, "INVENTORY_UNEXPECTED_ENTRY")

    def test_inventory_path_that_is_a_file_fails_closed(self):
        self.root.mkdir(parents=True)
        (self.root / "inventory").write_text("x", encoding="utf-8")
        with self.assertRaises(u.UnifiedError) as ctx:
            u.load_inventories(self.root)
        self.assertEqual(ctx.exception.code, "INVENTORY_NOT_A_DIRECTORY")

    def test_migration_coverage_is_none_without_an_inventory_for_the_pair(self):
        self.write("18.5", community_only(PUBLIC_18))
        self.assertIsNone(u.migration_coverage(self.root, SRC, TGT, {"mine": ["sale"]}))
        self.assertIsNone(u.migration_coverage(Path(self._tmp.name) / "none", SRC, TGT, {"mine": ["sale"]}))


if __name__ == "__main__":
    unittest.main()
