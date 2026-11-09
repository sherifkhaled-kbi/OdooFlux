"""TST-012-T06b (feature 012, plan addendum B3): unified Community + Enterprise module inventory and dependency resolver.

Snapshots are built with the real `build_snapshot` and `BlobStore`. Manifests are parsed only (never executed): a manifest
with a computed expression must leave a sentinel file untouched. Stdlib unittest; no network.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.update import inventory as inv

REV = "a" * 40
CREATED = "2026-01-01T00:00:00Z"
COMMUNITY = "odoo-16.0"
ENTERPRISE = "enterprise-16.0"


def manifest(name, depends=(), **extra):
    fields = {"name": name, "depends": list(depends), "version": "1.0"}
    fields.update(extra)
    return repr(fields) + "\n"


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "store")
        self._count = 0

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self, source_id, files):
        """Write *files* ({relpath: text|bytes}) into a fresh tree and snapshot it through the real helpers."""
        self._count += 1
        root = self.base / f"tree{self._count}"
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        root.mkdir(parents=True, exist_ok=True)
        return build_snapshot(root, source_id, REV, self.store, created_at=CREATED)

    def part(self, source_id, confidentiality, files):
        return inv.build_part(self.snapshot(source_id, files), self.store, source_id=source_id,
                              confidentiality=confidentiality)

    def community_files(self):
        return {
            "addons/base/__manifest__.py": manifest("base"),
            "addons/account/__manifest__.py": manifest("account", ["base"]),
            "addons/sale/__manifest__.py": manifest("sale", ["base", "account"]),
            "odoo/addons/web/__manifest__.py": manifest("web", ["base"]),
            "addons/dupe_mod/__manifest__.py": manifest("dupe_mod", ["base"]),
        }

    def enterprise_files(self):
        return {
            "account_accountant/__manifest__.py": manifest("account_accountant", ["account"]),
            "dupe_mod/__manifest__.py": manifest("dupe_mod_ent", ["account"]),
        }

    def unified(self):
        parts = [self.part(COMMUNITY, "public", self.community_files()),
                 self.part(ENTERPRISE, "enterprise", self.enterprise_files())]
        return inv.merge(parts)


class BuildPartTests(Fixture):
    def test_community_layouts_are_recognised(self):
        part = self.part(COMMUNITY, "public", self.community_files())
        self.assertEqual(sorted(part["modules"]), ["account", "base", "dupe_mod", "sale", "web"])
        self.assertEqual(part["modules"]["sale"]["depends"], ["account", "base"])
        self.assertEqual(part["parse_errors"], [])
        self.assertEqual(part["skipped"], 0)

    def test_enterprise_root_layout_is_recognised(self):
        part = self.part(ENTERPRISE, "enterprise", self.enterprise_files())
        self.assertIn("account_accountant", part["modules"])
        self.assertEqual(part["modules"]["account_accountant"]["depends"], ["account"])

    def test_flags_and_defaults(self):
        part = self.part(COMMUNITY, "public", {
            "addons/a/__manifest__.py": "{'depends': ['base', 'base', 'web']}\n",
            "addons/b/__manifest__.py": "{'installable': False, 'auto_install': ['base']}\n",
            "addons/c/__manifest__.py": "{'auto_install': []}\n",
        })
        self.assertEqual(part["modules"]["a"]["depends"], ["base", "web"])
        self.assertTrue(part["modules"]["a"]["installable"])
        self.assertFalse(part["modules"]["a"]["auto_install"])
        self.assertFalse(part["modules"]["b"]["installable"])
        self.assertTrue(part["modules"]["b"]["auto_install"])
        self.assertFalse(part["modules"]["c"]["auto_install"])
        self.assertRegex(part["modules"]["a"]["manifest_digest"], r"^[0-9a-f]{64}$")

    def test_computed_expression_is_not_executed(self):
        sentinel = self.base / "SENTINEL_EXECUTED.txt"
        payload = f"__import__('pathlib').Path({str(sentinel)!r}).write_text('ran')"
        part = self.part(COMMUNITY, "public", {
            "addons/evil/__manifest__.py": "{'name': 'evil', 'depends': ['base'], 'x': " + payload + "}\n",
            "addons/comp/__manifest__.py": "{'depends': [m for m in ['base']]}\n",
            "addons/stmt/__manifest__.py": "x = 1\n",
            "addons/broken/__manifest__.py": "{'depends': [\n",
        })
        self.assertFalse(sentinel.exists(), "manifest expression was executed")
        self.assertEqual(part["modules"]["evil"]["parse_error"], "NOT_LITERAL")
        self.assertEqual(part["modules"]["evil"]["depends"], [])
        self.assertEqual(part["modules"]["comp"]["parse_error"], "NOT_LITERAL")
        self.assertEqual(part["modules"]["stmt"]["parse_error"], "NOT_A_DICT_LITERAL")
        self.assertEqual(part["modules"]["broken"]["parse_error"], "SYNTAX")
        self.assertEqual(part["parse_errors"], ["broken", "comp", "evil", "stmt"])

    def test_oversize_manifest_is_a_parse_error(self):
        big = "{'name': 'big', 'depends': [], 'pad': '" + "x" * (inv.MAX_MANIFEST_BYTES + 10) + "'}\n"
        part = self.part(COMMUNITY, "public", {"addons/big/__manifest__.py": big})
        self.assertEqual(part["modules"]["big"]["parse_error"], "TOO_LARGE")
        self.assertEqual(part["modules"]["big"]["depends"], [])

    def test_bad_module_names_are_skipped_and_counted(self):
        part = self.part(COMMUNITY, "public", {
            "addons/Bad-Name/__manifest__.py": manifest("x"),
            "addons/" + "a" * 65 + "/__manifest__.py": manifest("y"),
            "__manifest__.py": manifest("root"),
            "addons/ok/__manifest__.py": manifest("ok"),
        })
        self.assertEqual(part["skipped"], 3)
        self.assertEqual(sorted(part["modules"]), ["ok"])

    def test_nested_manifests_create_no_phantom_module(self):
        part = self.part(COMMUNITY, "public", {
            "addons/x/__manifest__.py": manifest("x"),
            "addons/x/static/__manifest__.py": manifest("static"),
            "addons/a/b/c/__manifest__.py": manifest("c"),
            "odoo/x/addons/z/__manifest__.py": manifest("z"),
            "tests/fixtures/y/__manifest__.py": manifest("y"),
            "addons/x/tests/data/__manifest__.py": manifest("data"),
        })
        self.assertEqual(sorted(part["modules"]), ["x"])
        self.assertEqual(part["skipped_nested"], 5)
        self.assertEqual(part["skipped"], 0)
        self.assertEqual(part["parse_errors"], [])

    def test_nested_same_name_does_not_conflict_with_module_root(self):
        part = self.part(COMMUNITY, "public", {
            "addons/x/__manifest__.py": manifest("x"),
            "addons/x/static/x/__manifest__.py": manifest("x", ["base"]),
        })
        self.assertEqual(part["modules"]["x"]["depends"], [])
        self.assertNotIn("parse_error", part["modules"]["x"])
        self.assertEqual(part["parse_errors"], [])
        self.assertEqual(part["skipped_nested"], 1)

    def test_root_level_addons_and_odoo_dirs_are_modules_only_by_root_rule(self):
        part = self.part(ENTERPRISE, "enterprise", {
            "addons/__manifest__.py": manifest("addons"),
            "odoo/__manifest__.py": manifest("odoo", ["addons"]),
        })
        self.assertEqual(sorted(part["modules"]), ["addons", "odoo"])
        self.assertEqual(part["modules"]["odoo"]["depends"], ["addons"])
        self.assertEqual(part["skipped_nested"], 0)

    def test_root_and_addons_layouts_still_recognised(self):
        part = self.part(COMMUNITY, "public", {
            "addons/a1/__manifest__.py": manifest("a1"),
            "odoo/addons/a2/__manifest__.py": manifest("a2"),
            "a3/__manifest__.py": manifest("a3"),
        })
        self.assertEqual(sorted(part["modules"]), ["a1", "a2", "a3"])
        self.assertEqual(part["skipped_nested"], 0)

    def test_wrong_types_are_parse_errors(self):
        part = self.part(COMMUNITY, "public", {
            "addons/s/__manifest__.py": "{'depends': 'base'}\n",
            "addons/t/__manifest__.py": "{'depends': ['Base']}\n",
            "addons/u/__manifest__.py": "{'installable': 'yes'}\n",
            "addons/v/__manifest__.py": "{'auto_install': [1]}\n",
            "addons/w/__manifest__.py": "{'depends': ['base'], 'depends': ['web']}\n",
        })
        self.assertEqual(part["modules"]["s"]["parse_error"], "BAD_DEPENDS")
        self.assertEqual(part["modules"]["t"]["parse_error"], "BAD_DEPENDS")
        self.assertEqual(part["modules"]["u"]["parse_error"], "BAD_FLAG")
        self.assertEqual(part["modules"]["v"]["parse_error"], "BAD_FLAG")
        self.assertEqual(part["modules"]["w"]["parse_error"], "DUPLICATE_KEY")

    def test_duplicate_module_name_inside_one_source_is_an_error(self):
        part = self.part(COMMUNITY, "public", {
            "addons/x/__manifest__.py": manifest("x"),
            "odoo/addons/x/__manifest__.py": manifest("x", ["base"]),
        })
        self.assertEqual(part["modules"]["x"]["parse_error"], "DUPLICATE_IN_SOURCE")
        self.assertEqual(part["parse_errors"], ["x"])

    def test_enterprise_part_has_no_paths_or_content(self):
        marker = "ENTERPRISE-MARKER-TEXT-7731"
        part = self.part(ENTERPRISE, "enterprise", {
            "sec_mod/__manifest__.py": manifest("sec_mod", ["account"], summary=marker),
            "sec_mod/models/thing.py": "# " + marker + "\n",
        })
        serialised = json.dumps(part, sort_keys=True)
        self.assertNotIn(marker, serialised)
        self.assertNotIn("__manifest__", serialised)
        self.assertNotIn("sec_mod/", serialised)
        self.assertNotIn("models", serialised)
        self.assertEqual(set(part["modules"]["sec_mod"]),
                         {"depends", "installable", "auto_install", "manifest_digest", "path_digest"})

    def test_snapshot_source_mismatch_is_refused(self):
        snap = self.snapshot("other-source", self.community_files())
        with self.assertRaises(inv.InventoryError):
            inv.build_part(snap, self.store, source_id=COMMUNITY, confidentiality="public")
        with self.assertRaises(inv.InventoryError):
            inv.build_part(snap, self.store, source_id="other-source", confidentiality="internal")


class MergeTests(Fixture):
    def test_conflict_is_recorded_and_not_resolved(self):
        merged = self.unified()
        self.assertEqual(merged["conflicts"], [{"module": "dupe_mod", "sources": [ENTERPRISE, COMMUNITY]}])
        self.assertNotIn("dupe_mod", merged["modules"])
        self.assertEqual(inv.verify_inventory(merged), [])

    def test_module_record_shape_and_sources(self):
        merged = self.unified()
        self.assertEqual(merged["schema"], "odooflux.inventory/1")
        self.assertEqual(merged["sources"], [{"source_id": ENTERPRISE, "confidentiality": "enterprise"},
                                             {"source_id": COMMUNITY, "confidentiality": "public"}])
        self.assertEqual(merged["modules"]["account_accountant"], {
            "source_id": ENTERPRISE, "confidentiality": "enterprise", "depends": ["account"],
            "installable": True, "auto_install": False,
            "manifest_digest": merged["modules"]["account_accountant"]["manifest_digest"],
        })
        self.assertNotIn("path_digest", merged["modules"]["sale"])

    def test_merge_is_order_independent(self):
        a = self.part(COMMUNITY, "public", self.community_files())
        b = self.part(ENTERPRISE, "enterprise", self.enterprise_files())
        self.assertEqual(inv.merge([a, b]), inv.merge([b, a]))
        self.assertEqual(inv.merge([a, b])["digest"], inv.merge([b, a])["digest"])

    def test_digest_is_stable_and_sensitive(self):
        first = self.unified()
        again = inv.merge([self.part(COMMUNITY, "public", self.community_files()),
                           self.part(ENTERPRISE, "enterprise", self.enterprise_files())])
        self.assertEqual(first["digest"], again["digest"])
        changed_files = self.community_files()
        changed_files["addons/sale/__manifest__.py"] = manifest("sale", ["base"])
        changed = inv.merge([self.part(COMMUNITY, "public", changed_files),
                             self.part(ENTERPRISE, "enterprise", self.enterprise_files())])
        self.assertNotEqual(first["digest"], changed["digest"])
        self.assertEqual(first["digest"], digest_obj({k: v for k, v in first.items() if k != "digest"}))

    def test_parse_error_modules_go_to_unparsed(self):
        broken = self.part(ENTERPRISE, "enterprise", {"ent_x/__manifest__.py": "{'depends': base}\n"})
        merged = inv.merge([self.part(COMMUNITY, "public", self.community_files()), broken])
        self.assertEqual(merged["unparsed"], [{"module": "ent_x", "source_id": ENTERPRISE, "code": "NOT_LITERAL"}])
        self.assertNotIn("ent_x", merged["modules"])
        self.assertEqual(inv.verify_inventory(merged), [])

    def test_duplicate_source_ids_are_refused(self):
        a = self.part(COMMUNITY, "public", self.community_files())
        with self.assertRaises(inv.InventoryError):
            inv.merge([a, a])


class VerifyTests(Fixture):
    def recomputed(self, doc):
        doc["digest"] = digest_obj({k: v for k, v in doc.items() if k != "digest"})
        return doc

    def test_clean_inventory_verifies(self):
        self.assertEqual(inv.verify_inventory(self.unified()), [])

    def test_tamper_without_recompute_is_detected(self):
        doc = self.unified()
        doc["modules"]["sale"]["depends"] = ["base"]
        codes = [f["code"] for f in inv.verify_inventory(doc)]
        self.assertIn("DIGEST_MISMATCH", codes)

    def test_undeclared_source_is_detected_even_when_recomputed(self):
        doc = self.unified()
        doc["modules"]["sale"]["source_id"] = "ghost-source"
        doc = self.recomputed(doc)
        codes = [f["code"] for f in inv.verify_inventory(doc)]
        self.assertIn("UNKNOWN_SOURCE", codes)

    def test_enterprise_record_with_extra_key_is_rejected(self):
        doc = self.unified()
        doc["modules"]["account_accountant"]["path"] = "account_accountant/__manifest__.py"
        doc = self.recomputed(doc)
        self.assertTrue(any(f["code"] == "SCHEMA" for f in inv.verify_inventory(doc)))

    def test_confidentiality_must_match_declared_source(self):
        doc = self.unified()
        doc["modules"]["account_accountant"]["confidentiality"] = "public"
        doc = self.recomputed(doc)
        self.assertTrue(any(f["code"] == "CONFIDENTIALITY_MISMATCH" for f in inv.verify_inventory(doc)))

    def test_conflicted_module_must_not_be_resolved(self):
        doc = self.unified()
        doc["modules"]["dupe_mod"] = copy.deepcopy(doc["modules"]["sale"])
        doc["modules"]["dupe_mod"]["depends"] = []
        doc = self.recomputed(doc)
        self.assertTrue(any(f["code"] == "CONFLICT_INCONSISTENT" for f in inv.verify_inventory(doc)))

    def test_wrong_schema_marker_and_non_mapping(self):
        doc = self.unified()
        doc["schema"] = "odooflux.inventory/2"
        self.assertTrue(any(f["code"] == "SCHEMA" for f in inv.verify_inventory(doc)))
        self.assertEqual(inv.verify_inventory([])[0]["code"], "NOT_A_MAPPING")


class ResolveTests(Fixture):
    def inventory(self):
        return self.unified()

    def test_custom_to_community_only(self):
        result = inv.resolve(self.inventory(), {"kbi_sales": ["sale"]})
        entry = result["resolved"]["kbi_sales"]
        self.assertEqual(entry["direct"], ["sale"])
        self.assertEqual(entry["transitive"], ["account", "base"])
        self.assertEqual(entry["by_source"], {COMMUNITY: ["account", "base", "sale"]})
        self.assertEqual(result["enterprise_dependent"], [])
        self.assertEqual(result["unresolved"], {})

    def test_custom_to_enterprise_to_community(self):
        result = inv.resolve(self.inventory(), {"kbi_fin": ["account_accountant"]})
        entry = result["resolved"]["kbi_fin"]
        self.assertEqual(entry["transitive"], ["account", "base"])
        self.assertEqual(entry["by_source"], {COMMUNITY: ["account", "base"], ENTERPRISE: ["account_accountant"]})
        self.assertEqual(result["enterprise_dependent"], ["kbi_fin"])

    def test_custom_chain_reaches_enterprise(self):
        result = inv.resolve(self.inventory(), {"kbi_top": ["kbi_fin"], "kbi_fin": ["account_accountant"]})
        self.assertEqual(result["resolved"]["kbi_top"]["custom"], ["kbi_fin"])
        self.assertEqual(result["enterprise_dependent"], ["kbi_fin", "kbi_top"])

    def test_unknown_dependency_is_unresolved_not_assumed(self):
        result = inv.resolve(self.inventory(), {"kbi_x": ["ghost_mod", "sale"], "kbi_y": ["Bad Name"]})
        self.assertEqual(result["unresolved"], {"kbi_x": ["ghost_mod"], "kbi_y": ["Bad Name"]})
        self.assertNotIn("ghost_mod", result["resolved"]["kbi_x"]["by_source"].get(COMMUNITY, []))

    def test_cycle_among_custom_modules_terminates_and_is_reported(self):
        result = inv.resolve(self.inventory(), {"cyc_a": ["cyc_b"], "cyc_b": ["cyc_a", "base"]})
        self.assertEqual(result["cycles"], [["cyc_a", "cyc_b"]])
        self.assertEqual(result["resolved"]["cyc_a"]["custom"], ["cyc_b"])

    def test_self_loop_is_a_cycle(self):
        result = inv.resolve(self.inventory(), {"self_m": ["self_m"]})
        self.assertEqual(result["cycles"], [["self_m"]])

    def test_conflicted_dependency_is_reported(self):
        result = inv.resolve(self.inventory(), {"kbi_c": ["dupe_mod"]})
        self.assertEqual(result["conflicted"], {"kbi_c": ["dupe_mod"]})
        self.assertEqual(result["enterprise_dependent"], ["kbi_c"])
        self.assertEqual(result["unresolved"], {})

    def test_resolution_is_deterministic(self):
        custom = {"b_mod": ["sale", "account_accountant"], "a_mod": ["web"]}
        self.assertEqual(inv.resolve(self.inventory(), custom), inv.resolve(self.inventory(), custom))

    def test_tampered_inventory_is_refused(self):
        doc = self.inventory()
        doc["modules"]["sale"]["depends"] = []
        with self.assertRaises(inv.InventoryError):
            inv.resolve(doc, {"kbi": ["sale"]})


class CarryForwardTests(Fixture):
    def test_pass_when_enterprise_dependencies_still_exist(self):
        old = self.unified()
        new = inv.merge([self.part(COMMUNITY, "public", self.community_files()),
                         self.part(ENTERPRISE, "enterprise", self.enterprise_files())])
        self.assertEqual(inv.carry_forward_compat(old, new), [])

    def test_fail_when_new_community_drops_a_dependency(self):
        old = self.unified()
        files = self.community_files()
        del files["addons/account/__manifest__.py"]
        files["addons/sale/__manifest__.py"] = manifest("sale", ["base"])
        new = inv.merge([self.part(COMMUNITY, "public", files), self.part(ENTERPRISE, "enterprise", self.enterprise_files())])
        self.assertEqual(inv.carry_forward_compat(old, new),
                         [{"module": "account_accountant", "missing": ["account"]}])

    def test_only_enterprise_modules_are_checked_by_default(self):
        old = self.unified()
        files = {"addons/base/__manifest__.py": manifest("base")}
        new = inv.merge([self.part(COMMUNITY, "public", files)])
        default = inv.carry_forward_compat(old, new)
        self.assertEqual([f["module"] for f in default], ["account_accountant"])
        everything = inv.carry_forward_compat(old, new, enterprise_only=False)
        self.assertIn("sale", [f["module"] for f in everything])
        self.assertNotIn("sale", [f["module"] for f in default])


if __name__ == "__main__":
    unittest.main()
