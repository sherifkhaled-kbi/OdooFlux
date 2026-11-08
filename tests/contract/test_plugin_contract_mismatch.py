"""TST-003-025 (REQ-ARC-006): a wrong contract version is rejected with a clear message; the run continues."""

import unittest

from odooflux.builtins import build_context
from odooflux.cli.plugins import load_plugins
from odooflux.core.contracts import CONTRACT_VERSION, PluginContractError

from ..integration.helpers import make_module, new_tmp, run_cli_main

BAD = "contract.samples.bad_plugins:PLUGIN"


class ContractMismatchTests(unittest.TestCase):
    def test_every_kind_rejects_version_99_naming_both_versions(self):
        ctx = build_context()
        failures = load_plugins([BAD], ctx.registries)
        self.assertEqual(len(failures), 1)
        spec, message = failures[0]
        self.assertEqual(spec, BAD)
        self.assertIn("99", message)
        self.assertIn(str(CONTRACT_VERSION), message)

    def test_run_continues_without_the_bad_plugin(self):
        root = new_tmp()
        module = make_module(root, "clean_mod")
        code, out = run_cli_main(["--module", module, "--from-version", "14", "--no-color", "--plugin", BAD,
                                  "--state-dir", root / "s"])
        self.assertIn("not loaded", out)
        self.assertIn("clean_mod", out)  # the module still ran


if __name__ == "__main__":
    unittest.main()
