"""A rule that raises in detect (TST-003-026)."""

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.plugins import PluginEntry


class RaisingRule:
    key = "sample.raises"
    contract_version = CONTRACT_VERSION
    step = "*"
    depends = ()

    def detect(self, document):
        raise RuntimeError("boom from plugin")


PLUGIN = [PluginEntry("rules", RaisingRule())]
