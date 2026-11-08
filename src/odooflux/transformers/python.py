"""Python edit helpers (REQ-PY-001, REQ-TRF-003).

Each helper locates targets with ``parsers.python.spans`` and returns ``Edit`` values for
``core.engine.edits.apply_edits``. Nothing is mutated. A document without a tree yields no edits.
"""


from odooflux.core.engine.edits import Edit
from odooflux.parsers.python import spans as sp

DEFAULT_SEVERITY = "WARNING"
DEFAULT_STEP = "python-fix"
VALIDATION = ("python-syntax",)


def _edit(doc, span, after, *, op, rule_id, severity, step):
    return Edit(
        id=f"{rule_id}:{op}:{span.start}-{span.end}", rule_id=rule_id, path=doc.path,
        start=span.start, end=span.end, before=doc.text[span.start:span.end], after=after,
        severity=severity, step=step, validation=VALIDATION)


def remove_decorator(doc, name, *, rule_id, severity=DEFAULT_SEVERITY, step=DEFAULT_STEP):
    """Remove every decorator line whose callee is ``name`` (e.g. ``api.multi``)."""
    if doc.tree is None:
        return []
    return [_edit(doc, sp.decorator_removal_span(doc, dec), "", op="remove_decorator",
                  rule_id=rule_id, severity=severity, step=step)
            for dec in sp.decorators_named(doc, name)]


def _keyword_pairs(doc, call_name, keyword):
    return [(call, kw) for call in sp.calls_named(doc, call_name) for kw in sp.keywords_named(call, keyword)]


def remove_keyword(doc, call_name, keyword, *, rule_id, severity=DEFAULT_SEVERITY, step=DEFAULT_STEP):
    """Remove keyword argument ``keyword`` from every call to ``call_name`` (F-PY-2: comma-aware)."""
    if doc.tree is None:
        return []
    return [_edit(doc, sp.keyword_removal_span(doc, call, kw), "", op="remove_keyword",
                  rule_id=rule_id, severity=severity, step=step)
            for call, kw in _keyword_pairs(doc, call_name, keyword)]


def rename_keyword(doc, call_name, keyword, new_name, *, rule_id, severity=DEFAULT_SEVERITY, step=DEFAULT_STEP):
    """Rename keyword argument ``keyword`` of calls to ``call_name`` to ``new_name``."""
    if not new_name.isidentifier():
        raise ValueError(f"not an identifier: {new_name!r}")
    if doc.tree is None:
        return []
    return [_edit(doc, sp.keyword_rename_span(doc, kw), new_name, op="rename_keyword",
                  rule_id=rule_id, severity=severity, step=step)
            for _, kw in _keyword_pairs(doc, call_name, keyword)]


def replace_call_name(doc, old, new, *, rule_id, severity=DEFAULT_SEVERITY, step=DEFAULT_STEP):
    """Replace the dotted callee ``old`` with ``new`` in every call (string literals are not code)."""
    if doc.tree is None:
        return []
    return [_edit(doc, sp.node_span(doc, call.func), new, op="replace_call_name",
                  rule_id=rule_id, severity=severity, step=step)
            for call in sp.calls_named(doc, old)]


def replace_attribute(doc, old, new, *, rule_id, severity=DEFAULT_SEVERITY, step=DEFAULT_STEP):
    """Replace the dotted attribute chain ``old`` with ``new`` wherever it is read."""
    if doc.tree is None:
        return []
    return [_edit(doc, sp.node_span(doc, node), new, op="replace_attribute",
                  rule_id=rule_id, severity=severity, step=step)
            for node in sp.attributes_named(doc, old)]
