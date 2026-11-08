"""TST-011-060 (REQ-KAP-017, REQ-KAP-002): the AI proposer runs only with an explicit evidence_excerpt grant, sends a
minimised request, accepts only a closed JSON reply, and can never confirm a candidate, create evidence, set a
maturity, set detectors_verified or move a ledger change.

The gateway is the real `odooflux.ai` gateway over the packaged `fake` provider (FakeProvider replays a scripted
reply). Nothing opens a socket; no live provider is called. The proposer itself imports nothing from `odooflux.ai`:
the gateway and authorizer are passed in as parameters, here built by the test (tests may import the AI package).
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from odooflux.ai.authorization import Authorizer, parse_grants
from odooflux.ai.gateway import GatewayConfig, build_gateway
from odooflux.ai.providers.catalog import load_catalog
from odooflux.builtins import build_registries
from odooflux.knowledge.candidates import ai_proposer as ap
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.candidates.templates import load_templates
from odooflux.knowledge.ledger.ledger import Ledger

KNOWN = build_registries().extract_toolkit.detectors
CLOCK = lambda: "2026-11-08T00:00:00Z"  # noqa: E731
SOURCE = {"source_id": "odoo-community-17.0", "official": True, "url": "https://github.com/odoo/odoo/tree/" + "a" * 40,
          "repository": "odoo/odoo", "revision": "a" * 40, "branch": "17.0"}
GRANT = "fake=evidence_excerpt"
CONFIG = {"enabled": True, "provider": "fake", "model": "fake-model", "kill_switch": False,
          "budget_job_tokens": 100000}


def _snap(sid_hex, digest_hex):
    return {"snapshot_id": "ss-" + sid_hex, "snapshot_digest": digest_hex * 64}


def _draft(subject, kind, cls):
    return {"domain": "python_orm", "kind": kind, "subject_key": subject, "class": cls, "detail": {},
            "locations": [{"snapshot_id": "ss-0123456789ab", "path": "addons/sale/models/order.py",
                           "line": 12, "sha256": "cd" * 32}], "proposed_by": "DETERMINISTIC"}


class _Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.tree = self.base / "tree"
        self.tree.mkdir()
        drafts = [_draft("sale.demo.order.compute", "method", "REMOVED"),
                  _draft("sale.demo.order.priority", "field", "REMOVED")]
        self.ledger = Ledger.create("17-18", _snap("111111111111", "1"), _snap("222222222222", "2"), drafts,
                                    clock=CLOCK)
        self.result = gen.generate(self.ledger, tree_root=self.tree, source=SOURCE, checked_on="2026-11-08",
                                   known_detectors=KNOWN)
        self.candidates = copy.deepcopy(self.result["candidates"])
        self.evidence = copy.deepcopy(self.result["evidence"])
        self.changes = {r["change_id"]: r for r in self.ledger.records()}
        self.template_ids = [t["template_id"] for t in load_templates(known_detectors=KNOWN)]

    def tearDown(self):
        self._tmp.cleanup()

    def _gateway(self, entries, *, grants=(GRANT,)):
        script = self.base / "fake_script.json"
        script.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        cfg = GatewayConfig(provider="fake", model="fake-model", grants=parse_grants(list(grants)),
                            fake_script=str(script))
        return build_gateway(cfg, load_catalog(), environ={})

    def _reply(self, body):
        return [{"response": {"raw_text": json.dumps(body) if not isinstance(body, str) else body}}]

    def _propose(self, gateway, *, config=None, grants=(GRANT,)):
        return ap.propose(self.candidates, evidence=self.evidence, changes=self.changes, gateway=gateway,
                          authorizer=Authorizer(parse_grants(list(grants))), config=dict(config or CONFIG),
                          template_ids=self.template_ids)


class AiOffTests(_Fixture):
    def test_ai_off_identical_output(self):
        before = copy.deepcopy((self.candidates, self.evidence, self.ledger.to_dict()))
        gw = self._gateway(self._reply({"rationale": "x", "template_hint": ""}))
        out = self._propose(gw, config={**CONFIG, "enabled": False})
        self.assertEqual(out["status"], "off")
        self.assertEqual(out["proposals"], [])
        self.assertEqual((self.candidates, self.evidence, self.ledger.to_dict()), before)
        self.assertEqual(gw.provider.requests, [])

    def test_zero_gateway_calls_when_off(self):
        class Boom:
            def complete(self, req):
                raise AssertionError("the gateway was called while AI is off")
        out = self._propose(Boom(), config={**CONFIG, "enabled": False})
        self.assertEqual(out["status"], "off")
        self.assertEqual(out["calls"], [])


class AiGuardTests(_Fixture):
    def test_ai_no_grant_skips(self):
        gw = self._gateway(self._reply({"rationale": "x", "template_hint": ""}))
        for grants in ((), ("fake=source_python",), ("other=evidence_excerpt",)):
            out = self._propose(gw, grants=grants)
            self.assertEqual(out["status"], "denied", grants)
            self.assertEqual(out["missing"], ["evidence_excerpt"], grants)
            self.assertEqual(out["proposals"], [])
        self.assertEqual(gw.provider.requests, [], "a denied request must never reach the provider")

    def test_kill_switch(self):
        gw = self._gateway(self._reply({"rationale": "x", "template_hint": ""}))
        out = self._propose(gw, config={**CONFIG, "kill_switch": True})
        self.assertEqual(out["status"], "kill_switch")
        self.assertEqual(out["proposals"], [])
        self.assertEqual(gw.provider.requests, [])

    def test_budget_exhausted_skips_rest(self):
        gw = self._gateway([{"response": {"raw_text": json.dumps({"rationale": "r", "template_hint": ""}),
                                          "usage": {"input": 50, "output": 50}}}])
        out = self._propose(gw, config={**CONFIG, "budget_job_tokens": 100})
        self.assertEqual(len(out["proposals"]), 1)
        self.assertEqual([s["reason"] for s in out["skipped"]], ["budget_exhausted"])


class ReplyTests(_Fixture):
    def test_ai_cannot_confirm_or_create_evidence(self):
        forbidden = {"status": "ACCEPTED", "confirmed": True, "maturity": "FIX_ENABLED", "detectors_verified": True,
                     "disposition": "RULE_CREATED", "evidence": [{"id": "EV-999"}], "fixer_ref": "x.fix"}
        before = copy.deepcopy((self.candidates, self.evidence, self.ledger.to_dict()))
        gw = self._gateway(self._reply({"rationale": "looks removed", "template_hint": "", **forbidden}))
        out = self._propose(gw)
        self.assertEqual(out["proposals"], [])
        self.assertEqual(len(out["discarded"]), len(self.candidates))
        self.assertEqual({d["reason"] for d in out["discarded"]}, {"schema_violation"})
        self.assertEqual((self.candidates, self.evidence, self.ledger.to_dict()), before)

    def test_clean_reply_fills_only_allowed_fields(self):
        gw = self._gateway(self._reply({"rationale": "Removed method; review the callers.", "template_hint": ""}))
        before = copy.deepcopy((self.candidates, self.evidence, self.ledger.to_dict()))
        out = self._propose(gw)
        self.assertEqual(len(out["proposals"]), len(self.candidates))
        for item in out["proposals"]:
            self.assertEqual(item["origin"], "AI_PROPOSED")
            self.assertTrue(item["ai_proposed"])
            self.assertEqual(sorted(item), ["ai_proposed", "candidate_id", "change_id", "origin", "rationale",
                                            "template_hint"])
        self.assertEqual((self.candidates, self.evidence, self.ledger.to_dict()), before)

    def test_unknown_template_hint_discards_reply(self):
        gw = self._gateway(self._reply({"rationale": "x", "template_hint": "no-such-template"}))
        out = self._propose(gw)
        self.assertEqual(out["proposals"], [])
        self.assertEqual({d["reason"] for d in out["discarded"]}, {"schema_violation"})

    def test_truncated_or_non_json_reply_discarded(self):
        gw = self._gateway(self._reply("not json at all"))
        out = self._propose(gw)
        self.assertEqual(out["proposals"], [])
        self.assertEqual({d["reason"] for d in out["discarded"]}, {"not_json"})

    def test_provider_error_is_explicit_no_fallback(self):
        gw = self._gateway([{"response": {"error_kind": "invalid_request"}}])
        out = self._propose(gw)
        self.assertEqual(out["proposals"], [])
        self.assertEqual({d["reason"] for d in out["denied"]}, {"invalid_request"})


class RequestTests(_Fixture):
    def test_request_is_minimised_and_relative(self):
        gw = self._gateway(self._reply({"rationale": "r", "template_hint": ""}))
        self._propose(gw)
        self.assertTrue(gw.provider.requests)
        for req in gw.provider.requests:
            self.assertEqual(tuple(req.data_categories), ("evidence_excerpt",))
            self.assertFalse(Path(req.region["path"]).is_absolute())
            payload = json.loads(req.messages[0]["content"])
            self.assertEqual(sorted(payload), ["allowed_template_ids", "change", "excerpt"])
            self.assertEqual(sorted(payload["change"]), ["class", "domain", "kind", "step", "subject_key"])
            self.assertNotIn("<code>", req.messages[0]["content"])

    def test_proposer_module_has_no_ai_import(self):
        import re
        source = Path(ap.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(import|from)\s+odooflux(\.ai|\s+import\s+ai)", source, re.M))
        self.assertNotIn("importlib", source)


if __name__ == "__main__":
    unittest.main()
