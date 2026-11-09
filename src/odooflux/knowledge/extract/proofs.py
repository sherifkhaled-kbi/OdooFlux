"""Static soundness proofs for machine-confirmed fix pairs (feature 012, addendum F1). Stdlib `ast` only.

Pure and deterministic: no file access, no execution, no AI. Input is the text of one python module on each side of a
pair. Output is a `Proof` (derived class, derived params, structural witness and its digest) or a `Refusal` (one
reason code). Every condition is re-run by `check_witness` on the witness facts alone, so the prover, the L1 verifier
and the extractor facts share one code path. Any ambiguity is a refusal.

Review item 5 (feature 012 hardening): every class refuses a module whose text uses a REFLECTIVE_NAMES name (globals,
locals, sys, inspect, exec, getattr, `__name__`, frame attributes, ...) on either side, and refuses a module-level
statement that is not an import, def, docstring or simple constant assignment and that mentions the old or new name
(MODULE_STATEMENT). S2 requires immutable literal defaults (S2_DEFAULT_NOT_IMMUTABLE). The witness names `proof_side`, the
side whose file carries the proof, which the L1 verifier binds to the evidence location.

Derived classes: S1 `REPLACEMENT_CONFIRMED` (identical bodies; ledger REPLACEMENT_CANDIDATE with an official docs or
migration hint), S2 `DELEGATING_ALIAS` (old only forwards to new; ledger BEHAVIOUR_CHANGED or DEPRECATED),
S3 `IDENTITY_DECORATOR_REMOVED` (old is `return p`; ledger REMOVED). Scope: top-level plain sync functions of ONE
module; no decorators; no nested def or class anywhere in the module named old or new; no star import; no module
`__getattr__`. A name loaded by a body is local, or a builtin not bound by the module, or an import binding whose
statement digest is identical on both sides. Anything else refuses (S1_GLOBAL_REF, S2_GLOBAL_REF).

Witness: structural facts only (identifiers, booleans, ints, 64-hex digests). Source text is never stored. The
docstring is not part of the body comparison (no runtime effect); the `Replaces ``old``` hint is read from the new
function's docstring and only its name is kept.

Public API:
    module_name(path) -> str | None
    module_facts(text, path, watch=()) -> dict | None
    function_proofs(text, path) -> dict[name, dict] | None     (extractor fact `proof`, see python_orm)
    prove(*, ledger_class, source_kind=None, old, new=None, from_path, to_path, from_text, to_text) -> Proof | Refusal
    check_witness(witness) -> Proof | Refusal
    valid_name(name) -> bool
    PROOF_TOOL_ID, REFUSAL_CODES, LEDGER_CLASS_RULE, Proof, Refusal
"""

import ast
import builtins
import copy
import hashlib
import keyword
import re
import warnings
from dataclasses import dataclass

from odooflux.knowledge.release.canonical import digest_obj

__all__ = ["PROOF_TOOL_ID", "REFUSAL_CODES", "LEDGER_CLASS_RULE", "Proof", "Refusal", "module_name", "module_facts",
           "function_proofs", "prove", "check_witness", "valid_name"]

