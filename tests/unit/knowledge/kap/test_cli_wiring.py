"""TST-011-016 (REQ-KAP-005, REQ-KAP-001): CLI wiring for the knowledge acquisition groups.

Contract: cli-surface (groups live in `cli/kap_*.py`, each with `register(subparsers)`; existing `validate`, `refresh`,
`matrix` unchanged). Groups are injected as in-memory modules so no `cli/kap_*.py` file is created by the test.
"""

import argparse
import sys
import types
import unittest
from unittest import mock

from odooflux.cli import knowledge as knowledge_cli
from odooflux.cli.kap_common import EXIT_PACKAGE_REJECTED, EXIT_INTEGRITY, EXIT_SOURCE_UNAVAILABLE, register_all
from odooflux.cli.exit_codes import USAGE

FAKE = "odooflux.cli.kap_fakegroup"


def _subparsers_action(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError("parser has no subcommands")


def _fake_module(ran: list):
    module = types.ModuleType(FAKE)

    def register(sub):
        group = sub.add_parser("fakegroup", help="fake group for wiring tests")
        group.add_argument("--flag", action="store_true")
        group.set_defaults(kap_handler=lambda args: ran.append(args.flag) or 0)

    module.register = register
    return module


class TestCliWiring(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get(FAKE)

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop(FAKE, None)
        else:
            sys.modules[FAKE] = self._saved

    def test_existing_commands_unchanged(self):
        parser = knowledge_cli.build_parser()
        choices = _subparsers_action(parser).choices
        for name in ("validate", "refresh", "matrix"):
            self.assertIn(name, choices)
            self.assertNotIn("kap_handler", choices[name]._defaults)
        validate_flags = {a.dest for a in choices["validate"]._actions}
        matrix_flags = {a.dest for a in choices["matrix"]._actions}
        self.assertIn("path", validate_flags)
        self.assertTrue({"check", "output", "path"} <= matrix_flags)

    def test_help_lists_groups_when_present(self):
        sys.modules[FAKE] = _fake_module([])
        parser = argparse.ArgumentParser(prog="odooflux knowledge")
        sub = parser.add_subparsers(dest="action", required=True)
        registered = register_all(sub, modules=[_fake_module([])])
        self.assertEqual(registered, ["kap_fakegroup"])
        self.assertIn("fakegroup", parser.format_help())
        base = knowledge_cli.build_parser().format_help()
        for name in ("validate", "refresh", "matrix"):
            self.assertIn(name, base)

    def test_no_groups_registers_nothing(self):
        parser = argparse.ArgumentParser(prog="odooflux knowledge")
        sub = parser.add_subparsers(dest="action", required=True)
        self.assertEqual(register_all(sub, modules=[]), [])

    def test_group_dispatch_runs_registered_handler(self):
        ran = []
        sys.modules[FAKE] = _fake_module(ran)
        with mock.patch.object(knowledge_cli, "register_all",
                               side_effect=lambda sub: register_all(sub, modules=[_fake_module(ran)])):
            self.assertEqual(knowledge_cli.main(["fakegroup", "--flag"]), 0)
        self.assertEqual(ran, [True])

    def test_exit_codes_for_kap_groups(self):
        self.assertEqual(USAGE, 2)
        self.assertEqual(EXIT_PACKAGE_REJECTED, 3)
        self.assertEqual(EXIT_SOURCE_UNAVAILABLE, 4)
        self.assertEqual(EXIT_INTEGRITY, 5)


if __name__ == "__main__":
    unittest.main()
