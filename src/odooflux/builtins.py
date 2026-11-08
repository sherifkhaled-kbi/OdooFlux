"""Composition root: registers built-in entries, loads the knowledge data, and runs the CLI.

This is the only module that wires adapters (parsers, validators, AI, renderers) into the core.
The console script and the launcher both enter through :func:`main`.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.ai.integration import EscalationPass
from odooflux.ai.providers.legacy_anthropic import LegacyAnthropicProvider
from odooflux.core.contracts.plugins import Registries
from odooflux.core.orchestrator.run_inputs import RunRuleBinder
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.parsers.python.document import PythonParser  # noqa: F401  (registered below)
from odooflux.parsers.xml.wellformed import XmlParser
from odooflux.reporting import register_default_renderers
from odooflux.validation.dependency.integrity import check_integrity
from odooflux.validation.static.rescan import RescanValidator
from odooflux.validation.syntax.manifest import ManifestSyntaxValidator
from odooflux.validation.syntax.python import PythonSyntaxValidator
from odooflux.validation.syntax.xml import XmlSyntaxValidator
from odooflux.versions.registry.loader import KNOWLEDGE_FILE, load_version_data
from odooflux.versions.graph.graph import VersionGraph


class _ParserEntry:
    """Registry entry for a parser adapter (keyed by language)."""

    contract_version = 1

    def __init__(self, key, parser):
        self.key = key
        self._parser = parser

    def parse(self, text):
        return self._parser.parse(text)


@dataclass
class Context:
    registries: Registries
    transitions: dict
    versions: list = field(default_factory=list)
    layer3: object = None  # callable(path, to_version) -> (findings, ValidationResult), REQ-VAL-003

    def graph(self) -> VersionGraph:
        return VersionGraph(self.registries.versions.all(), self.transitions)


def build_context(knowledge_path: Path = KNOWLEDGE_FILE) -> Context:
    versions, transitions = load_version_data(knowledge_path)
    registries = Registries()
    for version in versions:
        registries.versions.register(version)
    registries.parsers.register(_ParserEntry("python", PythonParser()))
    registries.parsers.register(_ParserEntry("xml", XmlParser()))
    for validator in (PythonSyntaxValidator(), XmlSyntaxValidator(), ManifestSyntaxValidator(),
                      RescanValidator()):
        registries.validators.register(validator)
    registries.ai_providers.register(LegacyAnthropicProvider())
    registries.ai_providers.register(EscalationPass(layer3=_layer3))
    register_default_renderers(registries)
    registries.run_rule_binder = RunRuleBinder(lambda: load_knowledge().rules, BINDABLE_MODULES)
    return Context(registries=registries, transitions=transitions, versions=versions, layer3=_layer3)


def _layer3(path, to_version: int):
    return check_integrity([path], target_version=f"{to_version}.0")


def build_registries() -> Registries:
    return build_context().registries


def main(argv=None) -> int:
    from odooflux.cli.main import run
    argv = sys.argv[1:] if argv is None else list(argv)
    return run(argv, build_context())


if __name__ == "__main__":
    raise SystemExit(main())