PROOF_TOOL_ID = "proofs/1"
MAX_NAME_LENGTH = 120
REPLACES_RE = re.compile(r"[Rr]eplaces ``([A-Za-z_][\w.]*)``")
LEDGER_CLASS_RULE = {"REPLACEMENT_CANDIDATE": "S1", "BEHAVIOUR_CHANGED": "S2", "DEPRECATED": "S2", "REMOVED": "S3"}
DERIVED_NAME = {"S1": "REPLACEMENT_CONFIRMED", "S2": "DELEGATING_ALIAS", "S3": "IDENTITY_DECORATOR_REMOVED"}
HINT_SOURCES = ("docs", "migration")
WARN_CATEGORIES = ("DeprecationWarning", "FutureWarning")
REFUSAL_CODES = frozenset({
    "UNSUPPORTED_CLASS", "NAME_INVALID", "MODULE_MISMATCH", "PARSE_FAILED", "WITNESS_INVALID", "WITNESS_SOURCE_TEXT",
    "STAR_IMPORT", "MODULE_GETATTR", "NESTED_DEFINITION", "BINDING_CONFLICT", "DEF_MISSING", "NOT_PLAIN_DEF",
    "LEDGER_SOURCE", "S1_NOT_IDENTICAL", "S1_HINT_MISSING", "S1_GLOBAL_REF", "S2_NOT_ALIAS", "S2_SIGNATURE",
    "S2_CHAIN", "S2_CYCLE", "S2_GLOBAL_REF", "S3_NOT_IDENTITY", "S3_STILL_BOUND",
    "S2_DEFAULT_NOT_IMMUTABLE", "S1_REFLECTIVE", "S2_REFLECTIVE", "S3_REFLECTIVE", "MODULE_STATEMENT",
})
# Names whose use lets code observe or rebind the pair outside its own text (review item 5). A module that touches one
# of them, on either side, is refused by every class: the proof reads the module text, not what the module does at run
# time. Attribute names cover `frame.f_globals`, `gen.gi_frame` and the like.
REFLECTIVE_NAMES = frozenset({
    "sys", "inspect", "importlib", "builtins", "__builtins__", "gc", "ctypes", "globals", "locals", "vars", "exec",
    "eval", "compile", "getattr", "setattr", "delattr", "__import__", "__file__", "__name__", "__dict__", "__globals__",
    "__code__", "__closure__", "__class__", "__spec__", "__loader__", "f_globals", "f_locals", "f_back", "f_builtins",
    "f_code", "gi_frame", "cr_frame", "tb_frame", "currentframe", "_getframe",
})
_REFLECTIVE_PREFIX = {"S1": "S1_REFLECTIVE", "S2": "S2_REFLECTIVE", "S3": "S3_REFLECTIVE"}
# The side whose file carries the proof: the new function (to) for the replacement and alias classes, the removed
# function (from) for REMOVED. The machine confirmation binds its evidence location to this side (review item 2).
PROOF_SIDE = {"REPLACEMENT_CANDIDATE": "to", "BEHAVIOUR_CHANGED": "to", "DEPRECATED": "to", "REMOVED": "from"}
_BUILTINS = frozenset(n for n in dir(builtins) if not n.startswith("__"))
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SOURCE_HINT = re.compile(r"[\s()\[\]{}=,'\"]")
_DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
_BINDING_KINDS = frozenset({"def", "class", "store", "global", "except", "match"})
_WARNINGS_KIND = "import:" + hashlib.sha256(ast.dump(ast.parse("import warnings").body[0]).encode("utf-8")).hexdigest()
_TOP_KEYS = frozenset({"ledger_class", "source_kind", "module", "old", "new", "from", "to", "proof_side"})
_SIDE_KEYS = frozenset({"star_import", "bindings", "all_names", "nested_hits", "defs", "reflective", "statement_hits"})
_DEF_KEYS = frozenset({"is_async", "decorator_count", "signature", "def_digest", "free_names", "declares_global",
                       "nested_scope", "docstring_replaces", "forward_shape", "identity_shape", "immutable_defaults"})
_SIG_KEYS = frozenset({"positional", "posonly", "vararg", "kwonly", "kwarg", "defaults", "kw_defaults"})
_FWD_KEYS = frozenset({"callee", "positional", "vararg", "keywords", "kwarg", "warn"})


@dataclass(frozen=True)
class Refusal:
    """No proof. `code` is one of REFUSAL_CODES; `detail` names the condition, never source text."""
    code: str
    detail: str = ""


@dataclass(frozen=True)
class Proof:
    derived_class: str        # REPLACEMENT_CONFIRMED | DELEGATING_ALIAS | IDENTITY_DECORATOR_REMOVED
    module: str
    old: str
    new: object               # str, or None for REMOVED
    derived_params: dict      # {module, old, new} for S1/S2, {module, name} for S3 (fixer keywords)
    witness: dict
    witness_digest: str


def _refuse(code: str, detail: str = "") -> Refusal:
    assert code in REFUSAL_CODES, code
    return Refusal(code, detail)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_name(name) -> bool:
    return (isinstance(name, str) and _IDENT.fullmatch(name) is not None and not keyword.iskeyword(name)
            and len(name) <= MAX_NAME_LENGTH)


def module_name(path):
    """Dotted module of a snapshot path: `odoo/x/y.py` -> `odoo.x.y`, `__init__.py` -> the package,
    `odoo/addons/<a>/...` -> `odoo.addons.<a>...`. None unless every segment is a plain identifier."""
    if not isinstance(path, str) or not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(_IDENT.fullmatch(p) and not keyword.iskeyword(p) for p in parts):
        return None
    return ".".join(parts)


def _split_doc(body):
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return list(body[1:]), first.value.value
    return list(body), None


