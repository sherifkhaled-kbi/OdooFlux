"""Adapter for the Messages API over the stdlib transport (REQ-AI-001, REQ-AI-006). No SDK, no logging.

The endpoint, the credential variable and the ``anthropic_version`` header value come from the catalog entry.
"""

import json

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.ai.providers.transport import UrllibTransport, kind_for_status
from odooflux.ai.providers.types import (
    AIResponse, Usage, error_response, heuristic_tokens, parse_structured)


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class AnthropicProvider:
    contract_version = CONTRACT_VERSION

    def __init__(self, *, name: str, endpoint: str, models=(), credential=None, transport=None,
                 timeout_s: float = 60.0, options=None):
        self.name = name
        self.endpoint = endpoint
        self._models = list(models)
        self._credential = credential
        self._transport = transport if transport is not None else UrllibTransport()
        self.timeout_s = timeout_s
        self.options = dict(options or {})

    def models(self) -> list:
        return list(self._models)

    def supports(self) -> set:
        return {"usage_cached_tokens"}

    def count_tokens(self, text: str, model: str):
        return heuristic_tokens(text), True

    def complete(self, req) -> AIResponse:
        headers = {"Content-Type": "application/json"}
        if self._credential:
            headers["x-api-key"] = self._credential.reveal()
        if self.options.get("anthropic_version"):
            headers["anthropic-version"] = self.options["anthropic_version"]
        body = {"model": req.model, "max_tokens": req.max_output_tokens, "system": req.system,
                "messages": [dict(m) for m in req.messages]}
        try:
            result = self._transport.post(self.endpoint, headers, json.dumps(body).encode("utf-8"), self.timeout_s)
        except Exception as exc:  # noqa: BLE001  only the class name is kept
            return error_response("unknown", type(exc).__name__)
        if result.error:
            return error_response(kind_for_status(0), result.error)
        if not 200 <= result.status < 300:
            return error_response(kind_for_status(result.status), f"http_{result.status}")
        try:
            data = json.loads(result.body.decode("utf-8"))
            blocks = data["content"]
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
            stop_reason = data.get("stop_reason")
        except (ValueError, KeyError, TypeError, AttributeError):
            return error_response("unknown", "malformed_response")
        if stop_reason == "refusal":
            return error_response("invalid_request", "refusal")
        stop = "max_tokens" if stop_reason == "max_tokens" else "complete"
        return AIResponse(text=text, parsed=parse_structured(text), usage=self._usage(data, req, text), stop_reason=stop)

    @staticmethod
    def _usage(data: dict, req, text: str) -> Usage:
        usage = data.get("usage")
        if not isinstance(usage, dict) or "input_tokens" not in usage:
            source = req.system + "".join(m.get("content", "") for m in req.messages)
            return Usage(input=heuristic_tokens(source), output=heuristic_tokens(text), estimated=True)
        return Usage(input=_int(usage.get("input_tokens")) + _int(usage.get("cache_creation_input_tokens")),
                     output=_int(usage.get("output_tokens")), cached=_int(usage.get("cache_read_input_tokens")))
