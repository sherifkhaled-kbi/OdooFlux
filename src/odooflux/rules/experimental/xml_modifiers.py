"""Experimental fixer for the ``attrs`` and ``states`` view attributes (roadmap T2, section 3: strict subset).

Experimental: the two knowledge rules stay DETECT_ONLY. The registry (``rules.experimental.registry``) binds these
functions to the existing detectors only when a run passes ``--experimental-fixes``.

Conversion is all or nothing per element. An element is converted only when it is inside a ``<form>`` and not inside a
nested list, kanban, search or other view; every ``attrs`` key is ``invisible``, ``readonly`` or ``required``; every
leaf is ``(bare_field, op, literal)`` with ``op`` in ``=``, ``!=``, ``in``, ``not in`` and a non-falsy literal (or a
non-empty list of them); the only logical operators are ``&``, ``|`` and ``!``; and the element has no existing modifier
attribute of a key it would write. ``states="a,b"`` becomes ``invisible="state not in ['a','b']"`` only when the
element has no ``invisible`` and no ``attrs``. Anything else is left untouched and reported with a reason.

Inherited views (AF-6): inside the ``<field name="arch">`` of a record that has an ``inherit_id``, an element is also
converted when it sits in an ``<xpath>`` with ``position`` ``inside``, ``after``, ``before`` or ``replace`` whose
``expr`` passes the target rules below; the element itself carries no ``position``. An
``<xpath position="attributes">`` holding ``<attribute name="attrs">`` with a dict is converted to one
``<attribute name="<key>">expression</attribute>`` per key, under the same leaf rules.

The target view of an xpath is not known from one document, and the word ``form`` alone is no proof. An expression is
accepted without more proof only when it is a form-rooted path: ``/form`` or ``//form`` followed by child steps
(``/name`` or ``//name``, each with an optional ``[@name='x']``), with no axis, ``..`` or other predicate, and no
list-like view. ``/form/field[@name='x']`` and ``//form/field[@name='x']`` are also checked against the target whenever
it can be read: the field must occur exactly once in that form and outside any nested view. Any other expression is
converted only when its target is proven: the record's ``inherit_id`` names exactly one ``ir.ui.view`` record (or
``<template>`` id) with that xmlid, that record is a base view (no ``inherit_id``) whose arch is a single ``<form>``,
and the expression is ``//field[@name='x']`` naming a field found exactly once in that form, outside any nested
list-like view or embedded form. A ``/form/field`` or ``//form/field`` target that cannot be read (a core ref, or no
module context for a ref outside the document) is accepted as the form-rooted shape. Without module context (the default) only a bare ref to a record of this same document is proven; a qualified
ref is refused. With a ``ModuleViews`` context (VR-1, one per run) the records are also read from the other XML files
of the module the ref names (a bare ref names the document's own module), and that module must be a sibling module
directory beside the document's module. Target-level failures keep the reason ``inherited-target-not-form``;
expression and field failures have their own reasons (``inherited-target-expr-unverified``,
``inherited-target-field-not-found``, ``inherited-target-field-ambiguous``, ``inherited-target-field-nested``).

Literal mode only: the falsy shortcut is never used. Output is deterministic; a second application finds nothing.
"""

import ast
import keyword
import os
import re
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import unescape

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import Edit
from odooflux.parsers.xml import document as xmldoc
from odooflux.transformers import xml as xh
from odooflux.transformers.modifiers import Unconvertible, domain_to_expression

ATTRS_RULE = "16-17.xml.attrs-removed"
STATES_RULE = "16-17.xml.states-attribute-removed"
XML_VALIDATION = ("xml-wellformed",)
KEYS = ("invisible", "readonly", "required")
NESTED_VIEWS = frozenset({"tree", "list", "kanban", "search", "graph", "pivot", "calendar", "gantt", "activity",
                          "map", "cohort"})
OPERATORS = ("=", "!=", "in", "not in")
# Names that an Odoo 17 modifier expression evaluates from its context, not from the record: a field with one of these
# names would silently compare the context value instead (QA D1). A Python keyword is refused for the same reason.
RESERVED = frozenset({"uid", "context", "context_today", "current_date", "today", "now", "time", "datetime",
                      "relativedelta", "parent", "active_id", "active_ids", "active_model", "allowed_company_ids"})