def _params(args) -> set:
    names = {x.arg for x in args.posonlyargs + args.args + args.kwonlyargs}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _outer_parts(node) -> list:
    """Expressions of a def, class or lambda that run in the enclosing scope."""
    if isinstance(node, _DEF_TYPES):
        a = node.args
        parts = [*node.decorator_list, *a.defaults, *[d for d in a.kw_defaults if d is not None]]
        for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
            if arg is not None and arg.annotation is not None:
                parts.append(arg.annotation)
        if node.returns is not None:
            parts.append(node.returns)
        return parts
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *node.keywords]
    return [*node.args.defaults, *[d for d in node.args.kw_defaults if d is not None]]  # ast.Lambda


def _import_names(node) -> list:
    if isinstance(node, ast.Import):
        return [a.asname or a.name.split(".")[0] for a in node.names]
    return [a.asname or a.name for a in node.names if a.name != "*"]


def _comp_values(node) -> list:
    return [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]


def _bound_here(nodes) -> set:
    """Names bound in the scope the nodes belong to. Nested def and class bodies, lambda bodies and comprehension
    targets are other scopes and are not entered; a nested def or class contributes its own name."""
    out, stack = set(), list(nodes)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
            stack.extend(_outer_parts(node))
            continue
        if isinstance(node, ast.Lambda):
            stack.extend(_outer_parts(node))
            continue
        if isinstance(node, _COMPREHENSIONS):
            stack.append(node.generators[0].iter)
            for index, gen in enumerate(node.generators):
                if index:
                    stack.append(gen.iter)
                stack.extend(gen.ifs)
            stack.extend(_comp_values(node))
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out.update(_import_names(node))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif type(node).__name__ in ("MatchAs", "MatchStar") and node.name:
            out.add(node.name)
        elif type(node).__name__ == "MatchMapping" and node.rest:
            out.add(node.rest)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _loads(nodes, scopes) -> set:
    """Names loaded by `nodes` that no enclosing scope in `scopes` binds (scopes innermost last)."""
    free = set()
    stack = [(node, scopes) for node in nodes]
    while stack:
        node, sc = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            stack.extend((part, sc) for part in _outer_parts(node))
            if isinstance(node, ast.Lambda):
                inner = sc + [_params(node.args) | _bound_here([node.body])]
                stack.append((node.body, inner))
            else:
                locs = _bound_here(node.body)
                if not isinstance(node, ast.ClassDef):
                    locs |= _params(node.args)
                stack.extend((stmt, sc + [locs]) for stmt in node.body)
        elif isinstance(node, _COMPREHENSIONS):
            targets = set()
            for gen in node.generators:
                targets |= {n.id for n in ast.walk(gen.target) if isinstance(n, ast.Name)}
            inner = sc + [targets]
            stack.append((node.generators[0].iter, sc))
            for index, gen in enumerate(node.generators):
                if index:
                    stack.append((gen.iter, inner))
                stack.append((gen.target, inner))
                stack.extend((cond, inner) for cond in gen.ifs)
            stack.extend((value, inner) for value in _comp_values(node))
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load) and not any(node.id in s for s in sc):
                free.add(node.id)
        else:
            stack.extend((child, sc) for child in ast.iter_child_nodes(node))
    return free


def _free_names(node, body):
    """(sorted free names, declares_global). Header expressions run at module scope; the body in its own scope."""
    free = _loads(_outer_parts(node), [])
    free |= _loads(body, [_params(node.args) | _bound_here(body)])
    declares = any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(node))
    return sorted(free), declares


def _digest_of_nodes(nodes) -> str:
    return digest_obj([None if n is None else ast.dump(n) for n in nodes])


_IMMUTABLE_TYPES = (type(None), bool, int, float, str, bytes)


def _immutable_literal(node) -> bool:
    """True for None, bool, int, float, str, bytes and tuples of those: values with no identity or state to share."""
    if isinstance(node, ast.Constant):
        return type(node.value) in _IMMUTABLE_TYPES
    if isinstance(node, ast.Tuple):
        return all(_immutable_literal(elt) for elt in node.elts)
    return False


def _reflective_hits(tree) -> list:
    """Reflective names (REFLECTIVE_NAMES) the module text uses: names, attributes and import bindings."""
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in REFLECTIVE_NAMES:
            hits.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in REFLECTIVE_NAMES:
            hits.add(node.attr)
        elif isinstance(node, ast.Import):
            hits.update(a.name.split(".")[0] for a in node.names if a.name.split(".")[0] in REFLECTIVE_NAMES)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in REFLECTIVE_NAMES:
            hits.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            hits.update(a.name for a in node.names if a.name in REFLECTIVE_NAMES)
    return sorted(hits)


