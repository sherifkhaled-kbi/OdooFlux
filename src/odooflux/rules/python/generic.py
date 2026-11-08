"""Generic Python detectors and fixers bound by rule metadata (REQ-PY-002, REQ-PY-003, REQ-TRF-003).

Each function takes the engine ``Document``, a ``RuleContext`` and keyword parameters from the rule's
``params``. Detectors return ``Finding`` values and never edit. Fixers return ``Edit`` values and are
idempotent: the output of a fixer contains nothing it would match again.

Names are resolved through the module's imports: with ``from odoo import fields as f``, the call ``f.Char``
resolves to ``fields.Char``. The ``odoo.`` and ``openerp.`` prefixes are dropped, so a target ``fields.``
(with a trailing dot) matches every callee under that prefix. A name bound by two different imports is
ambiguous: detectors still report it by its literal spelling, fixers skip it.
"""

import ast
import re

from odooflux.core.engine.documents import Document, Span
from odooflux.parsers.python import document as pydoc
from odooflux.parsers.python import spans as sp
from odooflux.rules.shared.emit import edit, finding
from odooflux.utils.astnodes import nodes_of

VALIDATION = ("python-syntax",)
_ODOO_PREFIXES = ("odoo.", "openerp.")
_DOTTED = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _normalise(name: str) -> str:
    for prefix in _ODOO_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


class Names:
    """Import bindings of one module: local name to qualified name, and the names bound ambiguously."""

    def __init__(self, tree):
        self.bound = {}
        self.ambiguous = set()
        for node in sp.all_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self._bind(alias.asname, alias.name)
                    else:
                        top = alias.name.split(".")[0]
                        self._bind(top, top)
            elif isinstance(node, ast.ImportFrom):
                prefix = "." * node.level + (node.module or "")
                for alias in node.names:
                    if alias.name != "*":
                        self._bind(alias.asname or alias.name,
                                   prefix + alias.name if prefix.endswith(".") else f"{prefix}.{alias.name}")

    def _bind(self, local: str, target: str) -> None:
        if local in self.bound and self.bound[local] != target:
            self.ambiguous.add(local)
        else:
            self.bound.setdefault(local, target)

    def qualify(self, dotted: str):
        """``(qualified name, certain)``. ``certain`` is False when the head name is ambiguous."""
        head, dot, rest = dotted.partition(".")
        if head in self.bound:
            full = self.bound[head] + (dot + rest if dot else "")
        else:
            full = dotted
        return _normalise(full), head not in self.ambiguous


def _matches(qualified: str, target: str) -> bool:
    target = _normalise(target)
    return qualified.startswith(target) if target.endswith(".") else qualified == target


_NAMES: list = [None, None]  # [parsed document, its Names]: every rule of a run reads the same file in turn


def _load(document: Document):
    parsed = pydoc.parse_document(document)
    if parsed.tree is None:
        return None, None
    if _NAMES[0] is not parsed:
        _NAMES[:] = [parsed, Names(parsed.tree)]
    return parsed, _NAMES[1]


def _walk(tree, types):
    return nodes_of(tree, types)


def _calls(tree, names, callee):
    """``(Call, certain)`` for every call whose callee matches."""
    hits = []
    for node in _walk(tree, ast.Call):
        dotted = sp.dotted_name(node.func)
        if dotted is not None:
            qualified, certain = names.qualify(dotted)
            if _matches(qualified, callee):
                hits.append((node, certain))
    return hits


def _decorators(tree, names, target):
    """``(decorator expression, certain)`` for every decorator whose callee matches."""
    hits = []
    for node in _walk(tree, (*_DEF_NODES, ast.ClassDef)):
        for dec in node.decorator_list:
            dotted = sp.dotted_name(dec.func if isinstance(dec, ast.Call) else dec)
            if dotted is not None:
                qualified, certain = names.qualify(dotted)
                if _matches(qualified, target):
                    hits.append((dec, certain))
    return hits


def _attributes(tree, names, target):
    """``(Attribute, certain, is_load)`` for every attribute chain that matches."""
    hits = []
    for node in _walk(tree, ast.Attribute):
        dotted = sp.dotted_name(node)
        if dotted is not None:
            qualified, certain = names.qualify(dotted)
            if _matches(qualified, target):
                hits.append((node, certain, isinstance(node.ctx, ast.Load)))
    return hits


