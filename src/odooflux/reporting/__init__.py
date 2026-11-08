"""Report model v1, schema check, and renderers (REQ-REP-001, FR-017).

Renderer registry (T006, REQ-ARC-006): :func:`register_default_renderers` registers the built-in formats into the core's
renderer registry. A renderer is any object with ``key``, ``contract_version`` (must equal the core CONTRACT_VERSION,
otherwise registration is rejected) and ``render(report, **options) -> str``. Third parties add formats through the
plugin mechanism without core edits."""

DEFAULT_FORMATS = ("json", "terminal", "html", "sarif", "diff", "diff-index", "legacy-json")


def register_default_renderers(registries) -> None:
    from odooflux.reporting.exporters.diff import DiffIndexRenderer, DiffRenderer
    from odooflux.reporting.exporters.legacy_json import LegacyJsonRenderer
    from odooflux.reporting.exporters.sarif import SarifRenderer
    from odooflux.reporting.html.html import HtmlRenderer
    from odooflux.reporting.model.json_renderer import JsonRenderer
    from odooflux.reporting.terminal.ansi import TerminalRenderer
    for renderer in (JsonRenderer(), TerminalRenderer(), HtmlRenderer(), SarifRenderer(), DiffRenderer(),
                     DiffIndexRenderer(), LegacyJsonRenderer()):
        registries.renderers.register(renderer)
