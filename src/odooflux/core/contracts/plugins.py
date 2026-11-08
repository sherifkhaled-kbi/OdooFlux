"""Generic registries (R-03). Entries expose ``key`` and ``contract_version``."""

from odooflux.core.contracts import (
    CONTRACT_VERSION, DuplicateRegistrationError, PluginContractError)

KINDS = ("versions", "rules", "parsers", "validators", "runtimes", "ai_providers", "renderers")


class Registry:
    def __init__(self, kind: str):
        self.kind = kind
        self._entries: dict = {}

    def register(self, entry, *, plugin: str = "builtin") -> None:
        actual = getattr(entry, "contract_version", None)
        if actual != CONTRACT_VERSION:
            raise PluginContractError(plugin, CONTRACT_VERSION, actual)
        key = entry.key
        if key in self._entries:
            raise DuplicateRegistrationError(f"{self.kind}: duplicate id {key!r}")
        self._entries[key] = entry

    def get(self, key):
        try:
            return self._entries[key]
        except KeyError:
            raise KeyError(f"{self.kind}: no entry {key!r}") from None

    def __contains__(self, key) -> bool:
        return key in self._entries

    def all(self) -> list:
        return [self._entries[k] for k in sorted(self._entries)]


class Registries:
    """The seven registries of the core (registries-and-plugins.md)."""

    def __init__(self):
        for kind in KINDS:
            setattr(self, kind, Registry(kind))


from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True)
class PluginEntry:
    """What a plugin module exports as ``PLUGIN``: one registry kind and one entry object."""

    kind: str
    entry: object