def _mentions(node, names) -> set:
    """Watched names a node mentions: a name, an attribute, or a string constant that spells the name as a word."""
    hits = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in names:
            hits.add(sub.id)
        elif isinstance(sub, ast.Attribute) and sub.attr in names:
            hits.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            hits.update(n for n in names if re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", sub.value))
    return hits


def _statement_allowed(stmt, position) -> bool:
    """Module-level statements that cannot run code over the watched names: imports, defs, the docstring and simple
    constant assignments."""
    if isinstance(stmt, (ast.Import, ast.ImportFrom) + _DEF_TYPES):
        return True
    if position == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
            and isinstance(stmt.value.value, str):
        return True
    return (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Constant))


def _statement_hits(tree, watch) -> list:
    """Watched names mentioned by a module-level statement that is not an allowed kind (review item 5)."""
    hits = set()
    for position, stmt in enumerate(tree.body):
        if not _statement_allowed(stmt, position):
            hits |= _mentions(stmt, watch)
    return sorted(hits)


def _warn_of(stmt):
    """`warnings.warn(<str const>, DeprecationWarning|FutureWarning[, stacklevel=<int const>])` or None."""
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return None
    call, func = stmt.value, stmt.value.func
    if not (isinstance(func, ast.Attribute) and func.attr == "warn" and isinstance(func.value, ast.Name)
            and func.value.id == "warnings"):
        return None
    if len(call.args) != 2:
        return None
    msg, category = call.args
    if not (isinstance(msg, ast.Constant) and isinstance(msg.value, str) and isinstance(category, ast.Name)
            and category.id in WARN_CATEGORIES):
        return None
    stacklevel = None
    for kw in call.keywords:
        if kw.arg != "stacklevel" or stacklevel is not None:
            return None
        if not (isinstance(kw.value, ast.Constant) and type(kw.value.value) is int):
            return None
        stacklevel = kw.value.value
    return {"category": category.id, "stacklevel": stacklevel}


def _forward_shape(node, body):
    """The alias shape `[warn] return callee(<every parameter once, same order>)` or None."""
    if isinstance(node, ast.AsyncFunctionDef):
        return None
    stmts, warn = list(body), None
    if len(stmts) == 2:
        warn = _warn_of(stmts[0])
        if warn is None:
            return None
        stmts = stmts[1:]
    if len(stmts) != 1 or not isinstance(stmts[0], ast.Return):
        return None
    call = stmts[0].value
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
        return None
    a = node.args
    positional = [x.arg for x in a.posonlyargs + a.args]
    vararg = a.vararg.arg if a.vararg else None
    kwonly = [x.arg for x in a.kwonlyargs]
    kwarg = a.kwarg.arg if a.kwarg else None
    want_args = [ast.dump(ast.Name(id=n, ctx=ast.Load())) for n in positional]
    if vararg:
        want_args.append(ast.dump(ast.Starred(value=ast.Name(id=vararg, ctx=ast.Load()), ctx=ast.Load())))
    want_kw = [ast.dump(ast.keyword(arg=n, value=ast.Name(id=n, ctx=ast.Load()))) for n in kwonly]
    if kwarg:
        want_kw.append(ast.dump(ast.keyword(arg=None, value=ast.Name(id=kwarg, ctx=ast.Load()))))
    if [ast.dump(x) for x in call.args] != want_args or [ast.dump(k) for k in call.keywords] != want_kw:
        return None
    return {"callee": call.func.id, "positional": positional, "vararg": vararg, "keywords": kwonly,
            "kwarg": kwarg, "warn": warn}


def _identity_shape(node, body, positional) -> bool:
    """`return p` only, one positional parameter, no defaults, no annotations, no decorators."""
    a = node.args
    if not isinstance(node, ast.FunctionDef) or node.decorator_list or node.returns is not None:
        return False
    if len(positional) != 1 or a.posonlyargs or a.vararg or a.kwonlyargs or a.kwarg or a.defaults or a.kw_defaults:
        return False
    if a.args[0].annotation is not None:
        return False
    return (len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Name)
            and body[0].value.id == positional[0])