def _findings(document, ctx, parsed, nodes_or_spans):
    spans = [item if not isinstance(item, ast.AST) else sp.node_span(parsed, item) for item in nodes_or_spans]
    return [finding(document, ctx, span) for span in sorted(spans, key=lambda s: (s.start, s.end))]


def _edits(document, ctx, pairs, *, op):
    """``pairs`` are ``(Span, after)``; edits come back in document order."""
    return [edit(document, ctx, span, after, op=op, validation=VALIDATION)
            for span, after in sorted(pairs, key=lambda p: (p[0].start, p[0].end))]


def _check_dotted(name: str) -> None:
    if not _DOTTED.match(name):
        raise ValueError(f"not a dotted name: {name!r}")


def _check_identifier(name: str) -> None:
    if not name.isidentifier():
        raise ValueError(f"not an identifier: {name!r}")


# ---- keyword arguments -------------------------------------------------------------------------


def keyword_in_call(document, ctx, *, callee, keyword):
    """Detect keyword argument ``keyword`` in calls to ``callee``."""
    parsed, names = _load(document)
    if parsed is None:
        return []
    nodes = [kw for call, _ in _calls(parsed.tree, names, callee) for kw in sp.keywords_named(call, keyword)]
    return _findings(document, ctx, parsed, nodes)


def rename_keyword(document, ctx, *, callee, keyword, new_keyword):
    """Rename keyword argument ``keyword`` of calls to ``callee`` to ``new_keyword``. Ambiguous callees are skipped."""
    _check_identifier(new_keyword)
    parsed, names = _load(document)
    if parsed is None:
        return []
    pairs = [(sp.keyword_rename_span(parsed, kw), new_keyword)
             for call, certain in _calls(parsed.tree, names, callee) if certain
             for kw in sp.keywords_named(call, keyword)]
    return _edits(document, ctx, pairs, op="rename_keyword")


def remove_keyword(document, ctx, *, callee, keyword):
    """Remove keyword argument ``keyword`` from calls to ``callee``. Ambiguous callees are skipped."""
    parsed, names = _load(document)
    if parsed is None:
        return []
    pairs = [(sp.keyword_removal_span(parsed, call, kw), "")
             for call, certain in _calls(parsed.tree, names, callee) if certain
             for kw in sp.keywords_named(call, keyword)]
    return _edits(document, ctx, pairs, op="remove_keyword")


# ---- calls, decorators, definitions ------------------------------------------------------------


def flag_call(document, ctx, *, callee):
    """Detect every call to ``callee``."""
    parsed, names = _load(document)
    if parsed is None:
        return []
    return _findings(document, ctx, parsed, [call for call, _ in _calls(parsed.tree, names, callee)])


def flag_decorator(document, ctx, *, decorator):
    """Detect every decorator whose callee is ``decorator``."""
    parsed, names = _load(document)
    if parsed is None:
        return []
    return _findings(document, ctx, parsed, [dec for dec, _ in _decorators(parsed.tree, names, decorator)])


def remove_decorator(document, ctx, *, decorator):
    """Remove every decorator line whose callee is ``decorator``. Ambiguous callees are skipped."""
    parsed, names = _load(document)
    if parsed is None:
        return []
    pairs = [(sp.decorator_removal_span(parsed, dec), "")
             for dec, certain in _decorators(parsed.tree, names, decorator) if certain]
    return _edits(document, ctx, pairs, op="remove_decorator")


def flag_method_override(document, ctx, *, method):
    """Detect a method named ``method`` defined directly in a class body."""
    parsed, _ = _load(document)
    if parsed is None:
        return []
    spans = [sp.line_span(parsed, stmt.lineno, include_newline=False)
             for cls in _walk(parsed.tree, ast.ClassDef) for stmt in cls.body
             if isinstance(stmt, _DEF_NODES) and stmt.name == method]
    return _findings(document, ctx, parsed, spans)


