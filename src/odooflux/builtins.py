"""Composition root: registers built-in entries, loads the knowledge data, and runs the CLI.

This is the only module that wires adapters (parsers, validators, AI, renderers) into the core.
The console script and the launcher both enter through :func:`main`.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.ai.integration import EscalationPass
from odooflux.ai.providers.legacy_anthropic import LegacyAnthropicProvider
from odooflux.core.contracts.plugins import Registries
from odooflux.core.orchestrator.run_inputs import RunRuleBinder
from odooflux.knowledge.loader import RELEASE_TREE, load_active_knowledge
from odooflux.knowledge.release.resolver import resolve_knowledge
from odooflux.knowledge.update.certification import attach_executor
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.parsers.python.document import PythonParser  # noqa: F401  (registered below)
from odooflux.parsers.xml.wellformed import XmlParser
from odooflux.parsers.extract_toolkit import ExtractToolkit, detector_table
from odooflux.transformers.certify_exec import FixCertifier

_FIX_CERTIFIER = FixCertifier(modules=BINDABLE_MODULES)  # one per process: certification accepts one attached executor (re-attach is a no-op)
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
    knowledge: object = None  # the KnowledgeHandle of this run (migrate); None: the process default
    rebuild: object = None    # callable(handle) -> Context bound to that handle (one resolution per migrate run)

    def graph(self) -> VersionGraph:
        return VersionGraph(self.registries.versions.all(), self.transitions)

    def for_knowledge(self, handle) -> "Context":
        """This context rebuilt so that every knowledge reader uses *handle* (REQ-KAP-036, REQ-KAP-005)."""
        return self if self.rebuild is None else self.rebuild(handle)


def knowledge_tree(handle) -> Path:
    """The knowledge tree a handle is read from: the built-in tree itself, or `<release>/knowledge` (note 27)."""
    return Path(handle.root) if handle.builtin else Path(handle.root) / RELEASE_TREE


def build_context(knowledge_path: Path = KNOWLEDGE_FILE, handle=None) -> Context:
    """*handle* is the single knowledge handle of a migrate run: the rule binder, versions registry, L3 integrity and
    AI escalation all read its tree. Without a handle the process default applies (binder resolves lazily)."""
    if handle is None:
        versions, transitions = load_version_data(knowledge_path)
        layer3, rows, tree = _layer3, _active_rule_rows, None
    else:
        tree = knowledge_tree(handle)
        versions, transitions = load_version_data(knowledge_root=tree)
        layer3 = _layer3_for(tree)
        rows = (lambda: load_active_knowledge(handle).rules)
    registries = Registries()
    for version in versions:
        registries.versions.register(version)
    registries.parsers.register(_ParserEntry("python", PythonParser()))
    registries.parsers.register(_ParserEntry("xml", XmlParser()))
    for validator in (PythonSyntaxValidator(), XmlSyntaxValidator(), ManifestSyntaxValidator(),
                      RescanValidator()):
        registries.validators.register(validator)
    registries.ai_providers.register(LegacyAnthropicProvider())
    registries.ai_providers.register(EscalationPass(layer3=layer3, knowledge_root=tree))
    register_default_renderers(registries)
    registries.run_rule_binder = _HandleRuleBinder(rows, BINDABLE_MODULES, None if handle is None or handle.builtin
                                                   else tree)
    registries.extract_toolkit = ExtractToolkit(detectors=detector_table(BINDABLE_MODULES))  # REQ-ARC-001: KAP adapters
    attach_executor(_FIX_CERTIFIER)  # feature 012: the process's certification authority (certification.py)
    registries.ai_gateway_factory = ai_gateway_factory  # KAP `ai propose` only; lazy (D-08, see the factory)
    return Context(registries=registries, transitions=transitions, versions=versions, layer3=layer3,
                   knowledge=handle, rebuild=_rebuild)


def _rebuild(handle) -> Context:
    return build_context(handle=handle)


def ai_gateway_factory(config: dict):
    """`registries.ai_gateway_factory`: ``(gateway, authorizer)`` for one KAP AI run (feature 011, D-08).

    Lazy: only a command started with ``--ai`` calls it (cli/kap_candidates.py), so building the context never imports
    the gateway or builds a provider. *config* is ``cli/ai_options.AIConfig.to_dict()``. The provider, model and
    endpoint come from the packaged catalog merged with ``catalog_paths``; the credential is read from the environment
    variable name the catalog declares (never printed); the authorizer holds exactly the grants named on the command
    line, after the forbidden and unknown categories are refused. No default grant, no other provider, no fallback.
    Catalog and grant errors are raised as ValueError (the command exits 1 with the message)."""
    from odooflux.ai.authorization import Authorizer, AuthorizationError, parse_grants
    from odooflux.ai.gateway import GatewayConfig, build_gateway
    from odooflux.ai.providers.catalog import CatalogError, load_catalog
    from odooflux.ai.providers.credentials import CredentialError

    try:
        grants = parse_grants([f"{p}={','.join(c)}" for p, c in (config.get("authorizations") or {}).items()])
        catalog = load_catalog(config.get("catalog_paths") or [])
        entry, _ = catalog.resolve(config["provider"], config["model"], config.get("endpoint", ""))
        if entry.adapter == "fake" and not config.get("fake_script"):
            raise ValueError("the fake provider needs a script (ODOOFLUX_AI_FAKE_SCRIPT)")
        gateway = build_gateway(
            GatewayConfig(provider=config["provider"], model=config["model"], endpoint=config.get("endpoint", ""),
                          grants=grants, kill_switch=bool(config.get("kill_switch")),
                          max_retries=int(config.get("max_retries", 2)), timeout_s=float(config.get("timeout_s", 60.0)),
                          secrets_file=config.get("secrets_file", ""), fake_script=config.get("fake_script", "")),
            catalog, environ=os.environ)
    except (AuthorizationError, CatalogError, CredentialError) as exc:
        raise ValueError(str(exc)) from None
    return gateway, Authorizer(grants)


class _HandleRuleBinder(RunRuleBinder):
    """The run-input rule binder of one knowledge handle. For an active release it adds the release's knowledge tree
    to every run's parameters, so rule functions that read a knowledge file (view_refs) receive the release root
    (REQ-KAP-036). With no tree (built-in or no handle) the parameters are unchanged."""

    def __init__(self, rows_loader, modules, tree=None):
        super().__init__(rows_loader, modules)
        self._tree = None if tree is None else str(tree)

    def _params(self, run_params: dict) -> dict:
        return run_params if self._tree is None else {**run_params, "knowledge_root": self._tree}

    def __call__(self, run_params: dict, enabled) -> tuple:
        return super().__call__(self._params(run_params), enabled)

    def for_steps(self, run_params: dict, steps) -> tuple:
        return super().for_steps(self._params(run_params), steps)


class _DeferredContext:
    """The process context, built on first use. A migrate run never builds the default context: it asks for
    `for_knowledge(handle)` with its one handle, so no knowledge reader is constructed without that handle."""

    def __init__(self):
        self.__dict__["_built"] = None

    def _get(self) -> Context:
        if self.__dict__["_built"] is None:
            self.__dict__["_built"] = build_context()
        return self.__dict__["_built"]

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def for_knowledge(self, handle) -> Context:
        return build_context(handle=handle)


def default_context() -> _DeferredContext:
    """The context the console script passes to the CLI (built on first use)."""
    return _DeferredContext()


def _active_rule_rows() -> list:
    """Rule rows of the knowledge release resolved for this process (built-in unless a release is active)."""
    return load_active_knowledge(resolve_knowledge()).rules


def _layer3(path, to_version: int):
    return check_integrity([path], target_version=f"{to_version}.0")


def _layer3_for(tree: Path):
    """L3 integrity reading the core and Enterprise lists of one knowledge tree (REQ-KAP-036, REQ-KAP-042)."""
    def layer3(path, to_version: int):
        return check_integrity([path], target_version=f"{to_version}.0", knowledge_root=tree)
    return layer3


def build_registries() -> Registries:
    return build_context().registries


def main(argv=None) -> int:
    from odooflux.cli.main import run
    argv = sys.argv[1:] if argv is None else list(argv)
    return run(argv, default_context())


if __name__ == "__main__":
    raise SystemExit(main())
