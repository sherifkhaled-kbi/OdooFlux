"""TST-007-021 (FR-020, US5 scenario 3): the kill switch blocks all external transmission; local is unaffected."""

import unittest

from tests.unit.ai import _helpers as h
from tests.unit.ai._gateway_support import (
    GOOD_JSON, RaisingTransport, RecordingTransport, config_for, make_request, ok_openai)
from odooflux.ai.gateway import build_gateway
from odooflux.ai.providers.catalog import load_catalog

CATALOG = load_catalog(extra=[h.test_catalog()])
GRANTS = {"alpha": ["source_python", "evidence_excerpt"], "beta": ["source_python"]}
ENV = {"ALPHA_KEY": "k-alpha-1234567", "BETA_KEY": "k-beta-1234567"}


class KillSwitchTests(unittest.TestCase):
    def test_external_is_blocked_with_zero_transport_opens(self):
        transport = RaisingTransport()
        gw = build_gateway(config_for("alpha", "m-one", grants=GRANTS, kill=True), CATALOG, environ=ENV,
                           transport_for=lambda name: transport)
        resp = gw.complete(make_request("alpha", "m-one"))
        self.assertEqual((resp.stop_reason, resp.error_kind), ("error", "transmission_disabled"))
        self.assertEqual(transport.calls, [])

    def test_every_external_adapter_is_blocked(self):
        for provider, model in (("alpha", "m-one"), ("beta", "b-one")):
            transport = RaisingTransport()
            gw = build_gateway(config_for(provider, model, grants=GRANTS, kill=True), CATALOG, environ=ENV,
                               transport_for=lambda name, t=transport: t)
            self.assertEqual(gw.complete(make_request(provider, model)).error_kind, "transmission_disabled")
            self.assertEqual(transport.calls, [])

    def test_local_provider_is_unaffected(self):
        transport = RecordingTransport([ok_openai(GOOD_JSON)])
        gw = build_gateway(config_for("loc", "l-one", kill=True), CATALOG, environ={},
                           transport_for=lambda name: transport)
        resp = gw.complete(make_request("loc", "l-one"))
        self.assertEqual(resp.stop_reason, "complete")
        self.assertEqual(len(transport.calls), 1)

    def test_kill_switch_beats_a_valid_authorization(self):
        gw = build_gateway(config_for("alpha", "m-one", grants=GRANTS, kill=True), CATALOG, environ=ENV,
                           transport_for=lambda name: RaisingTransport())
        self.assertEqual(gw.complete(make_request("alpha", "m-one")).error_kind, "transmission_disabled")

    def test_switch_off_sends(self):
        transport = RecordingTransport([ok_openai(GOOD_JSON)])
        gw = build_gateway(config_for("alpha", "m-one", grants=GRANTS), CATALOG, environ=ENV,
                           transport_for=lambda name: transport)
        self.assertEqual(gw.complete(make_request("alpha", "m-one", categories=("source_python",))).stop_reason,
                         "complete")


if __name__ == "__main__":
    unittest.main()
