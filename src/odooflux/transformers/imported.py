"""Import-resolved symbol rewrite and decorator removal (feature 012, addendum F1 call-site rule and F3.7).

Non-core and pure: this module parses the text it is given and returns ``Edit`` values. It never imports, executes or
reads customer code. The fixers in ``odooflux.rules.python.certified`` call these functions, and the certification
executor runs the same bound fixers, so the certified code is the executed code.

A name resolves to a qualified name ONLY through a top-level ``import`` or ``from ... import`` statement of the same
file (``index_imports``). A file gets ZERO edits when a resolved name is bound more than once, or bound by anything
other than its import (assignment, parameter, def or class, loop, with, except, comprehension or walrus target,
global, match capture), when it has a star import, or when the new name would collide with a name the file uses.
The planner then returns the reason. String literals, comments and docstrings are never code and are never touched:
they are not Name or Attribute nodes. Anything unresolved is left as is.

Review item 4: the target can also be observed or changed without a Name or Attribute load, so the WHOLE file is refused
(zero edits, the detector reports the hazard spans) when (a) an attribute of the target is stored or deleted
(``M.old = x``, ``del M.old``, ``M.old += 1``), (b) a string constant equals the old name or the dotted path (getattr,
setattr, mock.patch name the symbol by string), (c) the old name is listed in ``__all__`` (a re-export), or (d) a
reflective builtin or ``mock``/``patch`` call (getattr, setattr, hasattr, delattr, ``patch*``) receives the module or
the target as an argument.
"""

import ast
from collections import Counter
from dataclasses import dataclass

from odooflux.core.engine.documents import Span
from odooflux.core.engine.edits import Edit
from odooflux.parsers.python import spans as sp

DEFAULT_SEVERITY = "WARNING"
DEFAULT_STEP = "python-fix"
VALIDATION = ("python-syntax",)
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True)
class Binding:
    """A top-level import binding: the qualified name the local name denotes, its alias node and its statement."""

    target: str
    alias: ast.alias
    stmt: ast.stmt


@dataclass(frozen=True)
class ImportIndex:
    counts: Counter     # name -> number of binding occurrences anywhere in the file (0 when absent)
    star: bool          # a star import exists somewhere in the file
    bindings: dict      # top-level import-bound local name -> Binding (absolute imports only)


def _count_bindings(tree):
    counts, star = Counter(), False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    star = True
                else:
                    counts[alias.asname or alias.name.split(".")[0]] += 1
        elif isinstance(node, _DEF_NODES):
            counts[node.name] += 1
        elif isinstance(node, ast.arg):
            counts[node.arg] += 1
        elif isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            counts[node.id] += 1
        elif isinstance(node, ast.ExceptHandler) and node.name:
            counts[node.name] += 1
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            counts.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            counts[node.name] += 1
        elif isinstance(node, ast.MatchMapping) and node.rest:
            counts[node.rest] += 1
    return counts, star


def index_imports(tree) -> ImportIndex:
    """Binding counts over the whole file and the top-level absolute import bindings. Only ``tree.body`` statements
    count as top-level: an import nested in a function, class, ``if`` or ``try`` is a binding but never resolves."""
    counts, star = _count_bindings(tree)
    bindings = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.asname:
                    local, target = alias.asname, alias.name
                else:
                    local = target = alias.name.split(".")[0]
                bindings.setdefault(local, Binding(target, alias, stmt))
        elif isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module:
            for alias in stmt.names:
                if alias.name != "*":
                    local = alias.asname or alias.name
                    bindings.setdefault(local, Binding(f"{stmt.module}.{alias.name}", alias, stmt))
    return ImportIndex(counts, star, bindings)


def qualified(node, index: ImportIndex):
    """The qualified name of a Name or Attribute chain through a top-level import, or None when unresolved."""
    dotted = sp.dotted_name(node)
    if dotted is None:
        return None
    root, dot, rest = dotted.partition(".")
    binding = index.bindings.get(root)
    if binding is None or index.counts[root] != 1:
        return None
    return binding.target + (dot + rest if dot else "")


_REFLECTIVE_CALLS = frozenset({"getattr", "setattr", "hasattr", "delattr"})


def _is_reflective_call(call: ast.Call) -> bool:
    parts = (sp.dotted_name(call.func) or "").split(".")
    return parts[-1] in _REFLECTIVE_CALLS or any(part.startswith("patch") for part in parts)


