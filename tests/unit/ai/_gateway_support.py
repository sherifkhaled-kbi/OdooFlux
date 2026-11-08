"""Doubles for gateway and adapter tests: a recording transport that returns canned results, and config helpers."""

from ._setup_path import SRC  # noqa: F401

import json

from odooflux.ai.gateway import GatewayConfig
from odooflux.ai.providers.transport import TransportResult
from odooflux.ai.providers.types import AIRequest, RESPONSE_SCHEMA


class RecordingTransport:
    """Replays ``results`` in order (the last one repeats). Records every call; ``raises`` makes post() raise."""

    def __init__(self, results, raises=None):
        self.results = list(results)
        self.calls = []
        self.raises = raises

    def post(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        if self.raises is not None:
            raise self.raises
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class RaisingTransport(RecordingTransport):
    def __init__(self):
        super().__init__([], raises=AssertionError("a transport was opened"))


def ok_openai(content, *, prompt=100, completion=20, finish="stop", cached=0):
    body = {"choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                      "prompt_tokens_details": {"cached_tokens": cached}}}
    return TransportResult(200, json.dumps(body).encode())


def ok_anthropic(content, *, inp=100, out=20, stop="end_turn", cache_read=0):
    body = {"content": [{"type": "text", "text": content}], "stop_reason": stop,
            "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cache_read}}
    return TransportResult(200, json.dumps(body).encode())


def http(status, body=b"{}"):
    return TransportResult(status, body)


GOOD_JSON = json.dumps({"replacement": "x = 1\n", "notes": "", "cannot_fix": False})


def config_for(provider, model, *, grants=None, kill=False, retries=2, timeout=7.0):
    return GatewayConfig(provider=provider, model=model, grants=grants or {}, kill_switch=kill,
                         max_retries=retries, timeout_s=timeout)


def make_request(provider, model, text="hello", categories=("source_python",), path="models/a.py"):
    return AIRequest(request_id="r1", model=model, system="system text",
                     messages=[{"role": "user", "content": f"<code>\n{text}\n</code>"}],
                     response_schema=RESPONSE_SCHEMA, max_output_tokens=100, budget_ref="job", cache_key="",
                     region={"path": path, "span": [0, 1], "kind": "function"}, provider=provider,
                     data_categories=tuple(categories))