def flag_class_attribute(document, ctx, *, attribute):
    """Detect a class-body assignment (plain or annotated) to ``attribute``."""
    parsed, _ = _load(document)
    if parsed is None:
        return []
    nodes = []
    for cls in _walk(parsed.tree, ast.ClassDef):
        for stmt in cls.body:
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            else:
                continue
            if any(isinstance(t, ast.Name) and t.id == attribute for t in targets):
                nodes.append(stmt)
    return _findings(document, ctx, parsed, nodes)


# ---- attribute chains --------------------------------------------------------------------------


def flag_attribute_access(document, ctx, *, old):
    """Detect every read or write of the dotted attribute chain ``old``."""
    parsed, names = _load(document)
    if parsed is None:
        return []
    return _findings(document, ctx, parsed, [node for node, _, _ in _attributes(parsed.tree, names, old)])


def rewrite_attribute_access(document, ctx, *, old, new):
    """Rewrite every read of the dotted attribute chain ``old`` to ``new``. Writes and ambiguous names are skipped."""
    _check_dotted(new)
    parsed, names = _load(document)
    if parsed is None:
        return []
    pairs = [(sp.node_span(parsed, node), new)
             for node, certain, is_load in _attributes(parsed.tree, names, old) if certain and is_load]
    return _edits(document, ctx, pairs, op="rewrite_attribute_access")


def flag_method_call(document, ctx, *, method):
    """Detect every call ``<receiver>.<method>(...)`` whatever the receiver. The finding sits on the callee."""
    parsed, _ = _load(document)
    if parsed is None:
        return []
    callees = [call.func for call in _walk(parsed.tree, ast.Call)
               if isinstance(call.func, ast.Attribute) and call.func.attr == method]
    return _findings(document, ctx, parsed, callees)


# ---- literal values and attribute maps ---------------------------------------------------------

_VALUE = re.compile(r"^[A-Za-z0-9_.\-]*$")


def _is_str_literal(node, value: str) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == value


def _plain_literal_span(parsed, node):
    """Span of a string literal whose source is exactly its quote, its value and its quote (no prefix, escapes or
    implicit concatenation). None otherwise, so only literals that can be rewritten are rewritten."""
    span = sp.node_span(parsed, node)
    raw = parsed.text[span.start:span.end]
    quote = raw[:1]
    if quote in ("'", '"') and raw == quote + node.value + quote:
        return span
    return None


def flag_keyword_value(document, ctx, *, callee, keyword, value):
    """Detect keyword argument ``keyword`` of calls to ``callee`` whose value is the string ``value``."""
    parsed, names = _load(document)
    if parsed is None:
        return []
    nodes = [kw.value for call, _ in _calls(parsed.tree, names, callee) for kw in sp.keywords_named(call, keyword)
             if _is_str_literal(kw.value, value)]
    return _findings(document, ctx, parsed, nodes)


def rewrite_keyword_value(document, ctx, *, callee, keyword, value, new_value):
    """Rewrite the plain string literal ``value`` of keyword ``keyword`` of calls to ``callee`` to ``new_value``,
    keeping its quotes. Ambiguous callees are skipped."""
    if not _VALUE.match(new_value):
        raise ValueError(f"not a plain value: {new_value!r}")
    parsed, names = _load(document)
    if parsed is None:
        return []
    pairs = []
    for call, certain in _calls(parsed.tree, names, callee):
        if not certain:
            continue
        for kw in sp.keywords_named(call, keyword):
            span = _plain_literal_span(parsed, kw.value) if _is_str_literal(kw.value, value) else None
            if span is not None:
                quote = parsed.text[span.start]
                pairs.append((span, f"{quote}{new_value}{quote}"))
    return _edits(document, ctx, pairs, op="rewrite_keyword_value")


def flag_attribute_map(document, ctx, *, mapping):
    """Detect every read or write of each dotted attribute chain that is a key of ``mapping``."""
    parsed, names = _load(document)
    if parsed is None:
        return []
    nodes = [node for old in sorted(mapping) for node, _, _ in _attributes(parsed.tree, names, old)]
    return _findings(document, ctx, parsed, nodes)