LOGIC = ("&", "|", "!")
POSITIONS = ("inside", "after", "before", "replace")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_NAME_STEP = r"/{1,2}[A-Za-z_][\w-]*(?:\[@name=(['\"])[A-Za-z_][A-Za-z0-9_]*\1\])?"
# ``/form`` or ``//form`` followed by child/descendant name steps only (no axis, ``..`` or other predicate).
_FORM_PATH = re.compile(r"//?form(?:" + _NAME_STEP + r")*")
# ``/form/field[@name='x']`` or ``//form/field[@name='x']``: the field must be checked in the target form when readable.
_FORM_FIELD = re.compile(r"//?form/field\[@name=(['\"])([A-Za-z_][A-Za-z0-9_]*)\1\]")
_NESTED_STEP = re.compile(r"(?<![\w-])(" + "|".join(sorted(NESTED_VIEWS)) + r")(?![\w-])")
_FIELD_PREDICATE = re.compile(r"//field\[@name=(['\"])([A-Za-z_][A-Za-z0-9_]*)\1\]")
# Below a target form's root, these start a region that is not the form itself (a list-like view or an embedded form).
_TARGET_NESTED = NESTED_VIEWS | {"form"}
TARGET_REASON = "inherited-target-not-form"
STATE_NOTE = "assumes a 'state' field on the record"
MANIFESTS = ("__manifest__.py", "__openerp__.py")
_MODULE_NAME = re.compile(r"[a-z_][a-z0-9_]*")  # an Odoo technical module name: no dots, no separators
_CONTEXT_SKIP = frozenset({"static", "tests"})  # directories whose XML is not view data of the module


@dataclass(frozen=True)
class Conversion:
    rule_id: str
    line: int
    element: str
    before: str
    after: str
    note: str = ""


@dataclass(frozen=True)
class Refusal:
    rule_id: str
    line: int
    element: str
    reason: str


@dataclass(frozen=True)
class Plan:
    edits: tuple = ()
    converted: tuple = ()
    refused: tuple = ()