def _def_facts(node) -> dict:
    body, doc = _split_doc(node.body)
    a = node.args
    positional = [x.arg for x in a.posonlyargs + a.args]
    signature = {"positional": positional, "posonly": len(a.posonlyargs),
                 "vararg": a.vararg.arg if a.vararg else None, "kwonly": [x.arg for x in a.kwonlyargs],
                 "kwarg": a.kwarg.arg if a.kwarg else None, "defaults": _digest_of_nodes(a.defaults),
                 "kw_defaults": _digest_of_nodes(a.kw_defaults)}
    clone = copy.copy(node)  # name and docstring are the only normalised parts
    clone.name = "_"
    clone.body = body
    free, declares = _free_names(node, body)
    return {
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "decorator_count": len(node.decorator_list),
        "signature": signature,
        "def_digest": _sha(ast.dump(clone)),
        "free_names": free,
        "declares_global": declares,
        "nested_scope": any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                            for n in ast.walk(node) if n is not node),
        "docstring_replaces": sorted(set(REPLACES_RE.findall(doc or ""))),
        "forward_shape": _forward_shape(node, body),
        "identity_shape": _identity_shape(node, body, positional),
        "immutable_defaults": all(_immutable_literal(d) for d in
                                  [*a.defaults, *[d for d in a.kw_defaults if d is not None]]),
    }


def _module_bindings(tree):
    """({name: [kind, ...]}, star_import) for every module-scope binding, including those under if, try and with.
    Comprehension targets and walrus targets are counted: over-approximation only ever refuses more."""
    bindings, star = {}, False

    def bind(name, kind):
        bindings.setdefault(name, []).append(kind)

    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name, "class" if isinstance(node, ast.ClassDef) else "def")
            stack.extend(_outer_parts(node))
            for inner in ast.walk(node):
                if isinstance(inner, ast.Global):
                    for name in inner.names:
                        bind(name, "global")
            continue
        if isinstance(node, ast.Lambda):
            stack.extend(_outer_parts(node))
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
                star = True
            kind = "import:" + _sha(ast.dump(node))
            for name in _import_names(node):
                bind(name, kind)
            continue
        if isinstance(node, ast.Global):
            for name in node.names:
                bind(name, "global")
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bind(node.id, "store")
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bind(node.name, "except")
        elif type(node).__name__ in ("MatchAs", "MatchStar") and node.name:
            bind(node.name, "match")
        elif type(node).__name__ == "MatchMapping" and node.rest:
            bind(node.rest, "match")
        stack.extend(ast.iter_child_nodes(node))
    return bindings, star


