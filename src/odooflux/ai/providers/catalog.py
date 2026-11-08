"""Per-provider model catalog loaded from configuration (FR-018, ADR-017). No model id or price is in code.

The packaged ``catalog/providers.json`` lists providers, endpoints and credential variable names, with no models.
Users merge their own catalog files over it (``--ai-catalog``); later files override earlier ones field by field and
models are merged by id.
"""

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.ai.providers.types import ModelDescriptor

SCHEMA = "odooflux.ai-catalog/1"
PACKAGED = Path(__file__).resolve().parent.parent / "catalog" / "providers.json"
TYPES = ("external", "local", "fake")
ADAPTERS = ("openai_compatible", "anthropic", "fake")


class CatalogError(Exception):
    """``code``: catalog_invalid, unknown_provider, model_not_in_catalog, endpoint_not_https, endpoint_required."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


@dataclass
class ProviderEntry:
    name: str
    type: str
    adapter: str
    endpoint: str = ""
    credential_env: str = ""
    timeout_s: float = 0.0  # 0 = use the run's --ai-timeout
    options: dict = field(default_factory=dict)
    models: dict = field(default_factory=dict)  # id -> ModelDescriptor


def _bad(message: str):
    raise CatalogError("catalog_invalid", message)


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        _bad(f"{label} must be a non-negative number")
    return value


def _model(provider: str, doc) -> ModelDescriptor:
    if not isinstance(doc, dict) or not isinstance(doc.get("id"), str) or not doc["id"]:
        _bad(f"{provider}: every model needs a string id")
    pricing = doc.get("pricing")
    if pricing is not None:
        if not isinstance(pricing, dict):
            _bad(f"{provider}/{doc['id']}: pricing must be an object or null")
        pricing = {k: _number(v, f"{provider}/{doc['id']} pricing.{k}") for k, v in pricing.items()}
    for flag in ("structured_output", "tool_calling"):
        if flag in doc and not isinstance(doc[flag], bool):
            _bad(f"{provider}/{doc['id']}: {flag} must be a boolean")
    return ModelDescriptor(
        provider=provider, id=doc["id"], context_window=int(_number(doc.get("context_window", 0), "context_window")),
        max_output=int(_number(doc.get("max_output", 0), "max_output")),
        structured_output=bool(doc.get("structured_output", False)), tool_calling=bool(doc.get("tool_calling", False)),
        pricing=pricing or None)


class Catalog:
    def __init__(self):
        self._providers: dict = {}

    def merge(self, doc) -> None:
        if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("providers"), dict):
            _bad(f"expected schema {SCHEMA} with a providers object")
        for name, spec in doc["providers"].items():
            if not isinstance(spec, dict):
                _bad(f"{name}: provider must be an object")
            entry = self._providers.get(name)
            if entry is None:
                if spec.get("type") not in TYPES or spec.get("adapter") not in ADAPTERS:
                    _bad(f"{name}: a new provider needs type {TYPES} and adapter {ADAPTERS}")
                entry = ProviderEntry(name=name, type=spec["type"], adapter=spec["adapter"])
                self._providers[name] = entry
            if "type" in spec and spec["type"] not in TYPES:
                _bad(f"{name}: unknown type {spec['type']!r}")
            if "adapter" in spec and spec["adapter"] not in ADAPTERS:
                _bad(f"{name}: unknown adapter {spec['adapter']!r}")
            for key in ("type", "adapter", "endpoint", "credential_env"):
                if key in spec:
                    if not isinstance(spec[key], str):
                        _bad(f"{name}: {key} must be a string")
                    setattr(entry, key, spec[key])
            if "timeout_s" in spec:
                entry.timeout_s = float(_number(spec["timeout_s"], f"{name}.timeout_s"))
            if "options" in spec:
                if not isinstance(spec["options"], dict):
                    _bad(f"{name}: options must be an object")
                entry.options = {**entry.options, **spec["options"]}
            if "models" in spec:
                if not isinstance(spec["models"], list):
                    _bad(f"{name}: models must be a list")
                for model_doc in spec["models"]:
                    descriptor = _model(name, model_doc)
                    entry.models[descriptor.id] = descriptor

    def providers(self) -> list:
        return sorted(self._providers)

    def provider(self, name: str) -> ProviderEntry:
        try:
            return self._providers[name]
        except KeyError:
            raise CatalogError("unknown_provider", name) from None

    def resolve(self, provider: str, model: str, endpoint: str = ""):
        """``(ProviderEntry copy with the effective endpoint, ModelDescriptor)`` or a CatalogError."""
        entry = copy.deepcopy(self.provider(provider))
        if model not in entry.models:
            raise CatalogError("model_not_in_catalog", f"{provider}/{model}")
        if endpoint:
            entry.endpoint = endpoint
        if entry.type == "external" and not entry.endpoint.startswith("https://"):
            raise CatalogError("endpoint_not_https", provider)
        if entry.type == "local" and not entry.endpoint:
            raise CatalogError("endpoint_required", provider)
        return entry, entry.models[model]


def load_catalog(paths=(), extra=()) -> Catalog:
    """Packaged catalog, then each file in ``paths``, then each dict in ``extra``."""
    catalog = Catalog()
    try:
        catalog.merge(json.loads(PACKAGED.read_text(encoding="utf-8")))
    except OSError:
        _bad("the packaged catalog is missing from this installation")
    for path in paths:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _bad(f"{Path(path).name}: {type(exc).__name__}")
        catalog.merge(doc)
    for doc in extra:
        catalog.merge(doc)
    return catalog
