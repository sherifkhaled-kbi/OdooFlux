"""The composition root's `ai_gateway_factory` (feature 011, D-08): lazy, explicit grants only, kill switch, no fallback.

The factory is built from the production configuration path (cli/ai_options.add_ai_arguments + resolve_ai), so the
dict it receives is exactly what `knowledge ai propose` passes. The packaged `fake` provider answers from a script;
the external provider is a catalog entry whose adapter is `fake`, so its gateway checks (kill switch, grants,
credential) run without any transport. Sockets are blocked for every test here.

Note on imports: `odooflux.builtins` imports `odooflux.ai.integration` at module level (the pre-existing escalation
registration), which loads `odooflux.ai.gateway`. The attachment therefore cannot be proven by sys.modules; what is
asserted instead is that building the context never calls build_gateway or builds a provider.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins
from odooflux.ai.providers.fake import FakeProvider
from odooflux.cli import ai_options
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from tests.unit.ai._gateway_support import make_request
from tests.unit.knowledge.kap.test_cli_candidates import CLOCK, DATA_DIRS, SOURCE, _draft, _snap

ENV_KEY = "ODOOFLUX_KAP_TEST_KEY"
ENV_KEY_VALUE = "sk-test-NEVER-PRINTED-0123456789"
FAKE_REPLY = json.dumps({"rationale": "Review the removed method.", "template_hint": ""})
EXT_CATALOG = {
    "schema": "odooflux.ai-catalog/1",
    "providers": {"ext": {"type": "external", "adapter": "fake", "endpoint": "https://ext.example.invalid/v1",
                          "credential_env": ENV_KEY,
                          "models": [{"id": "ext-model", "context_window": 100000, "max_output": 4096,
                                      "structured_output": True}]}},
}


class _NoSocket:
    def __init__(self, *args, **kwargs):
        raise AssertionError("a socket was opened in a test that must not reach the network")


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.script = self.base / "fake_script.json"
        self.script.write_text(json.dumps({"entries": [{"response": {"raw_text": FAKE_REPLY}}]}), encoding="utf-8")
        self.catalog = self.base / "ext_catalog.json"
        self.catalog.write_text(json.dumps(EXT_CATALOG), encoding="utf-8")
        self.env = {"ODOOFLUX_AI_FAKE_SCRIPT": str(self.script), ENV_KEY: ENV_KEY_VALUE}
        env_patch = mock.patch.dict(os.environ, self.env)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        socket_patch = mock.patch.object(socket, "socket", _NoSocket)
        socket_patch.start()
        self.addCleanup(socket_patch.stop)

    def config(self, *argv, environ=None):
        """The production configuration dict: parse the AI flags and resolve them exactly as the command does."""
        parser = argparse.ArgumentParser()
        ai_options.add_ai_arguments(parser)
        args = parser.parse_args(["--ai", "--ai-consent-send-code", "--ai-budget-job-tokens", "1000", *argv])
        cfg, error = ai_options.resolve_ai(args, self.env if environ is None else environ)
        self.assertIsNone(error)
        return cfg.to_dict()

    def fake_cfg(self, *extra):
        return self.config("--ai-provider", "fake", "--ai-model", "fake-model", *extra)

    def ext_cfg(self, *extra, environ=None):
        return self.config("--ai-provider", "ext", "--ai-model", "ext-model", "--ai-catalog", str(self.catalog),
                           *extra, environ=environ)


class ContextAttachmentTests(_Base):
    def test_context_build_neither_builds_a_gateway_nor_a_provider(self):
        with mock.patch("odooflux.ai.gateway.build_gateway") as gw, \
                mock.patch("odooflux.ai.providers.factory.build_provider") as prov:
            registries = builtins.build_registries()
        gw.assert_not_called()
        prov.assert_not_called()
        self.assertIs(registries.ai_gateway_factory, builtins.ai_gateway_factory)

    def test_factory_is_only_called_for_an_ai_run(self):
        registries = builtins.build_registries()
        with mock.patch("odooflux.ai.gateway.build_gateway") as gw:
            self.assertIsNotNone(registries.ai_gateway_factory)
        gw.assert_not_called()


class FactoryTests(_Base):
    def test_fake_provider_gateway_answers_through_fake_provider(self):
        gateway, authorizer = builtins.ai_gateway_factory(
            self.fake_cfg("--ai-authorize", "fake=evidence_excerpt"))
        self.assertIsInstance(gateway.provider, FakeProvider)
        self.assertEqual(gateway.provider_name, "fake")
        resp = gateway.complete(make_request("fake", "fake-model", categories=("evidence_excerpt",)))
        self.assertIsNone(resp.error_kind)
        self.assertIn("Review the removed method.", resp.text)
        self.assertEqual(authorizer.check("fake", "external", ("evidence_excerpt",)), None)

    def test_authorizer_reflects_only_the_granted_categories(self):
        _, authorizer = builtins.ai_gateway_factory(
            self.ext_cfg("--ai-authorize", "ext=evidence_excerpt"))
        self.assertIsNone(authorizer.check("ext", "external", ("evidence_excerpt",)))
        self.assertEqual(authorizer.check("ext", "external", ("source_python",)), "authorization_category_denied")
        self.assertEqual(authorizer.check("ext", "external", ("source_python", "evidence_excerpt")),
                         "authorization_category_denied")
        self.assertEqual(authorizer.check("other", "external", ("evidence_excerpt",)),
                         "authorization_provider_mismatch")

    def test_no_grant_named_means_no_grant(self):
        _, authorizer = builtins.ai_gateway_factory(self.ext_cfg())
        self.assertEqual(authorizer.grants, {})
        self.assertEqual(authorizer.check("ext", "external", ("evidence_excerpt",)), "authorization_missing")

    def test_missing_grant_is_refused_naming_the_category(self):
        gateway, _ = builtins.ai_gateway_factory(self.ext_cfg("--ai-authorize", "ext=source_python"))
        resp = gateway.complete(make_request("ext", "ext-model", categories=("evidence_excerpt",)))
        self.assertEqual(resp.error_kind, "authorization_category_denied")
        self.assertEqual(resp.detail, "authorization:missing=evidence_excerpt")
        self.assertEqual(gateway.provider.requests, [], "a denied request must not reach the provider")

    def test_kill_switch_blocks_external_transmission(self):
        gateway, _ = builtins.ai_gateway_factory(
            self.ext_cfg("--ai-authorize", "ext=evidence_excerpt", "--ai-disable-external"))
        resp = gateway.complete(make_request("ext", "ext-model", categories=("evidence_excerpt",)))
        self.assertEqual(resp.error_kind, "transmission_disabled")
        self.assertEqual(gateway.provider.requests, [])

    def test_kill_switch_from_environment_blocks_external_transmission(self):
        environ = {**self.env, "ODOOFLUX_AI_DISABLE_EXTERNAL": "1"}
        gateway, _ = builtins.ai_gateway_factory(self.ext_cfg("--ai-authorize", "ext=evidence_excerpt",
                                                              environ=environ))
        resp = gateway.complete(make_request("ext", "ext-model", categories=("evidence_excerpt",)))
        self.assertEqual(resp.error_kind, "transmission_disabled")

    def test_credential_is_read_from_the_declared_variable_and_never_echoed(self):
        cfg = self.ext_cfg("--ai-authorize", "ext=evidence_excerpt")
        with mock.patch.dict(os.environ):
            os.environ.pop(ENV_KEY, None)
            gateway, _ = builtins.ai_gateway_factory(cfg)
            resp = gateway.complete(make_request("ext", "ext-model", categories=("evidence_excerpt",)))
        self.assertEqual(resp.error_kind, "auth")
        self.assertEqual(resp.detail, "credential_missing")
        gateway, _ = builtins.ai_gateway_factory(cfg)
        resp = gateway.complete(make_request("ext", "ext-model", categories=("evidence_excerpt",)))
        self.assertIsNone(resp.error_kind)
        self.assertNotIn(ENV_KEY_VALUE, repr(resp))

    def test_forbidden_and_unknown_categories_are_refused(self):
        for grant, code in (("fake=credentials", "forbidden_category"), ("fake=bogus", "unknown_category")):
            with self.subTest(grant=grant):
                with self.assertRaises(ValueError) as ctx:
                    builtins.ai_gateway_factory(self.fake_cfg("--ai-authorize", grant))
                self.assertIn(code, str(ctx.exception))

    def test_unknown_provider_and_model_are_refused(self):
        cfg = self.config("--ai-provider", "nope", "--ai-model", "x")
        with self.assertRaises(ValueError) as ctx:
            builtins.ai_gateway_factory(cfg)
        self.assertIn("unknown_provider", str(ctx.exception))

    def test_fake_provider_without_script_is_refused(self):
        cfg = self.config("--ai-provider", "fake", "--ai-model", "fake-model", environ={})
        with self.assertRaises(ValueError):
            builtins.ai_gateway_factory(cfg)


def _write_generated_tree(base: Path):
    """A staging tree with the shipped data and a ledger with two drafts (the generate fixture of test_cli_candidates)."""
    tree = base / "tree"
    tree.mkdir()
    for name in DATA_DIRS:
        shutil.copytree(KNOWLEDGE_ROOT / name, tree / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", tree / "gaps.json")
    ledger_path = base / "17-18.ledger.json"
    Ledger.create("17-18", _snap("111111111111", "1"), _snap("222222222222", "2"),
                  [_draft("sale.demo.order.compute", "method", "REMOVED"),
                   _draft("sale.demo.order.priority", "field", "REMOVED")], clock=CLOCK).save(ledger_path)
    source = base / "source.json"
    source.write_text(json.dumps(SOURCE), encoding="utf-8")
    return tree, ledger_path, source


class CliEndToEndTests(_Base):
    """`knowledge ai propose` through the real `builtins.main` (default context, real factory)."""

    def setUp(self):
        super().setUp()
        self.tree, self.ledger, self.source = _write_generated_tree(self.base)
        code, out, err = self.main("candidates", "generate", "--path", str(self.tree), "--ledger", str(self.ledger),
                                   "--source", str(self.source), "--checked-on", "2026-11-08")
        self.assertEqual(code, 0, err)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(["knowledge", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_propose_with_fake_provider_stores_ai_proposals(self):
        code, _, err = self.main("ai", "propose", "--path", str(self.tree), "--ledger", str(self.ledger), "--ai",
                                 "--ai-consent-send-code", "--ai-provider", "fake", "--ai-model", "fake-model",
                                 "--ai-budget-job-tokens", "100000", "--ai-authorize", "fake=evidence_excerpt")
        self.assertEqual(code, 0, err)
        items = sorted((self.tree / "candidates" / "ai").glob("CR-*.json"))
        self.assertTrue(items)
        for path in items:
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["origin"], "AI_PROPOSED")

    def test_propose_without_ai_flags_exits_2_and_builds_no_gateway(self):
        with mock.patch("odooflux.ai.gateway.build_gateway") as gw:
            code, _, err = self.main("ai", "propose", "--path", str(self.tree), "--ledger", str(self.ledger))
        self.assertEqual(code, 2)
        self.assertIn("--ai", err)
        gw.assert_not_called()
        self.assertFalse((self.tree / "candidates" / "ai").exists())


if __name__ == "__main__":
    unittest.main()