class _Refuse(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Undetermined(_Refuse):
    """A target that this run cannot read (a core ref, or a ref outside the document without module context)."""

    def __init__(self):
        super().__init__(TARGET_REASON)


# ---- location ----------------------------------------------------------------------------------------------------

def _attr_value(element, name: str):
    attr = element.get_attr(name)
    return attr.value if attr is not None else None


def _location(by_index: dict, element) -> None:
    """Refuse unless the element sits in a form (plain view) or in an inherited view's xpath that targets a form, and
    in no nested list-like view."""
    if element.tag in NESTED_VIEWS:
        raise _Refuse("nested-view")
    in_form, xpath_el, parent = False, None, element.parent_index
    while parent is not None:
        ancestor = by_index[parent]
        if ancestor.tag in NESTED_VIEWS:
            raise _Refuse("nested-view")
        in_form = in_form or ancestor.tag == "form"
        if xpath_el is None and ancestor.tag == "xpath":
            xpath_el = ancestor
        parent = ancestor.parent_index
    if in_form:
        return
    if element.get_attr("position") is not None:
        raise _Refuse("position-element")
    _inherited_scope(by_index, element, xpath_el, POSITIONS, outside_reason="not-in-form")


def _is_inherited_arch(by_index: dict, arch) -> bool:
    """True for the ``<field name="arch">`` of a record that has an ``inherit_id`` field."""
    record = by_index.get(arch.parent_index)
    if record is None or record.tag != "record":
        return False
    return any(by_index[child].tag == "field" and _attr_value(by_index[child], "name") == "inherit_id"
               for child in record.children_index)


class _Index(dict):
    """Element index of one file (``element.index -> element``). ``views`` maps the bare ``id`` of each ``ir.ui.view``
    record of the file to those records; it is built on first use. ``path`` is the file and ``context`` the run's
    ``ModuleViews`` (None without module context)."""

    def __init__(self, elements, path=None, context=None):
        super().__init__((element.index, element) for element in elements)
        self._views = None
        self.path = path
        self.context = context

    @property
    def views(self) -> dict:
        if self._views is None:
            views: dict = {}
            for element in self.values():
                if element.tag == "record" and _attr_value(element, "model") == "ir.ui.view":
                    xmlid = _attr_value(element, "id")
                    if xmlid:
                        views.setdefault(xmlid, []).append(element)
            self._views = views
        return self._views


def _view_xmlid(element):
    """The xmlid an element defines as a view: an ``ir.ui.view`` record or a QWeb ``<template>``; None otherwise."""
    if element.tag == "template" or (element.tag == "record" and _attr_value(element, "model") == "ir.ui.view"):
        return _attr_value(element, "id") or None
    return None


def _qualified(xmlid: str, module: str) -> str:
    """The full xmlid of a record id seen in a file of ``module`` (an id that already has a dot is its own xmlid)."""
    return xmlid if "." in xmlid else f"{module}.{xmlid}"


class ModuleViews:
    """Read-only index of the view records of the modules beside a document (VR-1). One object per run.

    A module is a directory with a manifest. Its sibling modules are the other module directories of the same parent
    (the addons root of the run). Each module's ``*.xml`` files, except those under ``static`` and ``tests``, are
    parsed on first use and kept for the object's lifetime. A file that does not parse makes its whole module
    unreadable, so no target in it is ever proven. Nothing is written and no file is changed.
    """

    def __init__(self):
        self._tables: dict = {}  # module directory -> {xmlid: [(path, index, element)]}, or None when unreadable

    @staticmethod
    def module_dir(path):
        """The nearest ancestor directory of ``path`` that holds a manifest, or None."""
        for parent in Path(os.path.abspath(path)).parents:
            if any((parent / name).is_file() for name in MANIFESTS):
                return parent
        return None

    def module_name(self, path):
        found = self.module_dir(path)
        return None if found is None else found.name

    def directory(self, path, module: str):
        """The directory of module ``module`` as seen from the module that holds ``path``; None unless it is a module
        directory of that addons root (a name that is not a technical module name is never a module)."""
        own = self.module_dir(path)
        if own is None or not _MODULE_NAME.fullmatch(module):
            return None
        candidate = own.parent / module
        return candidate if any((candidate / name).is_file() for name in MANIFESTS) else None

    def table(self, directory: Path):
        key = str(directory)
        if key not in self._tables:
            self._tables[key] = _module_table(directory)
        return self._tables[key]


def _module_table(directory: Path):
    """``{qualified xmlid: [(path, index, element)]}`` of every view record of one module, or None when a file of the
    module cannot be parsed or read."""
    table: dict = {}
    try:
        files = sorted(p for p in directory.rglob("*.xml")
                       if not set(p.relative_to(directory).parts[:-1]) & _CONTEXT_SKIP)
        for path in files:
            xdoc = xmldoc.parse(Document.from_bytes(str(path), path.read_bytes()))
            if xdoc.parse_error is not None:
                return None
            index = _Index(xdoc.elements, str(path))
            for element in xdoc.elements:
                xmlid = _view_xmlid(element)
                if xmlid:
                    table.setdefault(_qualified(xmlid, directory.name), []).append((str(path), index, element))
    except (OSError, UnicodeError):
        return None
    return table


def _children_named(by_index: dict, element, tag: str, name: str | None = None) -> list:
    return [child for child in (by_index[i] for i in element.children_index)
            if child.tag == tag and (name is None or _attr_value(child, "name") == name)]


def _target_records(by_index: dict, ref: str) -> list:
    """``(index, element)`` of every view record (or template) whose xmlid is ``ref``.

    Without module context only this document is searched, and a qualified ref is refused (the PA-4 rule). With it,
    this document's records count too, and so do the other files of the module the ref names; a bare ref names the
    document's own module. A module that is not a readable sibling makes the ref unprovable."""
    views = by_index.context
    if views is None:
        if "." in ref:
            raise _Undetermined()
        return [(by_index, element) for element in by_index.views.get(ref, [])]
    own = views.module_name(by_index.path)
    if own is None:
        raise _Undetermined()
    key = ref if "." in ref else f"{own}.{ref}"
    directory = views.directory(by_index.path, key.partition(".")[0])
    if directory is None:
        raise _Undetermined()  # not a sibling module of this run (a core or third-party module)
    table = views.table(directory)
    if table is None:
        raise _Refuse(TARGET_REASON)  # a sibling module that cannot be read is refused, not assumed
    here = [(by_index, element) for element in by_index.values()
            if _view_xmlid(element) is not None and _qualified(_view_xmlid(element), own) == key]
    this_file = os.path.abspath(by_index.path)
    elsewhere = [(index, element) for path, index, element in table.get(key, [])
                 if os.path.abspath(path) != this_file]
    return here + elsewhere


def _target_arch_root(by_index: dict, record):
    """``(index, root)``: the ``<form>`` root of the base view that ``record`` inherits from, and the index of its file.

    Refuses with ``inherited-target-not-form`` unless ``inherit_id`` is one ref to exactly one view record (or
    template) with that xmlid, that record has no ``inherit_id`` of its own, and its arch holds exactly one element,
    a ``<form>``. The record of a view that inherits from another view is refused: its fields come from its parent."""
    refs = _children_named(by_index, record, "field", "inherit_id")
    if len(refs) != 1:
        raise _Refuse(TARGET_REASON)
    ref = _attr_value(refs[0], "ref")
    if not ref or refs[0].get_attr("eval") is not None:
        raise _Refuse(TARGET_REASON)
    found = _target_records(by_index, ref)
    if not found and by_index.context is None:
        raise _Undetermined()  # without module context a ref outside this document cannot be read
    if len(found) != 1:
        raise _Refuse(TARGET_REASON)
    target_index, target = found[0]
    if _children_named(target_index, target, "field", "inherit_id"):
        raise _Refuse(TARGET_REASON)
    arches = _children_named(target_index, target, "field", "arch")
    if len(arches) != 1:
        raise _Refuse(TARGET_REASON)
    roots = [target_index[i] for i in arches[0].children_index]
    if len(roots) != 1 or roots[0].tag != "form":
        raise _Refuse(TARGET_REASON)
    return target_index, roots[0]


def _target_field_matches(by_index: dict, root, name: str) -> list:
    """One entry per ``<field name=name>`` under ``root``: True when it sits inside a nested list-like view or embedded
    form (below the root), False when it is a direct part of the form."""
    matches, stack = [], [(root, False)]
    while stack:
        parent, nested = stack.pop()
        for index in parent.children_index:
            child = by_index[index]
            child_nested = nested or child.tag in _TARGET_NESTED
            if child.tag == "field" and _attr_value(child, "name") == name:
                matches.append(child_nested)
            stack.append((child, child_nested))
    return matches


def _check_target_field(by_index: dict, root, name: str) -> None:
    matches = _target_field_matches(by_index, root, name)
    if not matches:
        raise _Refuse("inherited-target-field-not-found")
    if len(matches) > 1:
        raise _Refuse("inherited-target-field-ambiguous")
    if matches[0]:
        raise _Refuse("inherited-target-field-nested")


def _target_check(by_index: dict, record, expr) -> None:
    """Refuse unless the xpath's target is proven to be a form (quoted text is ignored for the nested-view check).

    A form-rooted path (``_FORM_PATH``) with no list-like view is accepted without proof. A ``/form/field`` or
    ``//form/field`` with ``[@name='x']`` is accepted, and its field is checked in the proven form when that form can be
    read. Any other expression is accepted only as ``//field[@name='x']`` whose field is found exactly once, directly in
    the form proven by ``_target_arch_root``.
    """
    if expr is None:
        raise _Refuse(TARGET_REASON)
    stripped = expr.strip()
    if _NESTED_STEP.search(_QUOTED.sub("", expr)):
        raise _Refuse("nested-view")
    field = _FORM_FIELD.fullmatch(stripped)
    if field is not None:
        try:
            target_index, root = _target_arch_root(by_index, record)
        except _Undetermined:
            return
        _check_target_field(target_index, root, field.group(2))
        return
    if _FORM_PATH.fullmatch(stripped):
        return
    target_index, root = _target_arch_root(by_index, record)
    predicate = _FIELD_PREDICATE.fullmatch(stripped)
    if predicate is None:
        raise _Refuse("inherited-target-expr-unverified")
    _check_target_field(target_index, root, predicate.group(2))


def _inherited_scope(by_index: dict, element, xpath_el, expected_positions, *, outside_reason: str) -> None:
    """Refuse unless the element is inside an xpath of an inherited view's arch, with a supported position and an
    expression that targets a form."""
    arch, parent = None, element.parent_index
    while parent is not None:
        ancestor = by_index[parent]
        if ancestor.tag == "field" and _attr_value(ancestor, "name") == "arch":
            arch = ancestor
            break
        parent = ancestor.parent_index
    if arch is None or not _is_inherited_arch(by_index, arch):
        raise _Refuse(outside_reason)
    if xpath_el is None:
        raise _Refuse(outside_reason)
    if _attr_value(xpath_el, "position") not in expected_positions:
        raise _Refuse("unsupported-position")
    _target_check(by_index, by_index[arch.parent_index], _attr_value(xpath_el, "expr"))


# ---- attrs domain ------------------------------------------------------------------------------------------------

def _scalar(node):
    """A non-falsy literal value; context names and anything else are refused."""
    if isinstance(node, ast.Constant):
        value = node.value
        if value is None or (isinstance(value, (str, int, float)) and not value):
            raise _Refuse("falsy-literal")
        if isinstance(value, (str, int, float)):
            return value
        raise _Refuse("non-literal-value")
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float)):
        value = -node.operand.value if isinstance(node.op, ast.USub) else node.operand.value
        if not value:
            raise _Refuse("falsy-literal")
        return value
    if isinstance(node, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)):
        raise _Refuse("context-name")
    raise _Refuse("non-literal-value")


