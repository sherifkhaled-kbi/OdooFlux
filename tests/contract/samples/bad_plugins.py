"""Entries that declare an unsupported contract version (TST-003-025)."""

from odooflux.core.contracts.plugins import PluginEntry


class _Bad:
    contract_version = 99

    def __init__(self, key):
        self.key = key


PLUGIN = [PluginEntry(kind, _Bad(f"bad-{kind}")) for kind in
          ("versions", "rules", "parsers", "validators", "runtimes", "ai_providers", "renderers")]
