"""Scripted fake provider (REQ-AI-001): replays request -> response pairs deterministically, never opens a transport."""

import json

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.ai.providers.types import (
    AIResponse, Usage, error_response, heuristic_tokens)


class FakeProvider:
    contract_version = CONTRACT_VERSION

    def __init__(self, script: dict, *, models=(), name: str = "fake"):
        self.name = name
        self._entries = [dict(e, _left=e.get("times")) for e in script.get("entries", [])]
        self._models = list(models)
        self.requests = []  # recorded requests (tests inspect what would have been sent)

    @classmethod
    def from_file(cls, path, **kwargs):
        with open(path, encoding="utf-8") as handle:
            return cls(json.load(handle), **kwargs)

    def models(self) -> list:
        return list(self._models)

    def supports(self) -> set:
        return {"json_schema", "usage_cached_tokens"}

    def count_tokens(self, text: str, model: str):
        return heuristic_tokens(text), True

    def _matches(self, entry: dict, req) -> bool:
        if entry["_left"] == 0:
            return False
        match = entry.get("match") or {}
        body = "\n".join(m.get("content", "") for m in req.messages)
        if "contains" in match and match["contains"] not in body:
            return False
        if "rule_id" in match and match["rule_id"] != req.rule_id:
            return False
        return True

    def complete(self, req) -> AIResponse:
        self.requests.append(req)
        for entry in self._entries:
            if not self._matches(entry, req):
                continue
            if entry["_left"] is not None:
                entry["_left"] -= 1
            return self._build(entry["response"], req)
        return error_response("invalid_request", "no_script_match")

    def _build(self, spec: dict, req) -> AIResponse:
        usage_spec = spec.get("usage") or {}
        usage = Usage(input=usage_spec.get("input", 0), output=usage_spec.get("output", 0),
                      cached=usage_spec.get("cached", 0), estimated=bool(usage_spec.get("estimated", False)))
        if spec.get("error_kind"):
            resp = error_response(spec["error_kind"], "scripted")
            resp.usage = usage
            return resp
        if "raw_text" in spec:
            text = spec["raw_text"]
        else:
            text = json.dumps({"replacement": spec.get("replacement", ""), "notes": spec.get("notes", ""),
                               "cannot_fix": bool(spec.get("cannot_fix", False))})
        from odooflux.ai.providers.types import parse_structured
        return AIResponse(text=text, parsed=parse_structured(text), usage=usage,
                          stop_reason=spec.get("stop_reason", "complete"))
