"""Renderer for report model v1: deterministic JSON (R-08)."""

import json

from odooflux.core.contracts import CONTRACT_VERSION


class JsonRenderer:
    key = "json"
    contract_version = CONTRACT_VERSION

    def render(self, report: dict) -> str:
        return json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
