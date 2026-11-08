"""View reference stability rules (FR-021): ``inherit_id`` refs and xpath named anchors against a version index.

Both detectors are DETECT_ONLY and never edit. Per run they take ``target`` (the target series, a run parameter: without a run context the binding skips the
rule with an INFO gap) and may take
``index`` (a ``ViewIndex``; loaded for ``target`` when absent) and ``scanned_modules`` (modules being migrated,
whose views are checked by the dependency integrity pass instead).

Outcomes per reference:
- core module of the target and the id/anchor is absent from the index: a finding with the rule severity;
- present: nothing;
- non-core module, or no index for the target: an INFO finding worded 'unverifiable'. An unavailable index is
  never proof of compatibility (ADR-018 D-A7);
- unprefixed (same-module) refs and scanned modules: nothing.
"""

import re
from dataclasses import replace

from odooflux.knowledge.view_index import load_view_index
from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.shared.emit import finding

_ANCHOR = re.compile(r"""@(?:name|id)\s*=\s*(['"])(.*?)\1""")
_REF_CALL = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")


def _parse(document):
    xdoc = xmldoc.parse(document)
    return None if xdoc.parse_error is not None else xdoc


def _setup(target, index):
    """The index to check against: the given one, else the shipped index for ``target``, else None."""
    return index if index is not None else load_view_index(target)


def _detail(ctx, text):
    return replace(ctx, message=f"{ctx.message} {text}".strip())


def _info(ctx, text):
    return replace(ctx, severity="INFO", message=f"Unverifiable: {text}")


def _reason(index, target, module):
    if index is None:
        return f"index unavailable for {target!r}, so this reference cannot be checked"
    return f"module {module!r} is not a core module of {index.version}, so this reference cannot be checked"


def _views(xdoc):
    """(view element, inherit_id attr element-or-None, ref text, ref span) for each view that inherits."""
    out = []
    for el in xdoc.elements:
        if el.tag == "template":
            attr = el.get_attr("inherit_id")
            if attr is not None:
                out.append((el, attr.value, attr.span))
        elif el.tag == "record" and getattr(el.get_attr("model"), "value", None) == "ir.ui.view":
            for child in (xdoc.elements[i] for i in el.children_index):
                if child.tag != "field" or getattr(child.get_attr("name"), "value", None) != "inherit_id":
                    continue
                ref = child.get_attr("ref")
                if ref is not None:
                    out.append((el, ref.value, ref.span))
                else:
                    ev = child.get_attr("eval")
                    hit = _REF_CALL.search(ev.value) if ev is not None else None
                    if hit:
                        out.append((el, hit.group(1), ev.span))
    return out


def _expr_anchor_groups(expr):
    """Anchor alternatives per xpath predicate: ``[@name='a' or @name='b']`` is one group (either satisfies it);
    each other anchor is a group of one."""
    groups = []
    for predicate in re.findall(r"\[([^\]]*)\]", expr):
        names = tuple(m.group(2) for m in _ANCHOR.finditer(predicate))
        if names and " or " in predicate:
            groups.append(names)
        else:
            groups += [(n,) for n in names]
    return groups


def _checkable(name):
    """Button names of the form ``%(module.action)d`` are action xml ids that the parent may write unqualified,
    so their text is not comparable; they are not treated as anchors."""
    return "%(" not in name


def _skip(ref, scanned):
    module, dot, _ = ref.partition(".")
    return not dot or module in (scanned or ())


def flag_inherit_id_missing(document, ctx, *, target, index=None, scanned_modules=None):
    """Detect ``inherit_id`` refs to core views that are absent from the target version's index."""
    index = _setup(target, index)
    xdoc = _parse(document)
    if xdoc is None:
        return []
    out = []
    for _, ref, span in _views(xdoc):
        if _skip(ref, scanned_modules):
            continue
        module = ref.partition(".")[0]
        if index is not None and index.has_module(module):
            if not index.has_view(ref):
                out.append(finding(document, _detail(ctx, f"Missing: view {ref!r}."), span))
        else:
            out.append(finding(document, _info(ctx, f"inherit_id {ref!r}: " + _reason(index, target, module)), span))
    return out


def _anchors(xdoc, view):
    """(anchor value, span) for each xpath/shorthand reference made directly by the view's arch."""
    found = []
    root_elements = [xdoc.elements[i] for i in view.children_index] if view.tag == "template" else [
        xdoc.elements[j] for i in view.children_index if xdoc.elements[i].tag == "field"
        and getattr(xdoc.elements[i].get_attr("name"), "value", None) == "arch"
        for j in xdoc.elements[i].children_index]
    pending = list(root_elements)
    while pending:
        el = pending.pop(0)
        if el.get_attr("position") is not None or el.tag == "xpath":
            if el.tag == "xpath":
                expr = el.get_attr("expr")
                if expr is not None:
                    found += [(names, expr.span) for names in _expr_anchor_groups(expr.value)]
            elif el.get_attr("name") is not None:
                found.append(((el.get_attr("name").value,), el.get_attr("name").span))
            elif el.get_attr("id") is not None:
                found.append(((el.get_attr("id").value,), el.get_attr("id").span))
        elif el.tag in ("data",):
            pending += [xdoc.elements[i] for i in el.children_index]
    return [(names, span) for names, span in found if all(_checkable(n) for n in names)]


def _show(names):
    return " or ".join(repr(n) for n in names)


def flag_xpath_anchor_missing(document, ctx, *, target, index=None, scanned_modules=None):
    """Detect xpath/shorthand named anchors (``@name``, ``@id``) that no core view of the parent's tree defines."""
    index = _setup(target, index)
    xdoc = _parse(document)
    if xdoc is None:
        return []
    out = []
    for view, ref, _ in _views(xdoc):
        if _skip(ref, scanned_modules):
            continue
        module = ref.partition(".")[0]
        known = index is not None and index.has_module(module)
        if known and not index.has_view(ref):
            continue                      # the inherit-id rule reports the missing parent
        anchors = _anchors(xdoc, view)
        if known:
            present = index.anchors_for(ref)
            out += [finding(document, _detail(ctx, f"Missing: anchor {_show(names)} in the tree of {ref!r}."), span)
                    for names, span in anchors if not (set(names) & present)]
        else:
            why = _reason(index, target, module)
            out += [finding(document, _info(ctx, f"anchor {_show(names)} in view inheriting {ref!r}: " + why), span)
                    for names, span in anchors]
    return out
