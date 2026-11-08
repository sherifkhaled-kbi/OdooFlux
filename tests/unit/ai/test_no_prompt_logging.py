"""TST-007-023 (FR-021, REQ-AI-008): API keys and prompt/response content never appear in logs; metadata only."""

import contextlib
import io
import logging
import unittest

from . import _helpers as h
from ._gateway_support import RecordingTransport, config_for, http, make_request, ok_openai
from odooflux.ai.gateway import build_gateway
from odooflux.ai.providers.catalog import load_catalog

KEY = "sk-logcanary-9f8e7d6c5b4a3928"
PROMPT = "PROMPT_CANARY_do_not_log_this_customer_code_xyz"
RESPONSE = "RESPONSE_CANARY_do_not_log_the_model_output_abc"
CATALOG = load_catalog(extra=[h.test_catalog()])
GRANTS = {"alpha": ["source_python"]}


class CaptureLogs:
    def __enter__(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setLevel(1)
        self.records = []
        outer = self

        class Collect(logging.Handler):
            def emit(self, record):
                outer.records.append(record.getMessage() + " " + repr(record.__dict__.get("args")))
        self.collect = Collect(level=1)
        root = logging.getLogger()
        self.old_level = root.level
        root.setLevel(1)
        root.addHandler(self.handler)
        root.addHandler(self.collect)
        self.out, self.err = io.StringIO(), io.StringIO()
        self.ctx = contextlib.ExitStack()
        self.ctx.enter_context(contextlib.redirect_stdout(self.out))
        self.ctx.enter_context(contextlib.redirect_stderr(self.err))
        return self

    def __exit__(self, *exc):
        self.ctx.close()
        root = logging.getLogger()
        root.removeHandler(self.handler)
        root.removeHandler(self.collect)
        root.setLevel(self.old_level)

    @property
    def everything(self) -> str:
        return self.stream.getvalue() + "\n".join(self.records) + self.out.getvalue() + self.err.getvalue()


class NoPromptLoggingTests(unittest.TestCase):
    def gateway(self, transport):
        return build_gateway(config_for("alpha", "m-one", grants=GRANTS, retries=1), CATALOG,
                             environ={"ALPHA_KEY": KEY}, transport_for=lambda n: transport, sleep=lambda s: None)

    def test_success_logs_metadata_only(self):
        t = RecordingTransport([ok_openai(RESPONSE, prompt=111, completion=22)])
        with CaptureLogs() as cap:
            self.gateway(t).complete(make_request("alpha", "m-one", text=PROMPT))
        text = cap.everything
        for secret in (KEY, PROMPT, RESPONSE):
            self.assertNotIn(secret, text)
        self.assertIn("alpha", text)  # metadata is logged: provider, model, tokens, outcome
        self.assertIn("m-one", text)
        self.assertIn("111", text)

    def test_error_paths_do_not_log_keys_or_prompts(self):
        for results in ([http(500, PROMPT.encode())], [http(401, KEY.encode())], [http(429, RESPONSE.encode())]):
            t = RecordingTransport(results)
            with CaptureLogs() as cap:
                self.gateway(t).complete(make_request("alpha", "m-one", text=PROMPT))
            for secret in (KEY, PROMPT, RESPONSE):
                self.assertNotIn(secret, cap.everything)

    def test_transport_exception_text_is_not_propagated(self):
        t = RecordingTransport([], raises=RuntimeError(f"boom {KEY} {PROMPT}"))
        with CaptureLogs() as cap:
            resp = self.gateway(t).complete(make_request("alpha", "m-one", text=PROMPT))
        self.assertEqual(resp.error_kind, "unknown")
        for secret in (KEY, PROMPT):
            self.assertNotIn(secret, cap.everything)
            self.assertNotIn(secret, resp.detail)
            self.assertNotIn(secret, resp.text)

    def test_key_only_in_the_authorization_header_never_in_url_or_body(self):
        t = RecordingTransport([ok_openai(RESPONSE)])
        self.gateway(t).complete(make_request("alpha", "m-one", text=PROMPT))
        call = t.calls[0]
        self.assertNotIn(KEY, call["url"])
        self.assertNotIn(KEY.encode(), call["body"])
        self.assertIn(KEY, "".join(call["headers"].values()))

    def test_response_object_and_secret_repr_hide_the_key(self):
        from odooflux.ai.providers.credentials import Secret
        self.assertNotIn(KEY, repr(Secret(KEY)))
        gw = self.gateway(RecordingTransport([ok_openai(RESPONSE)]))
        self.assertNotIn(KEY, repr(gw.__dict__))

    def test_gateway_and_adapter_source_has_no_logging_of_content(self):
        import re
        for rel in ("gateway.py", "providers/openai_compatible.py", "providers/anthropic.py", "providers/transport.py"):
            body = (h.SRC / "odooflux" / "ai" / rel).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\bprint\(", body), rel)
            for m in re.finditer(r"(?:log|logger|logging)\.\w+\(([^)]*)\)", body):
                self.assertNotRegex(m.group(1), r"\b(req|request|messages|response\.text|resp\.text|body|headers|key)\b",
                                    f"{rel}: {m.group(0)}")


if __name__ == "__main__":
    unittest.main()
