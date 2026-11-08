"""TST-010-008 (T016; REQ-AI-008, REQ-SEC-005, FR-008, SC-003): a scenario with canary secrets in the environment and
the credential file is run, then every artefact is scanned (reports in every format, run log, state, AI cache, audit
log, workspace and backup copies, captured log and console output). Zero canary matches are allowed."""

import contextlib
import io
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.integration.ai.test_pipeline_pass import SOURCE, ToyRule, make_module
from tests.unit.ai import _helpers as h
from tests.unit.ai._gateway_support import RecordingTransport, ok_openai

from odooflux.builtins import build_context
from odooflux.cli.migrate import make_validate_text
from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.orchestrator.run import RunOptions, new_state, reports_from_state, run_pipeline
from odooflux.discovery.modules import module_ref
from odooflux.reporting.model.model import build_report
from odooflux.utils import redaction

ENV_CANARY = "CANARY-ENV-7f3a9c2e51d84b60a1c9"
FILE_CANARY = "CANARY-FILE-b81d44e0c7a2956f3e10"
SHAPED_CANARY = "sk-ant-CANARYSHAPE0123456789abcdef"
CANARIES = (ENV_CANARY, FILE_CANARY, SHAPED_CANARY)
REPLACEMENT = "    def f_ok(self):\n        return new_api(1)\n"


def run_ai_scenario(extra_log=None):
    """A fix run with AI through an external provider whose credential is a canary (recorded transport, no network)."""
    tmp = Path(tempfile.mkdtemp())
    state_dir, secrets_dir = tmp / "state", tmp / "secrets"
    secrets_dir.mkdir()
    secrets_file = secrets_dir / "keys.env"
    secrets_file.write_text(f"UNUSED_KEY={FILE_CANARY}\nOTHER={SHAPED_CANARY}\n", encoding="utf-8")
    secrets_file.chmod(0o600)
    catalog = tmp / "catalog.json"
    catalog.write_text(json.dumps(h.test_catalog()), encoding="utf-8")
    module = make_module(tmp)
    ctx = build_context()
    ctx.registries.rules.register(ToyRule())
    entry = ctx.registries.ai_providers.get("ai-escalation")
    entry.metadata_source = lambda: h.TOY_METAS
    entry.environ = {"ALPHA_KEY": ENV_CANARY, "ANTHROPIC_API_KEY": SHAPED_CANARY}
    transport = RecordingTransport([ok_openai(json.dumps(
        {"replacement": REPLACEMENT, "notes": "", "cannot_fix": False}))])
    entry.transport_for = lambda name: transport
    cfg = {"enabled": True, "provider_type": "external", "provider": "alpha", "model": "m-one",
           "consent_send_code": True, "authorizations": {"alpha": ["evidence_excerpt", "source_python"]}, "kill_switch": False,
           "endpoint": "", "catalog_paths": [str(catalog)], "budget_job_tokens": 100000, "budget_module_tokens": None,
           "budget_file_tokens": None, "budget_request_tokens": None, "budget_job_cost": None, "max_retries": 0,
           "timeout_s": 5.0, "use_cache": True, "clear_cache": False, "secrets_file": str(secrets_file),
           "fake_script": ""}
    plan = build_plan(ctx.graph(), "14.0", "15.0", [module_ref(module, 0)])
    options = RunOptions(from_version=14, to_version=15, mode="fix", backup=True, ai=True, module_paths=[str(module)])
    run = RunDir.create(state_dir, reversible=True, with_backup=True)
    state = new_state(run, plan, options, plan.modules)
    state["ai_config"] = cfg
    run.write_state(state)
    console, records = io.StringIO(), []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture(level=logging.DEBUG)
    logging.getLogger().addHandler(handler)
    old = logging.getLogger().level
    logging.getLogger().setLevel(logging.DEBUG)
    try:
        with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
            run_pipeline(run, state, ctx.registries, validate_text=make_validate_text(ctx.registries),
                         layer3=ctx.layer3)
    finally:
        logging.getLogger().removeHandler(handler)
        logging.getLogger().setLevel(old)
    reports_dir = tmp / "reports"
    reports_dir.mkdir()
    document = build_report(state, reports_from_state(state), run_log_path=str(run.log.path))
    for name in ("json", "sarif", "html"):
        renderer = ctx.registries.renderers.get(name)
        text = renderer.render(document, include_fixed=True, exit_code=0) if name == "sarif" else renderer.render(document)
        (reports_dir / f"report.{name}").write_text(text, encoding="utf-8")
    return SimpleNamespace(run=run, state=state, state_dir=state_dir, module=module, reports_dir=reports_dir,
                           transport=transport, console=console.getvalue(), logs=records, tmp=tmp,
                           secrets_dir=secrets_dir)


class SecretScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = run_ai_scenario()

    def test_the_credential_really_reached_the_adapter(self):
        calls = self.scenario.transport.calls
        self.assertTrue(calls, "the scenario never called the provider")
        self.assertIn(ENV_CANARY, json.dumps(calls[0]["headers"]), "the canary never travelled: the scan proves nothing")

    def test_no_artefact_contains_a_canary(self):
        s = self.scenario
        hits = redaction.scan_for_canaries([s.state_dir, s.reports_dir, s.module], CANARIES)
        self.assertEqual(hits, [])

    def test_captured_console_and_log_output_contain_no_canary(self):
        for blob in [s for s in [self.scenario.console, *self.scenario.logs]]:
            for canary in CANARIES:
                self.assertNotIn(canary, blob)

    def test_artefact_inventory_covers_every_kind(self):
        s = self.scenario
        names = {p.name for p in s.state_dir.rglob("*") if p.is_file()}
        self.assertIn("state.json", names)
        self.assertIn("run_log.jsonl", names)
        self.assertIn("audit.jsonl", names)
        self.assertTrue(any(p.parent.name == "ai-cache" or "ai-cache" in p.parts for p in s.state_dir.rglob("*.json")))
        self.assertEqual({p.suffix for p in s.reports_dir.iterdir()}, {".json", ".sarif", ".html"})

    def test_the_scanner_finds_a_planted_canary(self):
        planted = Path(tempfile.mkdtemp())
        (planted / "nested").mkdir()
        (planted / "nested" / "leak.txt").write_text(f"token={FILE_CANARY}\n", encoding="utf-8")
        (planted / "bin.dat").write_bytes(b"\x00\x01" + ENV_CANARY.encode("utf-8"))
        hits = redaction.scan_for_canaries([planted], CANARIES)
        self.assertEqual(sorted(Path(h_).name for h_, _ in hits), ["bin.dat", "leak.txt"])

    def test_shape_scan_flags_unlisted_credential_shapes(self):
        planted = Path(tempfile.mkdtemp())
        (planted / "x.txt").write_text("key sk-ant-abcdefghijklmnopqrstuv in a log\n", encoding="utf-8")
        self.assertTrue(redaction.scan_for_shapes([planted]))
        (planted / "x.txt").write_text("nothing secret\n", encoding="utf-8")
        self.assertEqual(redaction.scan_for_shapes([planted]), [])


class RedactionUnitTests(unittest.TestCase):
    def test_redact_text_removes_values_and_shapes(self):
        text = f"call with {ENV_CANARY} and Authorization: Bearer abcdef123456 and sk-ant-0123456789abcdef"
        out = redaction.redact_text(text, secrets=[ENV_CANARY])
        self.assertNotIn(ENV_CANARY, out)
        self.assertNotIn("abcdef123456", out)
        self.assertNotIn("sk-ant-0123456789abcdef", out)

    def test_scrub_walks_nested_values_and_secret_names(self):
        data = {"api_key": "v1", "list": [{"password": "v2", "fine": "x"}], "token": "v3", "n": 4}
        out = redaction.scrub(data)
        self.assertEqual(out, {"api_key": "***", "list": [{"password": "***", "fine": "x"}], "token": "***", "n": 4})

    def test_short_or_empty_secret_values_do_not_mangle_text(self):
        self.assertEqual(redaction.redact_text("abc", secrets=["", "a"]), "abc")


if __name__ == "__main__":
    unittest.main()
