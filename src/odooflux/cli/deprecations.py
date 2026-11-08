"""CLI deprecations with a removal point (D-10; REQ-AI-008, FR-008).

``--api-key`` leaks through shell history and process lists. It warns while the D-10 window is open and is rejected
from ``API_KEY_REMOVED_IN`` onward. The window is "one minor release" (feature 010 assumptions); the project owner has
not recorded the decision, so the removal point is a single constant, tested with a simulated version. Shipping the
removal means bumping ``odooflux.__version__`` to this value, an owner action recorded in the review register."""

import odooflux

API_KEY_REMOVED_IN = "0.3.0"
API_KEY_REMOVED_MESSAGE = ("ERROR: --api-key was removed in OdooFlux {removed} (decision D-10): a key on the command "
                           "line leaks through shell history and process lists. Set ANTHROPIC_API_KEY, or use "
                           "--ai-secrets-file with --ai.")
_OPTION = "--api-key"


def _version_tuple(version: str) -> tuple:
    parts = []
    for piece in str(version).split(".")[:3]:
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))


def api_key_removed(version: str = None) -> bool:
    version = odooflux.__version__ if version is None else version
    return _version_tuple(version) >= _version_tuple(API_KEY_REMOVED_IN)


def names_api_key(token: str) -> bool:
    """True for ``--api-key``, ``--api-key=VALUE`` and the unique prefixes argparse would accept (``--api-k``)."""
    name = token.split("=", 1)[0]
    return name.startswith("--ap") and _OPTION.startswith(name)


def secret_values(argv) -> list:
    """The values given to ``--api-key`` (either form), so error text can be scrubbed of them."""
    values, tokens = [], list(argv)
    for i, token in enumerate(tokens):
        if names_api_key(token):
            if "=" in token:
                values.append(token.split("=", 1)[1])
            elif i + 1 < len(tokens):
                values.append(tokens[i + 1])
    return [v for v in values if v]
