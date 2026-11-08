"""Explicit plugin loading (``--plugin module:attr``). The only module allowed to import dynamically
(TST-003-002 allow-list). Plugins never load automatically (R-03)."""

import importlib
import sys

from odooflux.core.contracts import ContractError
from odooflux.core.contracts.plugins import KINDS


def load_plugins(specs, registries) -> list:
    """Register every entry each spec names. Returns a list of (spec, error) for failures;
    a failing plugin is skipped and loading continues (US4 scenario 2)."""
    failures = []
    for spec in specs:
        module_name, _, attr = spec.partition(":")
        try:
            module = importlib.import_module(module_name)
            obj = getattr(module, attr or "PLUGIN")
            entries = obj if isinstance(obj, (list, tuple)) else [obj]
            for entry in entries:
                if entry.kind not in KINDS:
                    raise ValueError(f"unknown registry kind {entry.kind!r}")
                getattr(registries, entry.kind).register(entry.entry, plugin=spec)
        except (ImportError, AttributeError, ContractError, ValueError, TypeError) as exc:
            failures.append((spec, f"{type(exc).__name__}: {exc}"))
            print(f"WARNING: plugin {spec} not loaded: {exc}", file=sys.stderr)
    return failures
