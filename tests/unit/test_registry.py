"""TST-003-005 (REQ-ARC-006): duplicate ids, sorted listing, and contract-version rejection."""

import unittest
from dataclasses import dataclass

from odooflux.core.contracts import (
    CONTRACT_VERSION, DuplicateRegistrationError, PluginContractError)
from odooflux.core.contracts.plugins import Registry, Registries

from ._setup import SRC  # noqa: F401


@dataclass
class Entry:
    key: str
    contract_version: int = CONTRACT_VERSION


class RegistryTests(unittest.TestCase):
    def test_duplicate_id_is_rejected(self):
        reg = Registry("rules")
        reg.register(Entry("a"))
        with self.assertRaises(DuplicateRegistrationError):
            reg.register(Entry("a"))

    def test_all_is_sorted_by_key(self):
        reg = Registry("rules")
        for key in ("zeta", "alpha", "mid"):
            reg.register(Entry(key))
        self.assertEqual([e.key for e in reg.all()], ["alpha", "mid", "zeta"])

    def test_contract_mismatch_names_both_versions(self):
        reg = Registry("rules")
        with self.assertRaises(PluginContractError) as ctx:
            reg.register(Entry("bad", contract_version=99), plugin="acme.rules:RULE")
        message = str(ctx.exception)
        self.assertIn("acme.rules:RULE", message)
        self.assertIn("99", message)
        self.assertIn(str(CONTRACT_VERSION), message)

    def test_seven_registries_exist(self):
        regs = Registries()
        for kind in ("versions", "rules", "parsers", "validators", "runtimes", "ai_providers", "renderers"):
            self.assertIsInstance(getattr(regs, kind), Registry)


if __name__ == "__main__":
    unittest.main()