def rewrite_attribute_map(document, ctx, *, mapping):
    """Rewrite every read of each dotted attribute chain that is a key of ``mapping`` to its value. Writes and
    ambiguous names are skipped (they need review)."""
    for new in mapping.values():
        _check_dotted(new)
    parsed, names = _load(document)
    if parsed is None:
        return []
    pairs = [(sp.node_span(parsed, node), new)
             for old, new in sorted(mapping.items())
             for node, certain, is_load in _attributes(parsed.tree, names, old) if certain and is_load]
    return _edits(document, ctx, pairs, op="rewrite_attribute_map")


def _module_hit(qualified: str, target: str) -> bool:
    """True when ``qualified`` (normalised) is ``target`` (normalised) or one of its submodules."""
    target = _normalise(target)
    return qualified == target or qualified.startswith(target + ".")


def flag_import(document, ctx, *, module):
    """Detect an absolute import of ``module`` or a submodule: ``import m``, ``from m import x``, and
    ``from <package> import <m's last part>`` (for example ``from odoo import osv``). The finding is the statement."""
    parsed, _ = _load(document)
    if parsed is None:
        return []
    hits = []
    for node in _walk(parsed.tree, (ast.Import, ast.ImportFrom)):
        if isinstance(node, ast.Import):
            matched = any(_module_hit(_normalise(alias.name), module) for alias in node.names)
        elif node.level == 0 and node.module:
            matched = _module_hit(_normalise(node.module), module) or any(
                _module_hit(_normalise(f"{node.module}.{alias.name}"), module) for alias in node.names)
        else:
            matched = False
        if matched:
            hits.append(node)
    return _findings(document, ctx, parsed, hits)


# ---- receiver-agnostic method calls (feature 006, migration steps) ----------------------------


def _method_calls(tree, methods):
    """Every call ``<receiver>.<method>(...)`` whose method name is in ``methods``, whatever the receiver."""
    return [call for call in _walk(tree, ast.Call)
            if isinstance(call.func, ast.Attribute) and call.func.attr in methods]


def flag_method_keyword(document, ctx, *, method, keyword):
    """Detect keyword argument ``keyword`` in calls ``<receiver>.<method>(...)``, whatever the receiver."""
    parsed, _ = _load(document)
    if parsed is None:
        return []
    nodes = [kw for call in _method_calls(parsed.tree, (method,)) for kw in sp.keywords_named(call, keyword)]
    return _findings(document, ctx, parsed, nodes)


def rename_method_keyword(document, ctx, *, method, keyword, new_keyword):
    """Rename keyword argument ``keyword`` of calls ``<receiver>.<method>(...)`` to ``new_keyword``."""
    _check_identifier(new_keyword)
    parsed, _ = _load(document)
    if parsed is None:
        return []
    pairs = [(sp.keyword_rename_span(parsed, kw), new_keyword)
             for call in _method_calls(parsed.tree, (method,)) for kw in sp.keywords_named(call, keyword)]
    return _edits(document, ctx, pairs, op="rename_method_keyword")


def flag_method_calls(document, ctx, *, methods):
    """Detect calls ``<receiver>.<method>(...)`` for each method in ``methods``. The finding sits on the callee."""
    parsed, _ = _load(document)
    if parsed is None:
        return []
    return _findings(document, ctx, parsed, [call.func for call in _method_calls(parsed.tree, tuple(methods))])


