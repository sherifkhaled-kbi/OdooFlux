"""TST-007-003 (REQ-AI-001, SC-001): no AI flags -> zero provider/transport opens on the golden fixtures."""

import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from tests.integration.helpers import make_module, new_tmp, run_cli_main, start_run


class _Guard:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        raise AssertionError("a transport was opened while AI is disabled")


class AIDisabledTests(unittest.TestCase):
    def _guarded(self):
        guard = _Guard()
        stack = mock.patch.multiple(urllib.request, urlopen=guard)
        sock = mock.patch.object(socket.socket, "connect", guard)
        return guard, stack, sock

    def test_cli_without_ai_flags_opens_nothing(self):
        guard, a, b = self._guarded()
        with a, b:
            for flags in ([], ["--fix"], ["--fix", "--dry-run"]):
                tmp = new_tmp()
                module = make_module(tmp, "kbi_demo")
                code, _out = run_cli_main(["--module", module, "--from-version", "14", "--to-version", "19",
                                           "--state-dir", tmp / "state", *flags])
                self.assertIn(code, (0, 1, 3, 4))
        self.assertEqual(guard.calls, [])

    def test_pipeline_in_fix_mode_has_zero_ai_requests(self):
        guard, a, b = self._guarded()
        with a, b:
            tmp = new_tmp()
            module = make_module(tmp, "kbi_demo")
            _run_id, state = start_run(tmp / "state", [module], mode="fix")
        self.assertEqual(guard.calls, [])
        from odooflux.core.orchestrator.run import reports_from_state
        from odooflux.reporting.model.model import build_report
        ai = build_report(state, reports_from_state(state), run_log_path="")["ai_usage"]
        self.assertEqual((ai["enabled"], ai["providers"], sum(p["requests"] for p in ai["providers"])),
                         (False, [], 0))  # report ai_usage: nothing used, zero requests
        self.assertFalse(state["options"].get("ai"))

    def test_provider_and_gateway_never_constructed_when_disabled(self):
        import odooflux.ai.gateway as gw
        with mock.patch.object(gw.Gateway, "__init__", side_effect=AssertionError("gateway built")):
            tmp = new_tmp()
            module = make_module(tmp, "kbi_demo")
            start_run(tmp / "state", [module], mode="fix")


if __name__ == "__main__":
    unittest.main()
