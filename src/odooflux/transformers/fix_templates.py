"""Fix templates for automated certification (Feature 012, plan section 4 and addendum A4).

A fix template maps one existing transformer primitive (``odooflux.transformers.python``, the five 1:1 operations)
to: the DERIVED change classes it may serve (ledger candidate classes never certify), the rule-row parameters it
requires, how those parameters become primitive arguments, and deterministic fixture generators. The table in
``FIX_TEMPLATES`` is the ONLY source of eligibility. Nothing is derived from rule text, and no AI output qualifies.

Pure stdlib. Library only in Wave 2: nothing here is wired into gates, the loader, the importer, promote, the
pipeline or the CLI, and nothing here creates or changes a rule row or a maturity value.
"""

import ast
import keyword as _pykeyword
import re
from dataclasses import dataclass
from types import MappingProxyType

from odooflux.transformers import imported as _imported
from odooflux.transformers import python as _python_transformers

FIX_TEMPLATES_VERSION = 1
MAX_NAME_LENGTH = 120
RULE_ORIGINS_ELIGIBLE = ("BUILTIN", "MANUAL")  # an absent origin means BUILTIN (rule_metadata.schema.json)

# Ledger change classes (schemas/change_ledger.schema.json, entries/class).
LEDGER_CLASSES = ("ADDED", "REMOVED", "RENAMED_CANDIDATE", "MOVED", "SIGNATURE_CHANGED", "BEHAVIOUR_CHANGED",
                  "DEPRECATED", "REPLACEMENT_CANDIDATE", "UNKNOWN")

# Derived change classes: the only classes that can make a fix eligible. Ledger classes are heuristic or descriptive
# and never certify a fix (REMOVED and DEPRECATED alone do not prove a removal is behaviour-preserving).
DERIVED_CLASSES = (
    "REPLACEMENT_CONFIRMED",       # a replacement pair confirmed by a recorded MANUAL ledger disposition
    "DELEGATING_ALIAS",            # static proof that the old method still exists in the new source and its body only
                                   # forwards its arguments to the replacement
    "IDENTITY_DECORATOR_REMOVED",  # the removed decorator was an identity function in the old source
)
# A derived class is only ever proven by the machine confirmation path (knowledge/update), never by a ledger class or an
# AI proposal. A GENERATED row is eligible only when the caller supplies a verified confirmation (confirmation_verified).

# Reasons for templates with no served class, keyed by template id. Other disabled templates get a generic reason.
_DISABLED_REASONS = MappingProxyType({
    "python.rename_keyword": "python.rename_keyword is disabled: no change class proves a renamed keyword argument "
                             "keeps its meaning",
    "python.remove_keyword": "python.remove_keyword is disabled: no change class proves a removed keyword argument "
                             "is a no-op",
    "python.replace_call_name": "python.replace_call_name is superseded by python.rewrite_imported_symbol: a literal "
                                "dotted match does not prove the callee is the imported symbol",
    "python.replace_attribute": "python.replace_attribute is superseded by python.rewrite_imported_symbol: a literal "
                                "dotted match does not prove the receiver is the imported module",
    "python.remove_decorator": "python.remove_decorator is superseded by python.remove_imported_decorator: a literal "
                               "decorator match does not prove the decorator is the imported identity function",
})

# Fixers bound by rule metadata (``module:function``, see rules/bindable.py). The certification executor runs exactly
# these through the loader path, so a certified template and an executed rule are the same code.
_CERTIFIED = "odooflux.rules.python.certified"
_REWRITE_FIXER = f"{_CERTIFIED}:rewrite_imported_symbol"
_REWRITE_DETECTOR = f"{_CERTIFIED}:flag_imported_symbol"
_REMOVE_FIXER = f"{_CERTIFIED}:remove_imported_decorator"
_REMOVE_DETECTOR = f"{_CERTIFIED}:flag_imported_decorator"

_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_KIND_PATTERNS = {"dotted": _DOTTED, "identifier": _IDENTIFIER}


