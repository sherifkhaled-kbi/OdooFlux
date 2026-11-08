"""Provider contract types (contracts/ai-provider.md, contract version 1).

The D-08 error kinds (authorization, kill switch, catalog, sensitive content) are additive, so the
contract version stays 1.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

from odooflux.core.contracts import CONTRACT_VERSION  # noqa: F401  (re-exported for adapters)

TRANSPORT_ERROR_KINDS = ("auth", "rate_limit", "transient", "invalid_request", "unknown")
GATEWAY_ERROR_KINDS = ("authorization_missing", "authorization_provider_mismatch",
                       "authorization_category_denied", "transmission_disabled",
                       "sensitive_content_excluded", "model_not_in_catalog")
ERROR_KINDS = TRANSPORT_ERROR_KINDS + GATEWAY_ERROR_KINDS
RETRYABLE_KINDS = ("rate_limit", "transient")
STOP_REASONS = ("complete", "max_tokens", "error")
DATA_CATEGORIES = ("source_python", "source_xml", "evidence_excerpt")

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "replacement": {"type": "string"},
        "notes": {"type": "string"},
        "cannot_fix": {"type": "boolean"},
    },
    "required": ["replacement", "notes", "cannot_fix"],
}


def heuristic_tokens(text: str) -> int:
    """Documented fallback counter: ceil(len(utf8 bytes) / 4). Always an estimate."""
    return math.ceil(len(text.encode("utf-8", errors="replace")) / 4)


@dataclass(frozen=True)
class ModelDescriptor:
    provider: str
    id: str
    context_window: int = 0
    max_output: int = 0
    structured_output: bool = False
    tool_calling: bool = False
    pricing: Optional[dict] = None  # input_per_mtok, output_per_mtok, cached_per_mtok; None -> cost is null


@dataclass(frozen=True)
class Usage:
    input: int = 0
    output: int = 0
    cached: int = 0
    estimated: bool = False


@dataclass
class AIRequest:
    request_id: str
    model: str
    system: str
    messages: list
    response_schema: dict
    max_output_tokens: int
    budget_ref: str
    cache_key: str
    region: dict
    provider: str = ""
    data_categories: tuple = ()
    rule_id: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class AIResponse:
    text: str = ""
    parsed: Optional[dict] = None
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = "complete"
    error_kind: Optional[str] = None
    cost: Optional[float] = None
    attempts: int = 1
    detail: str = ""  # short, content-free diagnostic (status code, exception class); never prompt text


def error_response(kind: str, detail: str = "") -> AIResponse:
    return AIResponse(stop_reason="error", error_kind=kind, detail=detail)


@dataclass(frozen=True)
class UsageRecord:
    request_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    estimated: bool
    cost: Optional[float]
    outcome: str  # accepted | rejected:<reason> | skipped:<reason> | error:<kind> | cache_hit
    finding_ids: tuple = ()
    duration_ms: int = 0
    module: str = ""
    attempts: int = 1  # provider attempts behind this request (retries included); tokens are summed over them


def parse_structured(text: str) -> Optional[dict]:
    """Validate ``text`` against RESPONSE_SCHEMA locally. Returns the dict or None (never raises)."""
    import json
    text = (text or "").strip()
    if text.startswith("```") and text.endswith("```"):  # one surrounding code fence is tolerated, nothing else
        inner = text.split("\n", 1)[1] if "\n" in text else ""
        text = inner.rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("replacement"), str) or not isinstance(data.get("cannot_fix"), bool):
        return None
    notes = data.get("notes", "")
    if not isinstance(notes, str):
        return None
    return {"replacement": data["replacement"], "notes": notes[:500], "cannot_fix": data["cannot_fix"]}