def _leaf(node) -> tuple:
    if len(node.elts) != 3:
        raise _Refuse("malformed-domain")
    field_node, op_node, value_node = node.elts
    if not (isinstance(field_node, ast.Constant) and isinstance(field_node.value, str)):
        raise _Refuse("malformed-domain")
    field = field_node.value
    if "." in field:
        raise _Refuse("dotted-field")
    if not _IDENTIFIER.fullmatch(field):
        raise _Refuse("malformed-domain")
    if field in RESERVED or keyword.iskeyword(field):
        raise _Refuse("reserved-name")
    if not (isinstance(op_node, ast.Constant) and isinstance(op_node.value, str)):
        raise _Refuse("malformed-domain")
    op = op_node.value
    if op not in OPERATORS:
        raise _Refuse(f"unsupported-operator:{op}")
    if op in ("in", "not in"):
        if not isinstance(value_node, (ast.List, ast.Tuple)) or not value_node.elts:
            raise _Refuse("malformed-domain")
        return (field, op, [_scalar(item) for item in value_node.elts])
    return (field, op, _scalar(value_node))


def _domain(node) -> list:
    if not isinstance(node, ast.List):
        raise _Refuse("malformed-domain")
    items = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value in LOGIC:
            items.append(item.value)
        elif isinstance(item, (ast.Tuple, ast.List)):
            items.append(_leaf(item))
        else:
            raise _Refuse("malformed-domain")
    if not items:
        raise _Refuse("empty-domain")
    return items


