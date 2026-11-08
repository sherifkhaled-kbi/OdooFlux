"""Adapter for the chat-completions wire format (REQ-AI-001, FR-015).

One adapter serves OpenAI, DeepSeek, Z.ai and any local OpenAI-compatible server (Ollama, vLLM): the provider differs
only by catalog entry (base URL, credential variable, options). It never raises for provider or HTTP errors, never
reads an error body into a diagnostic (bodies can echo the prompt) and never logs.
"""

import json

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.ai.providers.transport import UrllibTransport, kind_for_status
from odooflux.ai.providers.types import (
    AIResponse, Usage, error_response, heuristic_tokens, parse_structured)

SUFFIX = "/chat/completions"


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class OpenAICompatibleProvider:
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
        self._by_id = {m.id: m for m in self._models}

    def models(self) -> list:
        return list(self._models)

    def supports(self) -> set:
        return {"json_schema", "usage_cached_tokens"} if any(m.structured_output for m in self._models) \
            else {"usage_cached_tokens"}

    def count_tokens(self, text: str, model: str):
        return heuristic_tokens(text), True

    def _url(self) -> str:
        base = self.endpoint.rstrip("/")
        return base if base.endswith(SUFFIX) else base + SUFFIX

    def complete(self, req) -> AIResponse:
        headers = {"Content-Type": "application/json"}
        if self._credential:
            headers["Authorization"] = f"Bearer {self._credential.reveal()}"
        body = {"model": req.model,
                "messages": [{"role": "system", "content": req.system}] + [dict(m) for m in req.messages],
                self.options.get("max_tokens_param", "max_tokens"): req.max_output_tokens}
        descriptor = self._by_id.get(req.model)
        if descriptor is not None and descriptor.structured_output:
            body["response_format"] = {"type": "json_object"}
        try:
            result = self._transport.post(self._url(), headers, json.dumps(body).encode("utf-8"), self.timeout_s)
        except Exception as exc:  # noqa: BLE001  a transport must not break the run; only the class name is kept
            return error_response("unknown", type(exc).__name__)
        if result.error:
            return error_response(kind_for_status(0), result.error)
        if not 200 <= result.status < 300:
            return error_response(kind_for_status(result.status), f"http_{result.status}")
        return self._parse(result.body, req)

    def _parse(self, payload: bytes, req) -> AIResponse:
        try:
            data = json.loads(payload.decode("utf-8"))
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            return error_response("unknown", "malformed_response")
        finish = choice.get("finish_reason")
        if finish == "length":
            stop = "max_tokens"
        elif finish == "content_filter":
            return error_response("invalid_request", "content_filter")
        else:
            stop = "complete"
        return AIResponse(text=content, parsed=parse_structured(content), usage=self._usage(data, req, content),
                          stop_reason=stop)

    @staticmethod
    def _usage(data: dict, req, content: str) -> Usage:
        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict) or "prompt_tokens" not in usage:
            text = req.system + "".join(m.get("content", "") for m in req.messages)
            return Usage(input=heuristic_tokens(text), output=heuristic_tokens(content), estimated=True)
        details = usage.get("prompt_tokens_details")
        cached = _int(details.get("cached_tokens")) if isinstance(details, dict) else 0
        cached = cached or _int(usage.get("prompt_cache_hit_tokens"))
        prompt = _int(usage.get("prompt_tokens"))
        return Usage(input=max(prompt - cached, 0), output=_int(usage.get("completion_tokens")), cached=cached)