class FixTemplateError(ValueError):
    """A parameter set or fixture request that the table does not allow. ``code`` is machine-readable."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class FixTemplate:
    template_id: str
    primitive: str                 # function name in ``primitive_module``
    change_classes: tuple          # derived classes this template may serve (ledger classes never do)
    params: tuple                  # ((rule param name, kind), ...); every name is required, no extras
    distinct: tuple                # ((a, b), ...): pairs of params that must differ
    arguments: tuple               # ((primitive keyword, rule param name), ...)
    fixtures: object               # callable(validated params) -> (positive_before, positive_expected, negative)
    primitive_module: object = None  # module object holding ``primitive``
    fixer_ref: object = None       # the bound fixer (module:function) a row must carry to be eligible; None if disabled
    detector_refs: tuple = ()      # the bound detectors a row may carry (module:function)

    @property
    def names(self) -> frozenset:
        return frozenset(name for name, _ in self.params)


def _check_source(source: str) -> str:
    try:
        ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - fixtures are built from validated names only
        raise FixTemplateError("fixture_invalid", f"generated fixture does not parse: {exc.msg}") from exc
    return source


def _callee_fixtures(callee, replacement):
    before = f"value = {callee}(1)\n"
    expected = f"value = {replacement}(1)\n"
    negative = f"NOTE = '{callee}(1)'\nvalue = {callee}_other(1)\n"
    return _check_source(before), _check_source(expected), _check_source(negative)


def _attribute_fixtures(old, new):
    before = f"value = {old}\n"
    expected = f"value = {new}\n"
    negative = f"NOTE = '{old}'\nvalue = {old}_other\n"
    return _check_source(before), _check_source(expected), _check_source(negative)


def _rename_keyword_fixtures(callee, keyword, new_keyword):
    before = f"value = {callee}({keyword}=1)\n"
    expected = f"value = {callee}({new_keyword}=1)\n"
    negative = f"NOTE = '{callee}({keyword}=1)'\nvalue = {callee}({keyword}_other=1)\n"
    return _check_source(before), _check_source(expected), _check_source(negative)


def _remove_keyword_fixtures(callee, keyword):
    before = f"value = {callee}({keyword}=2)\n"
    expected = f"value = {callee}()\n"
    negative = f"NOTE = '{callee}({keyword}=2)'\nvalue = {callee}({keyword}_other=2)\n"
    return _check_source(before), _check_source(expected), _check_source(negative)


def _remove_decorator_fixtures(decorator):
    before = f"class Model:\n    @{decorator}\n    def f(self):\n        pass\n"
    expected = "class Model:\n    def f(self):\n        pass\n"
    negative = f"class Model:\n    @{decorator}_other\n    def f(self):\n        pass\nNOTE = '@{decorator}'\n"
    return _check_source(before), _check_source(expected), _check_source(negative)


def _rewrite_imported_fixtures(module, old, new):
    """Import + call positive (the import line and the call are both rewritten; the string and the comment are not),
    and a negative where the name is shadowed by a parameter, so the whole file must stay byte-identical."""
    before = f"from {module} import {old}\nvalue = {old}(1)\nNOTE = '{old}(1)'  # {old}(1)\n"
    expected = f"from {module} import {new}\nvalue = {new}(1)\nNOTE = '{old}(1)'  # {old}(1)\n"
    negative = f"from {module} import {old}\n\n\ndef g({old}):\n    return {old}(1)\n"
    return _check_source(before), _check_source(expected), _check_source(negative)


def _remove_imported_decorator_fixtures(module, name):
    """A bare decorator in a decorator stack is removed (the other decorator stays); a call decorator is not."""
    before = (f"from {module} import {name}\n\n\nclass Model:\n    @{name}\n    @property\n    def f(self):\n"
              "        return 1\n")
    expected = f"from {module} import {name}\n\n\nclass Model:\n    @property\n    def f(self):\n        return 1\n"
    negative = (f"from {module} import {name}\n\n\nclass Model:\n    @{name}(1)\n    def f(self):\n"
                f"        return 1\nNOTE = '@{name}'\n")
    return _check_source(before), _check_source(expected), _check_source(negative)


def _build_table():
    templates = (
        FixTemplate(
            template_id="python.rewrite_imported_symbol", primitive="rewrite_imported_symbol_edits",
            primitive_module=_imported,
            change_classes=("REPLACEMENT_CONFIRMED", "DELEGATING_ALIAS"),
            params=(("module", "dotted"), ("old", "identifier"), ("new", "identifier")),
            distinct=(("old", "new"),),
            arguments=(("module", "module"), ("old", "old"), ("new", "new")),
            fixtures=lambda p: _rewrite_imported_fixtures(p["module"], p["old"], p["new"]),
            fixer_ref=_REWRITE_FIXER, detector_refs=(_REWRITE_DETECTOR,)),
        FixTemplate(
            template_id="python.remove_imported_decorator", primitive="remove_imported_decorator_edits",
            primitive_module=_imported,
            change_classes=("IDENTITY_DECORATOR_REMOVED",),
            params=(("module", "dotted"), ("name", "identifier")),
            distinct=(),
            arguments=(("module", "module"), ("name", "name")),
            fixtures=lambda p: _remove_imported_decorator_fixtures(p["module"], p["name"]),
            fixer_ref=_REMOVE_FIXER, detector_refs=(_REMOVE_DETECTOR,)),
        # Superseded (feature 012 addendum F3.7): literal dotted matching is unsound for custom code, so these serve
        # no class and never certify. They stay in the table for audit and for the existing record tests.
        FixTemplate(
            template_id="python.replace_call_name", primitive="replace_call_name",
            primitive_module=_python_transformers,
            change_classes=(),
            params=(("callee", "dotted"), ("replacement", "dotted")),
            distinct=(("callee", "replacement"),),
            arguments=(("old", "callee"), ("new", "replacement")),
            fixtures=lambda p: _callee_fixtures(p["callee"], p["replacement"])),
        FixTemplate(
            template_id="python.replace_attribute", primitive="replace_attribute",
            primitive_module=_python_transformers,
            change_classes=(),
            params=(("old", "dotted"), ("new", "dotted")),
            distinct=(("old", "new"),),
            arguments=(("old", "old"), ("new", "new")),
            fixtures=lambda p: _attribute_fixtures(p["old"], p["new"])),
        FixTemplate(
            template_id="python.rename_keyword", primitive="rename_keyword",
            primitive_module=_python_transformers,
            change_classes=(),  # disabled: no derived class proves a renamed keyword keeps its meaning
            params=(("callee", "dotted"), ("keyword", "identifier"), ("new_keyword", "identifier")),
            distinct=(("keyword", "new_keyword"),),
            arguments=(("call_name", "callee"), ("keyword", "keyword"), ("new_name", "new_keyword")),
            fixtures=lambda p: _rename_keyword_fixtures(p["callee"], p["keyword"], p["new_keyword"])),
        FixTemplate(
            template_id="python.remove_keyword", primitive="remove_keyword",
            primitive_module=_python_transformers,
            change_classes=(),  # disabled: dropping a keyword argument changes behaviour unless proven a no-op
            params=(("callee", "dotted"), ("keyword", "identifier")),
            distinct=(),
            arguments=(("call_name", "callee"), ("keyword", "keyword")),
            fixtures=lambda p: _remove_keyword_fixtures(p["callee"], p["keyword"])),
        FixTemplate(
            template_id="python.remove_decorator", primitive="remove_decorator",
            primitive_module=_python_transformers,
            change_classes=(),
            params=(("decorator", "dotted"),),
            distinct=(),
            arguments=(("name", "decorator"),),
            fixtures=lambda p: _remove_decorator_fixtures(p["decorator"])),
    )
    by_params = {}
    for template in templates:
        if not hasattr(template.primitive_module, template.primitive):
            raise RuntimeError(f"fix template {template.template_id}: no primitive {template.primitive}")
        if frozenset(template.names) in by_params:
            raise RuntimeError(f"fix template {template.template_id}: parameter names collide")
        by_params[frozenset(template.names)] = template.template_id
    unknown = [c for t in templates for c in t.change_classes if c not in LEDGER_CLASSES + DERIVED_CLASSES]
    if unknown:
        raise RuntimeError(f"fix templates name unknown change classes: {unknown}")
    return MappingProxyType({t.template_id: t for t in templates})


FIX_TEMPLATES = _build_table()


def template(template_id: str) -> FixTemplate:
    try:
        return FIX_TEMPLATES[template_id]
    except (KeyError, TypeError):
        raise FixTemplateError("template_unknown", f"no fix template {template_id!r}") from None


def _check_value(name: str, kind: str, value) -> None:
    if not isinstance(value, str):
        raise FixTemplateError("param_type", f"{name} must be a string")
    if not value:
        raise FixTemplateError("param_empty", f"{name} is empty")
    if len(value) > MAX_NAME_LENGTH:
        raise FixTemplateError("param_too_long", f"{name} is longer than {MAX_NAME_LENGTH} characters")
    if not _KIND_PATTERNS[kind].fullmatch(value):
        raise FixTemplateError("param_invalid", f"{name} is not a {kind} name: {value!r}")
    if any(_pykeyword.iskeyword(part) for part in value.split(".")):
        raise FixTemplateError("param_reserved", f"{name} contains a Python keyword: {value!r}")


def validate_params(template_id: str, params) -> dict:
    """Strictly validate ``params`` for ``template_id`` and return the validated mapping. Raises FixTemplateError."""
    spec = template(template_id)
    if not isinstance(params, dict):
        raise FixTemplateError("params_type", "fixer params must be a mapping")
    keys = set(params)
    if keys != spec.names:
        raise FixTemplateError("params_set", f"{template_id} needs exactly {sorted(spec.names)}, got {sorted(keys)}")
    for name, kind in spec.params:
        _check_value(name, kind, params[name])
    for left, right in spec.distinct:
        if params[left] == params[right]:
            raise FixTemplateError("params_identical", f"{left} and {right} must differ")
    return {name: params[name] for name, _ in spec.params}


def _match_template(keys: frozenset):
    for spec in FIX_TEMPLATES.values():
        if spec.names == keys:
            return spec
    return None


def _closest_reason(keys: frozenset) -> str:
    best = min(FIX_TEMPLATES.values(), key=lambda t: len(t.names ^ keys))
    missing = sorted(best.names - keys)
    extra = sorted(keys - best.names)
    return (f"parameters match no fix template (closest {best.template_id}: missing {missing}, extra {extra})")


def _unproven_reason(change_class: str) -> str:
    """Why a ledger class never certifies a fix. A candidate class is an unconfirmed heuristic pair."""
    if change_class in ("RENAMED_CANDIDATE", "REPLACEMENT_CANDIDATE"):
        return (f"ledger change class {change_class!r} is an unconfirmed, unproven candidate pair: only a recorded "
                "MANUAL disposition confirms it (as a derived class), and a candidate class never certifies a fix")
    return (f"ledger change class {change_class!r} is unproven: it does not show a fix is behaviour-preserving, so it "
            "never certifies a fix (only a derived class carrying its own proof does)")


def eligible(rule_row, change_class=None, *, confirmation_verified=False):
    """``(template_id, reason)``. ``template_id`` is None when the row is not eligible; ``reason`` says why.

    A row qualifies only when its origin is BUILTIN or MANUAL (or GENERATED with ``confirmation_verified`` True, i.e.
    a verified machine confirmation), its ``params`` exactly match one template, its ``fixer_ref`` and ``detector_ref``
    are the ones the template binds (so the executed rule is the certified code), the supplied ``change_class`` is a
    DERIVED class the template serves, and every parameter validates. Ledger classes (``LEDGER_CLASSES``) are always
    refused as unproven, whatever the template. AI-proposed and unknown origins never qualify.
    """
    if not isinstance(rule_row, dict):
        return None, "rule row is not a mapping"
    origin = rule_row.get("origin", "BUILTIN")
    if not isinstance(origin, str) or origin not in RULE_ORIGINS_ELIGIBLE + ("GENERATED",):
        return None, (f"origin {origin!r} is not eligible: only {', '.join(RULE_ORIGINS_ELIGIBLE)} rows qualify "
                      "(AI-proposed and unknown origins never do)")
    if origin == "GENERATED" and confirmation_verified is not True:
        return None, ("origin 'GENERATED' is eligible only with a verified machine confirmation "
                      "(confirmation_verified); none was supplied")
    params = rule_row.get("params")
    if not isinstance(params, dict) or not params:
        return None, "rule row has no fixer params"
    spec = _match_template(frozenset(params))
    if spec is None:
        return None, _closest_reason(frozenset(params))
    if not spec.change_classes:
        return None, _DISABLED_REASONS.get(
            spec.template_id, f"{spec.template_id} is disabled: no change class is auto-certified for it")
    if change_class is None:
        return None, "ledger change class not supplied"
    if change_class in LEDGER_CLASSES:
        return None, _unproven_reason(change_class)
    if change_class not in spec.change_classes:
        return None, (f"ledger change class {change_class!r} is not served by {spec.template_id} "
                      f"(serves {', '.join(spec.change_classes)})")
    if rule_row.get("fixer_ref") != spec.fixer_ref:
        return None, (f"fixer_ref {rule_row.get('fixer_ref')!r} is not the fixer bound to {spec.template_id} "
                      f"({spec.fixer_ref!r})")
    if rule_row.get("detector_ref") not in spec.detector_refs:
        return None, (f"detector_ref {rule_row.get('detector_ref')!r} is not a detector bound to {spec.template_id} "
                      f"(one of {', '.join(spec.detector_refs)})")
    try:
        validate_params(spec.template_id, params)
    except FixTemplateError as exc:
        return None, f"{exc.code}: {exc.detail}"
    return spec.template_id, "eligible"


def primitive_arguments(template_id: str, params) -> dict:
    """Keyword arguments for the primitive, derived from validated params."""
    spec = template(template_id)
    valid = validate_params(template_id, params)
    return {kw: valid[name] for kw, name in spec.arguments}


def fixtures(template_id: str, params) -> tuple:
    """Deterministic ``(positive_before, positive_expected, negative_unchanged)`` built only from validated params."""
    spec = template(template_id)
    return spec.fixtures(validate_params(template_id, params))


def primitive_edits(template_id: str, parsed, rule_id: str, params) -> list:
    """Run the real primitive (looked up on its module at call time) on a parsed document; returns engine Edits."""
    spec = template(template_id)
    func = getattr(spec.primitive_module, spec.primitive)
    return func(parsed, **primitive_arguments(template_id, params), rule_id=rule_id)


__all__ = ["DERIVED_CLASSES", "FIX_TEMPLATES", "FIX_TEMPLATES_VERSION", "FixTemplate", "FixTemplateError",
           "LEDGER_CLASSES", "MAX_NAME_LENGTH", "RULE_ORIGINS_ELIGIBLE", "eligible", "fixtures", "primitive_arguments",
           "primitive_edits", "template", "validate_params"]