def module_facts(text, path, watch=()):
    """Structural facts of one module version, or None when the path is not a module or the text does not parse.
    `watch` names the symbols whose nested definitions are reported in `nested_hits`."""
    module = module_name(path)
    if module is None or not isinstance(text, str):
        return None
    try:
        with warnings.catch_warnings():  # invalid escapes in customer text must not print anything
            warnings.simplefilter("ignore")
            tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError, RecursionError):
        return None
    bindings, star = _module_bindings(tree)
    top = {id(stmt) for stmt in tree.body}
    nested = {n.name for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and id(n) not in top}
    all_names = set()
    for stmt in tree.body:
        if any(isinstance(n, ast.Name) and n.id == "__all__" for n in ast.walk(stmt)):
            all_names |= {n.value for n in ast.walk(stmt) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    defs = {stmt.name: _def_facts(stmt) for stmt in tree.body if isinstance(stmt, _DEF_TYPES)}
    return {
        "module": module,
        "star_import": star,
        "bindings": {name: sorted(kinds) for name, kinds in sorted(bindings.items())},
        "all_names": sorted(n for n in all_names if _IDENT.fullmatch(n)),
        "nested_hits": sorted(n for n in watch if n in nested),
        "defs": dict(sorted(defs.items())),
        "reflective": _reflective_hits(tree),
        "statement_hits": _statement_hits(tree, watch),
    }


def function_proofs(text, path):
    """Extractor view (fact key `proof`): one dict per top-level function, or None when no facts can be derived.
    None is never a guess: a missing proof simply means no fix can be proven for that function."""
    try:
        facts = module_facts(text, path)
    except (RecursionError, ValueError, TypeError, AttributeError):
        return None
    if facts is None:
        return None
    imports = {name: kinds[0][len("import:"):] for name, kinds in facts["bindings"].items()
               if len(kinds) == 1 and kinds[0].startswith("import:")}
    tops = digest_obj(facts["bindings"])
    out = {}
    for name, d in facts["defs"].items():
        out[name] = {"module": facts["module"], "def_digest": d["def_digest"], "free_names": d["free_names"],
                     "import_digests": imports, "top_level_bindings_digest": tops, "is_async": d["is_async"],
                     "forward_shape": d["forward_shape"], "identity_shape": d["identity_shape"],
                     "docstring_replaces": d["docstring_replaces"], "signature": d["signature"],
                     "decorator_count": d["decorator_count"], "nested_scope": d["nested_scope"],
                     "declares_global": d["declares_global"], "star_import": facts["star_import"],
                     "module_getattr": "__getattr__" in facts["bindings"]}
    return out


def _side_view(facts, watch) -> dict:
    return {"star_import": facts["star_import"], "bindings": facts["bindings"], "all_names": facts["all_names"],
            "nested_hits": facts["nested_hits"], "defs": {n: facts["defs"][n] for n in watch if n in facts["defs"]},
            "reflective": facts["reflective"], "statement_hits": facts["statement_hits"]}


def prove(*, ledger_class, source_kind=None, old, new=None, from_path, to_path, from_text, to_text):
    """Prove one pair from its two module texts. `new` is None only for REMOVED (S3)."""
    if ledger_class not in LEDGER_CLASS_RULE:
        return _refuse("UNSUPPORTED_CLASS", str(ledger_class))
    if not valid_name(old):
        return _refuse("NAME_INVALID", "old")
    if ledger_class == "REPLACEMENT_CANDIDATE":
        if source_kind not in HINT_SOURCES:
            return _refuse("LEDGER_SOURCE", "replacement needs an official docs or migration hint")
    elif source_kind is not None:
        return _refuse("LEDGER_SOURCE", "only a replacement candidate carries a hint source")
    if ledger_class == "REMOVED":
        if new is not None:
            return _refuse("NAME_INVALID", "REMOVED takes no replacement name")
    elif not valid_name(new) or new == old:
        return _refuse("NAME_INVALID", "new")
    module = module_name(from_path)
    if module is None or module != module_name(to_path):
        return _refuse("MODULE_MISMATCH", "both sides must be one module")
    watch = (old,) if new is None else (old, new)
    facts_from = module_facts(from_text, from_path, watch)
    facts_to = module_facts(to_text, to_path, watch)
    if facts_from is None or facts_to is None:
        return _refuse("PARSE_FAILED", "a side does not parse as python")
    witness = {"ledger_class": ledger_class, "source_kind": source_kind, "module": module, "old": old, "new": new,
               "from": _side_view(facts_from, watch), "to": _side_view(facts_to, watch),
               "proof_side": PROOF_SIDE[ledger_class]}
    return check_witness(witness)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _strings(item)


def _is_digest(value) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _is_kind(value) -> bool:
    if not isinstance(value, str):
        return False
    return value in _BINDING_KINDS or (value.startswith("import:") and _is_digest(value[len("import:"):]))


def _def_problem(d) -> bool:
    """True when a def record does not have the exact structural shape."""
    if not isinstance(d, dict) or set(d) != _DEF_KEYS:
        return True
    sig = d["signature"]
    if not isinstance(sig, dict) or set(sig) != _SIG_KEYS:
        return True
    names_ok = (all(valid_name(x) for x in sig["positional"] + sig["kwonly"])
                and (sig["vararg"] is None or valid_name(sig["vararg"]))
                and (sig["kwarg"] is None or valid_name(sig["kwarg"])))
    if not names_ok or not isinstance(sig["posonly"], int) or isinstance(sig["posonly"], bool):
        return True
    if not (_is_digest(sig["defaults"]) and _is_digest(sig["kw_defaults"])):
        return True
    if not (_is_digest(d["def_digest"]) and isinstance(d["is_async"], bool) and isinstance(d["identity_shape"], bool)
            and isinstance(d["declares_global"], bool) and isinstance(d["nested_scope"], bool)
            and isinstance(d["immutable_defaults"], bool)):
        return True
    if not isinstance(d["decorator_count"], int) or isinstance(d["decorator_count"], bool):
        return True
    if not all(valid_name(x) for x in d["free_names"]):
        return True
    if not all(_TOKEN.fullmatch(x) for x in d["docstring_replaces"]):
        return True
    fwd = d["forward_shape"]
    if fwd is None:
        return False
    if not isinstance(fwd, dict) or set(fwd) != _FWD_KEYS or not valid_name(fwd["callee"]):
        return True
    if not all(valid_name(x) for x in fwd["positional"] + fwd["keywords"]):
        return True
    if fwd["vararg"] is not None and not valid_name(fwd["vararg"]):
        return True
    if fwd["kwarg"] is not None and not valid_name(fwd["kwarg"]):
        return True
    warn = fwd["warn"]
    if warn is None:
        return False
    return (not isinstance(warn, dict) or set(warn) != {"category", "stacklevel"}
            or warn["category"] not in WARN_CATEGORIES
            or not (warn["stacklevel"] is None or (isinstance(warn["stacklevel"], int)
                                                  and not isinstance(warn["stacklevel"], bool))))


def _side_problem(side, names) -> bool:
    if not isinstance(side, dict) or set(side) != _SIDE_KEYS or not isinstance(side["star_import"], bool):
        return True
    bindings = side["bindings"]
    if not isinstance(bindings, dict):
        return True
    for name, kinds in bindings.items():
        if not valid_name(name) or not isinstance(kinds, list) or not all(_is_kind(k) for k in kinds):
            return True
    if not isinstance(side["all_names"], list) or not all(valid_name(x) for x in side["all_names"]):
        return True
    if not isinstance(side["nested_hits"], list) or not all(x in names for x in side["nested_hits"]):
        return True
    if not isinstance(side["reflective"], list) or not all(x in REFLECTIVE_NAMES for x in side["reflective"]):
        return True
    if not isinstance(side["statement_hits"], list) or not all(x in names for x in side["statement_hits"]):
        return True
    defs = side["defs"]
    if not isinstance(defs, dict) or not set(defs) <= set(names):
        return True
    return any(not valid_name(k) or _def_problem(v) for k, v in defs.items())


def _shape_problem(witness):
    if not isinstance(witness, dict) or set(witness) != _TOP_KEYS:
        return _refuse("WITNESS_INVALID", "closed key set")
    for text in _strings(witness):
        if _SOURCE_HINT.search(text):
            return _refuse("WITNESS_SOURCE_TEXT", "witness strings must be structural names or digests")
    cls = witness["ledger_class"]
    if cls not in LEDGER_CLASS_RULE or witness["source_kind"] not in (None,) + HINT_SOURCES:
        return _refuse("WITNESS_INVALID", "class or source kind")
    if witness["proof_side"] != PROOF_SIDE[cls]:
        return _refuse("WITNESS_INVALID", "proof side does not match the class")
    if not (isinstance(witness["module"], str) and _TOKEN.fullmatch(witness["module"])):
        return _refuse("WITNESS_INVALID", "module")
    if not valid_name(witness["old"]):
        return _refuse("WITNESS_INVALID", "old")
    if cls == "REMOVED":
        if witness["new"] is not None:
            return _refuse("WITNESS_INVALID", "REMOVED has no new name")
        names = (witness["old"],)
    else:
        if not valid_name(witness["new"]) or witness["new"] == witness["old"]:
            return _refuse("WITNESS_INVALID", "new")
        names = (witness["old"], witness["new"])
    if _side_problem(witness["from"], names) or _side_problem(witness["to"], names):
        return _refuse("WITNESS_INVALID", "side facts")
    return None


def _plain(d):
    if d["is_async"] or d["decorator_count"] or d["nested_scope"] or d["declares_global"]:
        return _refuse("NOT_PLAIN_DEF", "must be a top-level sync function without decorators or nested scopes")
    return None


def _single(side, name, kind) -> bool:
    return side["bindings"].get(name) == [kind]


def _global_ok(witness, name) -> bool:
    """A free name of a body is fine only as an identical import binding on both sides, or as an unshadowed builtin."""
    from_kinds = witness["from"]["bindings"].get(name, [])
    to_kinds = witness["to"]["bindings"].get(name, [])
    if from_kinds or to_kinds:
        return len(from_kinds) == 1 and from_kinds == to_kinds and from_kinds[0].startswith("import:")
    return name in _BUILTINS


def _check_s1(w):
    old, new, f, t = w["old"], w["new"], w["from"], w["to"]
    if w["source_kind"] not in HINT_SOURCES:
        return _refuse("LEDGER_SOURCE", "replacement needs an official docs or migration hint")
    if not (_single(f, old, "def") and _single(t, new, "def")):
        return _refuse("BINDING_CONFLICT", "old and new must each be bound once, as a def")
    if old in t["bindings"] or old in t["all_names"] or new in f["bindings"]:
        return _refuse("BINDING_CONFLICT", "old is still bound in the new version or new exists in the old")
    fo, ft = f["defs"].get(old), t["defs"].get(new)
    if fo is None or ft is None:
        return _refuse("DEF_MISSING", "definition not found")
    for d in (fo, ft):
        bad = _plain(d)
        if bad:
            return bad
    if fo["def_digest"] != ft["def_digest"] or fo["free_names"] != ft["free_names"]:
        return _refuse("S1_NOT_IDENTICAL", "bodies differ after normalising the name")
    if old not in ft["docstring_replaces"]:
        return _refuse("S1_HINT_MISSING", "new docstring does not name old")
    for name in fo["free_names"]:
        if not _global_ok(w, name):
            return _refuse("S1_GLOBAL_REF", "body reads a module-level name that is not a shared import or builtin")
    return "S1", {"module": w["module"], "old": old, "new": new}


def _check_s2(w):
    old, new, f, t = w["old"], w["new"], w["from"], w["to"]
    if not (_single(f, old, "def") and _single(t, old, "def") and _single(t, new, "def")):
        return _refuse("BINDING_CONFLICT", "old (both versions) and new (target) must each be one def")
    fo, to_old, to_new = f["defs"].get(old), t["defs"].get(old), t["defs"].get(new)
    if fo is None or to_old is None or to_new is None:
        return _refuse("DEF_MISSING", "definition not found")
    for d in (fo, to_old, to_new):
        bad = _plain(d)
        if bad:
            return bad
    if to_old["signature"] != to_new["signature"]:
        return _refuse("S2_SIGNATURE", "old must have the exact signature of new")
    if not (to_old["immutable_defaults"] and to_new["immutable_defaults"]):
        # defaults are evaluated once per definition: a call or a mutable literal is a different object in each
        return _refuse("S2_DEFAULT_NOT_IMMUTABLE", "defaults must be None, bool, int, float, str, bytes or tuples of those")
    fwd, sig = to_old["forward_shape"], to_old["signature"]
    if fwd is None or fwd["callee"] != new:
        return _refuse("S2_NOT_ALIAS", "old body is not a forward to new")
    if (fwd["positional"] != sig["positional"] or fwd["vararg"] != sig["vararg"]
            or fwd["keywords"] != sig["kwonly"] or fwd["kwarg"] != sig["kwarg"]):
        return _refuse("S2_SIGNATURE", "forward does not pass every parameter once in order")
    if to_new["forward_shape"] is not None:
        return _refuse("S2_CHAIN", "new is itself an alias")
    if old in to_new["free_names"]:
        return _refuse("S2_CYCLE", "new refers back to old")
    for name in to_old["free_names"]:
        if name == new:
            continue
        if name == "warnings" and t["bindings"].get("warnings") == [_WARNINGS_KIND]:
            continue
        if (name in WARN_CATEGORIES and name in _BUILTINS and name not in t["bindings"]
                and name not in f["bindings"]):
            continue
        return _refuse("S2_GLOBAL_REF", "alias body reads an unexpected module-level name")
    return "S2", {"module": w["module"], "old": old, "new": new}


def _check_s3(w):
    old, f, t = w["old"], w["from"], w["to"]
    if not _single(f, old, "def"):
        return _refuse("BINDING_CONFLICT", "old must be bound once, as a def, in the old version")
    if old in t["bindings"] or old in t["all_names"] or old in t["defs"]:
        return _refuse("S3_STILL_BOUND", "the new version still binds the name")
    fo = f["defs"].get(old)
    if fo is None:
        return _refuse("DEF_MISSING", "definition not found")
    bad = _plain(fo)
    if bad:
        return bad
    if fo["identity_shape"] is not True:
        return _refuse("S3_NOT_IDENTITY", "old is not `return p` over one parameter")
    return "S3", {"module": w["module"], "name": old}


_CHECKERS = {"S1": _check_s1, "S2": _check_s2, "S3": _check_s3}


def check_witness(witness):
    """Re-run every class condition on the witness facts. Pure. Returns the Proof or a Refusal."""
    bad = _shape_problem(witness)
    if bad is not None:
        return bad
    cls = witness["ledger_class"]
    for side in ("from", "to"):
        if witness[side]["star_import"]:
            return _refuse("STAR_IMPORT", f"{side} version has a star import")
        if "__getattr__" in witness[side]["bindings"]:
            return _refuse("MODULE_GETATTR", f"{side} version defines __getattr__")
        if witness[side]["nested_hits"]:
            return _refuse("NESTED_DEFINITION", f"{side} version defines a nested name that is watched")
    rule_name = LEDGER_CLASS_RULE[cls]
    result = _CHECKERS[rule_name](witness)
    if isinstance(result, Refusal):
        return result
    for side in ("from", "to"):  # the class proof reads the text only; reflection or a module statement defeats it
        if witness[side]["reflective"]:
            return _refuse(_REFLECTIVE_PREFIX[rule_name], f"{side} version uses a reflective name")
    for side in ("from", "to"):
        if witness[side]["statement_hits"]:
            return _refuse("MODULE_STATEMENT", f"{side} version has a module-level statement over the pair")
    rule, params = result
    return Proof(derived_class=DERIVED_NAME[rule], module=witness["module"], old=witness["old"],
                 new=witness["new"], derived_params=params, witness=copy.deepcopy(witness),
                 witness_digest=digest_obj(witness))