def _expression(domain: list) -> str:
    rendered = domain_to_expression(domain, "literal")
    if isinstance(rendered, Unconvertible):
        raise _Refuse(rendered.reason)
    return rendered


def _attrs_entries(raw: str) -> list:
    """``[(key, value_node)]`` of the attrs dictionary; refuses anything that is not a plain literal dict."""
    try:
        tree = ast.parse(raw.strip(), mode="eval")
    except (SyntaxError, ValueError):
        raise _Refuse("malformed-attrs")
    body = tree.body
    if not isinstance(body, ast.Dict):
        raise _Refuse("malformed-attrs")
    if not body.keys:
        raise _Refuse("empty-attrs")
    entries, seen = [], set()
    for key_node, value_node in zip(body.keys, body.values):
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            raise _Refuse("malformed-attrs")
        if key_node.value in seen:
            raise _Refuse(f"duplicate-key:{key_node.value}")
        seen.add(key_node.value)
        entries.append((key_node.value, value_node))
    return entries


# ---- per-element conversion --------------------------------------------------------------------------------------

def _meta(ctx, element, suffix: str):
    return xh.EditMeta(id=f"{ctx.rule_id}:{element.index}:{suffix}", rule_id=ctx.rule_id, step=ctx.step,
                       severity=ctx.severity, validation=XML_VALIDATION)


