"""TST-003-010 (REQ-DEP-002): topological order, name ties, cycles, external dependencies."""

import unittest

from odooflux.dependencies.graph import topo_order

from ._setup import SRC  # noqa: F401


class DependencyGraphTests(unittest.TestCase):
    def test_dependencies_come_first_with_name_ties(self):
        order, cycles, blocked = topo_order({"sale": ["base"], "base": [], "account": ["base"],
                                             "crm": ["sale"]})
        self.assertEqual(order, ["base", "account", "sale", "crm"])
        self.assertEqual(cycles, [])
        self.assertEqual(blocked, [])

    def test_cycle_is_reported_with_members_and_blocked(self):
        order, cycles, blocked = topo_order({"a": ["b"], "b": ["a"], "c": []})
        self.assertEqual(order, ["c"])
        self.assertEqual(cycles, [["a", "b"]])
        self.assertEqual(blocked, ["a", "b"])

    def test_external_dependencies_are_ignored(self):
        order, cycles, _ = topo_order({"a": ["web", "missing_module"]})
        self.assertEqual(order, ["a"])
        self.assertEqual(cycles, [])

    def test_self_dependency_is_a_cycle(self):
        _, cycles, _ = topo_order({"a": ["a"]})
        self.assertEqual(cycles, [["a"]])


if __name__ == "__main__":
    unittest.main()