def _hazards(tree, index: ImportIndex, module: str, symbol: str) -> list:
    """``(reason, node)`` for every construct that lets the target be observed or changed outside a resolved load. A
    non-empty list refuses the whole file (see the module docstring, review item 4)."""
    target, found = f"{module}.{symbol}", []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and not isinstance(node.ctx, ast.Load) \
                and qualified(node, index) == target:
            found.append(("the target is assigned or deleted as an attribute", node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in (symbol, target):
            found.append(("a string constant names the target", node))
        elif isinstance(node, ast.Call) and _is_reflective_call(node):
            args = [*node.args, *[kw.value for kw in node.keywords]]
            if any(qualified(arg, index) in (module, target) for arg in args
                   if isinstance(arg, (ast.Name, ast.Attribute))):
                found.append(("a reflective call receives the module or the target", node))
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in (
                    stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target])):
            if any(isinstance(n, ast.Constant) and n.value == symbol for n in ast.walk(stmt)):
                found.append(("the name is re-exported through __all__", stmt))
    return found


def _refusal(index: ImportIndex, symbol: str) -> str:
    """Why the whole file gets zero edits for a rewrite of ``symbol`` (``""`` when it may be edited)."""
    if index.star:
        return "the file has a star import, which may bind any name"
    for name in index.bindings:
        if index.counts[name] != 1:
            return f"import-bound name {name!r} is bound {index.counts[name]} times in the file"
    if index.counts[symbol] and symbol not in index.bindings:
        return f"{symbol!r} is bound in the file by something other than a top-level import"
    return ""


def _new_name_refusal(tree, index: ImportIndex, module: str, new: str) -> str:
    """A rename of a from-import creates a binding of ``new``: it must not collide with another binding or with a
    free reference that would start to resolve to the imported symbol."""
    if index.counts[new]:
        same = index.bindings.get(new)
        if index.counts[new] == 1 and same is not None and same.target == f"{module}.{new}" \
                and isinstance(same.stmt, ast.ImportFrom):
            return ""
        return f"the new name {new!r} is already bound in the file"
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == new and isinstance(node.ctx, ast.Load):
            return f"the new name {new!r} is referenced in the file without a binding"
    return ""


def _text(parsed, node) -> str:
    span = sp.node_span(parsed, node)
    return parsed.text[span.start:span.end]