def _is_str_ids(node) -> bool:
    """A string literal, or a list/tuple literal holding one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    return isinstance(node, (ast.List, ast.Tuple)) and any(_is_str_ids(item) for item in node.elts)


def flag_method_call_str_argument(document, ctx, *, method):
    """Detect ``<receiver>.<method>(...)`` whose first argument is a string id or a list holding one (``browse``
    rejects string ids in the newer version). The finding sits on the callee."""
    parsed, _ = _load(document)
    if parsed is None:
        return []
    callees = [call.func for call in _method_calls(parsed.tree, (method,)) if call.args and _is_str_ids(call.args[0])]
    return _findings(document, ctx, parsed, callees)


def _non_bool_argument(call) -> bool:
    if any(kw.arg == "user" for kw in call.keywords):
        return True
    if not call.args:
        return False
    first = call.args[0]
    return not (isinstance(first, ast.Constant) and isinstance(first.value, bool))


def flag_method_non_bool_argument(document, ctx, *, method):
    """Detect ``<receiver>.<method>(...)`` whose first argument is not a boolean literal, or that passes ``user=``.
    The ``sudo(flag)`` form takes a boolean; the ``sudo(user)`` form does not translate (EV-349). A call with
    no argument or a boolean literal is not reported."""
    parsed, _ = _load(document)
    if parsed is None:
        return []
    callees = [call.func for call in _method_calls(parsed.tree, (method,)) if _non_bool_argument(call)]
    return _findings(document, ctx, parsed, callees)


# ---- dotted names (imports, bare loads, attribute chains) -------------------------------------


def _bare_name_hits(tree, names, qualified):
    """``(Name, certain)`` for every load of a bare name whose binding qualifies to ``qualified``."""
    hits = []
    for node in _walk(tree, ast.Name):
        if isinstance(node.ctx, ast.Load):
            resolved, certain = names.qualify(node.id)
            if _matches(resolved, qualified):
                hits.append((node, certain))
    return hits


def _import_hits(tree, qualified):
    """``(ImportFrom, alias)`` for every absolute ``from m import x`` whose ``m.x`` is ``qualified``."""
    hits = []
    for node in _walk(tree, ast.ImportFrom):
        if node.level == 0 and node.module:
            for alias in node.names:
                if alias.name != "*" and _matches(_normalise(f"{node.module}.{alias.name}"), qualified):
                    hits.append((node, alias))
    return hits


def _alias_span(parsed, stmt, name: str) -> Span:
    """Span of the imported ``name`` inside an ``ImportFrom`` statement (the first whole-word match after ``import``)."""
    span = sp.node_span(parsed, stmt)
    text = parsed.text[span.start:span.end]
    keyword = re.search(r"\bimport\b", text)
    match = re.compile(rf"\b{re.escape(name)}\b").search(text, keyword.end())
    return Span(span.start + match.start(), span.start + match.end())


def flag_name(document, ctx, *, qualified):
    """Detect every reference to ``qualified`` (a dotted name such as ``odoo.tests.common.SavepointCase``): the import
    statement that brings it in, every load of a bare name bound to it, and every attribute chain that resolves to it."""
    parsed, names = _load(document)
    if parsed is None:
        return []
    statements = list(dict.fromkeys(stmt for stmt, _ in _import_hits(parsed.tree, qualified)))
    nodes = statements + [node for node, _ in _bare_name_hits(parsed.tree, names, qualified)]
    nodes += [node for node, _, _ in _attributes(parsed.tree, names, qualified)]
    return _findings(document, ctx, parsed, nodes)


def rename_name(document, ctx, *, qualified, new_name):
    """Rename the last component of ``qualified`` to ``new_name`` at its import, at each bare load bound to it, and in
    each attribute chain that resolves to it. An alias keeps its local name. The file is left unchanged when a
    reference is ambiguous, is written (not loaded), or sits in an ``except`` clause: those need review, and renaming
    only part of them would break the module."""
    _check_identifier(new_name)
    parsed, names = _load(document)
    if parsed is None:
        return []
    last = _normalise(qualified).rsplit(".", 1)[-1]
    bare = _bare_name_hits(parsed.tree, names, qualified)
    chains = [(node, certain, is_load) for node, certain, is_load in _attributes(parsed.tree, names, qualified)]
    in_except = {id(sub) for handler in _walk(parsed.tree, ast.ExceptHandler) if handler.type is not None
                 for sub in ast.walk(handler.type)}
    if (any(not certain for _, certain in bare) or any(not certain or not is_load for _, certain, is_load in chains)
            or any(id(node) in in_except for node, _ in bare)
            or any(id(node) in in_except for node, _, _ in chains)):
        return []
    pairs = [(sp.node_span(parsed, node), new_name) for node, _ in bare if node.id == last]
    pairs += [(_alias_span(parsed, stmt, last), new_name) for stmt, alias in _import_hits(parsed.tree, qualified)
              if alias.name == last]
    for node, _, _ in chains:
        span = sp.node_span(parsed, node)
        if parsed.text[span.start:span.end].endswith(last):
            pairs.append((Span(span.end - len(last), span.end), new_name))
    return _edits(document, ctx, pairs, op="rename_name")
