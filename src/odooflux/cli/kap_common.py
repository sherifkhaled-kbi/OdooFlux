"""Shared wiring for the knowledge acquisition command groups (REQ-KAP-005, REQ-KAP-001; contracts/cli-surface.md).

`register_all(sub)` calls `register(subparsers)` on each group module in the static list below. Adding a group
means adding its import there (no dynamic discovery: the security guard forbids importlib outside cli/plugins.py).
Each group sets its handler with `set_defaults(kap_handler=...)`; `cli/knowledge.py` dispatches on that attribute.

Exit codes: usage errors reuse `cli/exit_codes.USAGE` (2). The package and release codes below are local to the
knowledge groups. Their numbers collide with the reporting policy in `cli/exit_codes.py` (3 REJECTED edits, 4 BLOCKED)
because the two policies never meet in one command. This module does not change `exit_codes.py`.
"""

from odooflux.cli.exit_codes import USAGE

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_PACKAGE_REJECTED = 3
EXIT_SOURCE_UNAVAILABLE = 4
EXIT_INTEGRITY = 5
EXIT_USAGE = USAGE

def attached(args, name: str):
    """The object the composition root attached to the registries (`registries.<name>`), or None when this run
    has none. `cli/knowledge.main` puts the registries on the parsed args for the KAP groups only."""
    return getattr(getattr(args, "registries", None), name, None)


def register_all(sub, modules=None) -> list:
    """Register every KAP group on the subparsers `sub`. Returns the registered group names (module names).

    `modules` overrides the static list with already-imported group modules (used by tests). Each module must expose
    `register(subparsers)`. The imports are explicit here, not discovered: a group module that fails to import raises,
    so a broken group is never silently dropped. `kap_candidates` joins this list when its module exists."""
    if modules is None:
        from odooflux.cli import (kap_candidates, kap_coverage, kap_extract, kap_package, kap_release, kap_rule,
                                  kap_source, kap_update)
        modules = (kap_candidates, kap_coverage, kap_extract, kap_package, kap_release, kap_rule, kap_source,
                   kap_update)
    registered = []
    for module in modules:
        module.register(sub)
        registered.append(module.__name__.rsplit(".", 1)[-1])
    return registered