def _symbol_sites(parsed, index: ImportIndex, module: str, old: str, new):
    """``(Span, after, op)`` for every resolved reference to ``module.old``. ``new=None`` is detection mode (the
    ``after`` texts are then empty and the new-name checks are skipped)."""
    tree, target, sites = parsed.tree, f"{module}.{old}", []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and qualified(node, index) == target:
            after = "" if new is None else f"{_text(parsed, node.value)}.{new}"
            sites.append((sp.node_span(parsed, node), after, "rewrite_attribute"))
    for local, binding in index.bindings.items():
        if binding.target != target or not isinstance(binding.stmt, ast.ImportFrom):
            continue
        span = sp.node_span(parsed, binding.alias)
        if binding.alias.asname:
            if parsed.text[span.start:span.start + len(old)] != old:
                continue  # the alias text does not spell the symbol: left as is
            sites.append((Span(span.start, span.start + len(old)), "" if new is None else new, "rewrite_import"))
            continue
        sites.append((span, "" if new is None else new, "rewrite_import"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == local:
                sites.append((sp.node_span(parsed, node), "" if new is None else new, "rewrite_name"))
    return sorted(sites, key=lambda site: (site[0].start, site[0].end))


def _file_refusal(parsed, index: ImportIndex, module: str, symbol: str) -> str:
    """Why the whole file gets zero edits for ``module.symbol`` (``""`` when it may be edited)."""
    reason = _refusal(index, symbol)
    if reason:
        return reason
    hazards = _hazards(parsed.tree, index, module, symbol)
    return hazards[0][0] if hazards else ""


def _literal_spans(parsed, target: str) -> list:
    """Detection fallback for a shadowed file: import lines and attribute chains that spell the target literally."""
    spans = []
    for node in ast.walk(parsed.tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            spans += [sp.node_span(parsed, alias) for alias in node.names
                      if f"{node.module}.{alias.name}" == target]
        elif isinstance(node, ast.Attribute) and sp.dotted_name(node) == target:
            spans.append(sp.node_span(parsed, node))
    return sorted(spans, key=lambda span: (span.start, span.end))


def plan_rewrite_imported_symbol(parsed, module: str, old: str, new: str):
    """``(sites, refusal)``. ``sites`` are ``(Span, after, op)`` in document order; ``refusal`` is ``""`` when the file
    may be edited, else the reason it gets zero edits."""
    if parsed.tree is None:
        return [], "the file does not parse"
    index = index_imports(parsed.tree)
    refusal = _file_refusal(parsed, index, module, old)
    if not refusal and any(b.target == f"{module}.{old}" and b.alias.asname is None
                           and isinstance(b.stmt, ast.ImportFrom) for b in index.bindings.values()):
        refusal = _new_name_refusal(parsed.tree, index, module, new)
    if refusal:
        return [], refusal
    return _symbol_sites(parsed, index, module, old, new), ""


def plan_remove_imported_decorator(parsed, module: str, name: str):
    """``(sites, refusal)`` for removing bare decorators ``@name`` / ``@alias.name`` that resolve to ``module.name``.
    A call decorator (``@name(...)``) is never removed."""
    if parsed.tree is None:
        return [], "the file does not parse"
    index = index_imports(parsed.tree)
    refusal = _file_refusal(parsed, index, module, name)
    if refusal:
        return [], refusal
    target = f"{module}.{name}"
    decorators = [dec for node in ast.walk(parsed.tree) if isinstance(node, _DEF_NODES)
                  for dec in node.decorator_list
                  if isinstance(dec, (ast.Name, ast.Attribute)) and qualified(dec, index) == target]
    sites = [(sp.decorator_removal_span(parsed, dec), "", "remove_imported_decorator") for dec in decorators]
    return sorted(sites, key=lambda site: (site[0].start, site[0].end)), ""


def imported_symbol_spans(parsed, module: str, old: str) -> list:
    """Detection: spans of every reference to ``module.old``. In a file that gets zero edits the import lines and the
    literal attribute chains are reported instead, so a shadowed use still shows up for a human."""
    if parsed.tree is None:
        return []
    index = index_imports(parsed.tree)
    if _file_refusal(parsed, index, module, old):
        return _refused_spans(parsed, index, module, old)
    return [span for span, _, _ in _symbol_sites(parsed, index, module, old, None)]


def _refused_spans(parsed, index: ImportIndex, module: str, symbol: str) -> list:
    """Detection in a refused file: the literal spellings plus every hazard node (human review, zero edits)."""
    spans = _literal_spans(parsed, f"{module}.{symbol}")
    spans += [sp.node_span(parsed, node) for _, node in _hazards(parsed.tree, index, module, symbol)]
    return sorted(set(spans), key=lambda span: (span.start, span.end))


def imported_decorator_spans(parsed, module: str, name: str) -> list:
    """Detection: spans of every bare decorator resolving to ``module.name`` (literal fallback when refused)."""
    if parsed.tree is None:
        return []
    index = index_imports(parsed.tree)
    if _file_refusal(parsed, index, module, name):
        return _refused_spans(parsed, index, module, name)
    sites, _ = plan_remove_imported_decorator(parsed, module, name)
    return [span for span, _, _ in sites]


def _edit(parsed, span: Span, after: str, *, op: str, rule_id: str, severity: str, step: str) -> Edit:
    return Edit(id=f"{rule_id}:{op}:{span.start}-{span.end}", rule_id=rule_id, path=parsed.path,
                start=span.start, end=span.end, before=parsed.text[span.start:span.end], after=after,
                severity=severity, step=step, validation=VALIDATION)


def rewrite_imported_symbol_edits(parsed, module: str, old: str, new: str, *, rule_id: str,
                                  severity: str = DEFAULT_SEVERITY, step: str = DEFAULT_STEP) -> list:
    """Engine edits that rewrite ``module.old`` to ``module.new`` (see the module docstring for the proof rules)."""
    sites, _ = plan_rewrite_imported_symbol(parsed, module, old, new)
    return [_edit(parsed, span, after, op=op, rule_id=rule_id, severity=severity, step=step)
            for span, after, op in sites]


def remove_imported_decorator_edits(parsed, module: str, name: str, *, rule_id: str,
                                    severity: str = DEFAULT_SEVERITY, step: str = DEFAULT_STEP) -> list:
    """Engine edits that remove the bare decorators resolving to ``module.name``."""
    sites, _ = plan_remove_imported_decorator(parsed, module, name)
    return [_edit(parsed, span, after, op=op, rule_id=rule_id, severity=severity, step=step)
            for span, after, op in sites]