def _attrs_element(xdoc, by_index, element, ctx):
    _location(by_index, element)
    attr = element.get_attr("attrs")
    if element.get_attr("states") is not None:
        raise _Refuse("states-with-attrs")
    expressions = {}
    for key, value_node in _attrs_entries(attr.value):
        if key not in KEYS:
            raise _Refuse(f"unsupported-key:{key}")
        if element.get_attr(key) is not None:
            raise _Refuse(f"same-modifier-exists:{key}")
        expressions[key] = _expression(_domain(value_node))
    edits = []
    if ctx is not None:
        for key, expression in expressions.items():
            edits.append(xh.set_attr(xdoc, element, key, expression, meta=_meta(ctx, element, key)))
        edits.append(xh.remove_attr(xdoc, element, "attrs", meta=_meta(ctx, element, "attrs")))
    after = " ".join(f'{key}="{xh.escape_attr_value(value, chr(34))}"' for key, value in expressions.items())
    return edits, (xdoc.text[attr.span.start:attr.span.end], after, "")


def _text_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _attribute_element(xdoc, by_index, element, ctx):
    """``<xpath position="attributes"><attribute name="attrs">{dict}</attribute></xpath>`` in an inherited view: one
    ``<attribute name="<key>">expression</attribute>`` per key, replacing the element."""
    xpath_el = by_index.get(element.parent_index)
    if xpath_el is None or xpath_el.tag != "xpath":
        raise _Refuse("unsupported-target")
    if set(attr.name for attr in element.attrs) != {"name"}:
        raise _Refuse("malformed-attribute")
    _inherited_scope(by_index, element, xpath_el, ("attributes",), outside_reason="not-inherited-view")
    if element.end_tag_span is None:
        raise _Refuse("malformed-attrs")
    if element.children_index:
        raise _Refuse("malformed-attribute")
    raw = xdoc.text[element.start_tag_span.end:element.end_tag_span.start]
    entries = _attrs_entries(unescape(raw, {"&quot;": '"', "&apos;": "'"}))
    expressions = {}
    for key, value_node in entries:
        if key not in KEYS:
            raise _Refuse(f"unsupported-key:{key}")
        for sibling_index in xpath_el.children_index:
            sibling = by_index[sibling_index]
            if sibling is not element and sibling.tag == "attribute" and _attr_value(sibling, "name") == key:
                raise _Refuse(f"same-modifier-exists:{key}")
        expressions[key] = _expression(_domain(value_node))
    before = xdoc.text[element.span.start:element.span.end]
    parts = [f'<attribute name="{key}">{_text_escape(expression)}</attribute>'
             for key, expression in expressions.items()]
    line_start = xdoc.text.rfind("\n", 0, element.span.start) + 1
    prefix = xdoc.text[line_start:element.span.start]
    separator = "\n" + (prefix if prefix.strip() == "" else "")  # one element per line; indent kept when present
    after = separator.join(parts)
    edits = []
    if ctx is not None:
        meta = _meta(ctx, element, "attribute")
        edits.append(Edit(id=meta.id, rule_id=meta.rule_id, path=xdoc.path, start=element.span.start,
                          end=element.span.end, before=before, after=after, severity=meta.severity, step=meta.step,
                          validation=tuple(meta.validation), finding_ids=tuple(meta.finding_ids)))
    return edits, (before, after, "")


