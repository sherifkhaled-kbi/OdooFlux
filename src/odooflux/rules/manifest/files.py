"""Manifest file-reference rules (REQ-MAN-003): listed paths exist, security files load before views.

Only literal string entries are checked. Glob patterns and asset directives such as ``('include', ...)``
are skipped, because they do not name a single file.
"""

import ast
import os

from odooflux.parsers.python import spans as sp
from odooflux.rules.manifest.hygiene import manifest_entries
from odooflux.rules.shared.emit import finding

_GLOB = frozenset("*?[")
_FILE_KEYS = ("data", "demo", "init_xml", "update_xml", "demo_xml")


def _string_items(node):
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _asset_items(node):
    if not isinstance(node, ast.Dict):
        return []
    return [item for value in node.values for item in _string_items(value)]


def flag_missing_data_files(document, ctx, *, root=None):
    """Report ``data``/``demo``/``assets`` paths that do not exist. ``root`` defaults to the manifest directory;
    asset paths are rooted at the addons directory (their first segment is the module name)."""
    parsed, entries = manifest_entries(document)
    if not entries:
        return []
    module_root = root if root is not None else os.path.dirname(document.path) or "."
    addons_root = os.path.dirname(os.path.abspath(module_root))
    items = []
    for key in _FILE_KEYS:
        items += [(node, module_root) for node in _string_items(entries.get(key))]
    items += [(node, addons_root) for node in _asset_items(entries.get("assets"))]
    found = []
    for node, base in items:
        path = node.value
        if not path or _GLOB & set(path):
            continue
        if not os.path.exists(os.path.join(base, path.lstrip("/"))):
            found.append(finding(document, ctx, sp.node_span(parsed, node)))
    return sorted(found, key=lambda f: f.line)


def flag_load_order(document, ctx):
    """Report a ``security/`` data file listed after a ``views/`` file."""
    parsed, entries = manifest_entries(document)
    if not entries:
        return []
    seen_view, found = False, []
    for node in _string_items(entries.get("data")):
        parts = node.value.replace("\\", "/").split("/")
        if "views" in parts[:-1]:
            seen_view = True
        elif "security" in parts[:-1] and seen_view:
            found.append(finding(document, ctx, sp.node_span(parsed, node)))
    return found
