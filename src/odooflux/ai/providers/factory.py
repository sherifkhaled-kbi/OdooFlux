"""Adapter selection from a catalog entry (the only place that maps ``adapter`` names to classes)."""

from odooflux.ai.providers.anthropic import AnthropicProvider
from odooflux.ai.providers.fake import FakeProvider
from odooflux.ai.providers.openai_compatible import OpenAICompatibleProvider


def build_provider(entry, *, credential=None, transport=None, timeout_s: float = 60.0, fake_script=None):
    models = list(entry.models.values())
    if entry.adapter == "fake":
        provider = FakeProvider(fake_script or {}, models=models, name=entry.name)
        return provider
    cls = {"openai_compatible": OpenAICompatibleProvider, "anthropic": AnthropicProvider}[entry.adapter]
    return cls(name=entry.name, endpoint=entry.endpoint, models=models, credential=credential, transport=transport,
               timeout_s=timeout_s, options=entry.options)