def _attrs_any(xdoc, by_index, element, ctx):
    if element.tag == "attribute":
        return _attribute_element(xdoc, by_index, element, ctx)
    return _attrs_element(xdoc, by_index, element, ctx)


def _states_element(xdoc, by_index, element, ctx):
    _location(by_index, element)
    if element.get_attr("attrs") is not None:
        raise _Refuse("states-with-attrs")
    if element.get_attr("invisible") is not None:
        raise _Refuse("same-modifier-exists:invisible")
    attr = element.get_attr("states")
    raw = attr.value
    items = [part.strip() for part in raw.split(",")]
    if not raw.strip() or any(not _IDENTIFIER.fullmatch(item) for item in items):
        raise _Refuse("malformed-states")
    expression = "state not in [" + ",".join(repr(item) for item in items) + "]"
    edits = []
    if ctx is not None:
        edits.append(xh.set_attr(xdoc, element, "invisible", expression, meta=_meta(ctx, element, "invisible")))
        edits.append(xh.remove_attr(xdoc, element, "states", meta=_meta(ctx, element, "states")))
    after = f'invisible="{xh.escape_attr_value(expression, chr(34))}"'
    return edits, (xdoc.text[attr.span.start:attr.span.end], after, STATE_NOTE)


def _candidate_start(element, attr_name: str):
    """Start offset locating a candidate: its ``attr_name`` attribute, or for ``attrs`` the start tag of an
    ``<attribute name="attrs">`` element of an inherited view. None when the element is not a candidate."""
    attr = element.get_attr(attr_name)
    if attr is not None:
        return attr.span.start
    if attr_name == "attrs" and element.tag == "attribute" and _attr_value(element, "name") == "attrs":
        return element.start_tag_span.start
    return None


def _plan(document, rule_id: str, ctx, attr_name: str, per_element, views=None) -> Plan:
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        return Plan()
    by_index = _Index(xdoc.elements, document.path, views)
    edits, converted, refused = [], [], []
    for element in xdoc.elements:
        start = _candidate_start(element, attr_name)
        if start is None:
            continue
        line = document.line_col(start)[0]
        try:
            element_edits, (before, after, note) = per_element(xdoc, by_index, element, ctx)
        except _Refuse as exc:
            refused.append(Refusal(rule_id=rule_id, line=line, element=element.tag, reason=exc.reason))
            continue
        edits.extend(edit for edit in element_edits if edit is not None)
        converted.append(Conversion(rule_id=rule_id, line=line, element=element.tag, before=before, after=after,
                                    note=note))
    return Plan(edits=tuple(edits), converted=tuple(converted), refused=tuple(refused))


def plan_attrs(document: Document, ctx=None, views=None) -> Plan:
    """Convertible ``attrs`` elements with their edits (edits only when ``ctx`` is given), and refusals. ``views`` is a
    ``ModuleViews`` (module context of the run) or None."""
    return _plan(document, ATTRS_RULE, ctx, "attrs", _attrs_any, views)


def plan_states(document: Document, ctx=None, views=None) -> Plan:
    """Convertible ``states`` elements with their edits (edits only when ``ctx`` is given), and refusals."""
    return _plan(document, STATES_RULE, ctx, "states", _states_element, views)


def explain_attrs(document: Document, views=None) -> Plan:
    """The conversion records and refusals for ``attrs`` without edits (used by the report)."""
    return plan_attrs(document, None, views)


def explain_states(document: Document, views=None) -> Plan:
    return plan_states(document, None, views)


def convert_attrs(document, ctx, views=None) -> list:
    """Fixer for ``16-17.xml.attrs-removed`` (fixer contract ``(document, ctx, **params) -> edits``; ``views`` is the
    optional module context, bound per run by the orchestrator)."""
    return list(plan_attrs(document, ctx, views).edits)


def convert_states(document, ctx, views=None) -> list:
    """Fixer for ``16-17.xml.states-attribute-removed``."""
    return list(plan_states(document, ctx, views).edits)
