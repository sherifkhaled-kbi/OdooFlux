"""Bound fixers and detectors for import-resolved symbol changes (feature 012, addendum F3.7).

Rules bind these by ``odooflux.rules.python.certified:<name>`` (``rules.bindable.BINDABLE_MODULES``). The fixers
``rewrite_imported_symbol`` and ``remove_imported_decorator`` are the functions that automated certification runs
(``transformers.certify_exec``), so the certified code is the executed code. Detectors never edit. The planning is pure
and lives in ``odooflux.transformers.imported`` (it parses text only; no customer code is imported or executed).
"""

import keyword
import re

from odooflux.parsers.python import document as pydoc
from odooflux.rules.shared.emit import finding
from odooflux.transformers import imported as imp

_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def _check(module: str, *names: str) -> None:
    if not isinstance(module, str) or not _DOTTED.fullmatch(module) \
            or any(keyword.iskeyword(part) for part in module.split(".")):
        raise ValueError(f"not a dotted module name: {module!r}")
    for name in names:
        if not isinstance(name, str) or not name.isidentifier() or keyword.iskeyword(name):
            raise ValueError(f"not an identifier: {name!r}")


def flag_imported_symbol(document, ctx, *, module, old):
    """Detect references to ``module.old`` resolved through the file's own top-level imports."""
    _check(module, old)
    parsed = pydoc.parse_document(document)
    return [finding(document, ctx, span) for span in imp.imported_symbol_spans(parsed, module, old)]


def rewrite_imported_symbol(document, ctx, *, module, old, new):
    """Rewrite ``module.old`` to ``module.new`` where it resolves through the file's top-level imports (fixer)."""
    _check(module, old, new)
    if old == new:
        raise ValueError("old and new must differ")
    parsed = pydoc.parse_document(document)
    return imp.rewrite_imported_symbol_edits(parsed, module, old, new, rule_id=ctx.rule_id,
                                             severity=ctx.severity, step=ctx.step)


def flag_imported_decorator(document, ctx, *, module, name):
    """Detect bare decorators ``@name`` / ``@alias.name`` resolving to ``module.name``."""
    _check(module, name)
    parsed = pydoc.parse_document(document)
    return [finding(document, ctx, span) for span in imp.imported_decorator_spans(parsed, module, name)]


def remove_imported_decorator(document, ctx, *, module, name):
    """Remove the bare decorators resolving to ``module.name`` (fixer). Call decorators are never removed."""
    _check(module, name)
    parsed = pydoc.parse_document(document)
    return imp.remove_imported_decorator_edits(parsed, module, name, rule_id=ctx.rule_id,
                                               severity=ctx.severity, step=ctx.step)
