"""Shared manifest hygiene rules (REQ-MAN-002, REQ-MAN-003).

A manifest is a literal Python dict. These functions read it with ``ast`` (never executed, FR-019) and report
spans of the offending value. ``fix_version_prefix`` is the only fixer: it rewrites the series prefix of the
``version`` string and keeps its suffix and quote style.
"""

import ast
import re

from odooflux.core.engine.documents import Span
from odooflux.parsers.python import document as pydoc
from odooflux.parsers.python import spans as sp
from odooflux.rules.shared.emit import edit, finding

MANIFEST_VALIDATION = ("python-syntax",)
_TARGET = re.compile(r"\d+\.0")
_VERSION = re.compile(r"^(\d+\.\d+)(.*)$", re.S)


def manifest_entries(document):
    """``(parsed document, {key: value node})`` for a literal-dict manifest, or ``(parsed, None)``."""
    parsed = pydoc.parse_document(document)
    if parsed.tree is None or len(parsed.tree.body) != 1 or not isinstance(parsed.tree.body[0], ast.Expr):
        return parsed, None
    node = parsed.tree.body[0].value
    if not isinstance(node, ast.Dict):
        return parsed, None
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return parsed, None
    entries = {key.value: value for key, value in zip(node.keys, node.values)
               if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return parsed, entries


def flag_parse_error(document, ctx):
    """Report a manifest that is not a literal dict (not parseable by ``ast.literal_eval``)."""
    parsed, entries = manifest_entries(document)
    if entries is not None:
        return []
    line = parsed.parse_error["line"] if parsed.parse_error else 1
    offset = document.offset(line, 0) if line >= 1 else 0
    return [finding(document, ctx, Span(offset, offset))]


def _version_node(document, target):
    if not isinstance(target, str) or not _TARGET.fullmatch(target):
        raise ValueError(f"target must look like M.0, got {target!r}")
    parsed, entries = manifest_entries(document)
    node = (entries or {}).get("version")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return parsed, node
    return parsed, None


def flag_version_prefix(document, ctx, *, target):
    """Report a ``version`` whose ``M.0`` prefix is not ``target``. Versions without a numeric prefix are skipped."""
    parsed, node = _version_node(document, target)
    if node is None:
        return []
    match = _VERSION.match(node.value)
    if match is None or match.group(1) == target:
        return []
    return [finding(document, ctx, sp.node_span(parsed, node))]


def fix_version_prefix(document, ctx, *, target):
    """Replace the series prefix with ``target``; the suffix (``.1.2.3``) and the quote style are kept."""
    parsed, node = _version_node(document, target)
    if node is None:
        return []
    match = _VERSION.match(node.value)
    if match is None or match.group(1) == target:
        return []
    span = sp.node_span(parsed, node)
    literal = document.text[span.start:span.end]
    prefix_at = literal.find(match.group(1))
    if prefix_at < 0:
        return []
    after = literal[:prefix_at] + target + literal[prefix_at + len(match.group(1)):]
    return [edit(document, ctx, span, after, op="version_prefix", validation=MANIFEST_VALIDATION)]


def flag_not_installable(document, ctx):
    """Report ``'installable': False``."""
    parsed, entries = manifest_entries(document)
    node = (entries or {}).get("installable")
    if isinstance(node, ast.Constant) and node.value is False:
        return [finding(document, ctx, sp.node_span(parsed, node))]
    return []
