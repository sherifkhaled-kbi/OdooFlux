"""Per-tree caches for the analysis hot path (T014): many rules read the same ``ast`` tree in one run.

Trees are treated as immutable by every reader. The caches live on the tree object, so they die with it.
"""

import ast
from collections import OrderedDict

_NODES = "_odooflux_nodes"
_BUCKETS = "_odooflux_buckets"
_FILTERED = "_odooflux_filtered"
_PARSED: OrderedDict = OrderedDict()
_PARSED_SIZE = 96  # a module's Python files (about 30) across the analysis phases that read them


def parse(text: str, filename: str = "<unknown>"):
    """``ast.parse`` memoised by source text. Raises like ``ast.parse``; failures are not cached.

    ``filename`` only labels errors, so the tree of a successful parse is shared whatever name the caller used."""
    tree = _PARSED.get(text)
    if tree is None:
        tree = ast.parse(text, filename=filename)
        _PARSED[text] = tree
        if len(_PARSED) > _PARSED_SIZE:
            _PARSED.popitem(last=False)
    else:
        _PARSED.move_to_end(text)
    return tree


def all_nodes(tree) -> tuple:
    """Every node of ``tree`` in ``ast.walk`` order, computed once per tree object."""
    nodes = tree.__dict__.get(_NODES)
    if nodes is None:
        nodes = tuple(ast.walk(tree))
        setattr(tree, _NODES, nodes)
    return nodes


def _filtered(tree, types) -> tuple:
    """``isinstance`` filter over ``all_nodes``, memoised per tree and ``types`` (the result is an immutable tuple)."""
    cache = tree.__dict__.get(_FILTERED)
    if cache is None:
        cache = {}
        setattr(tree, _FILTERED, cache)
    hit = cache.get(types)
    if hit is None:
        hit = tuple(n for n in all_nodes(tree) if isinstance(n, types))
        cache[types] = hit
    return hit


def nodes_of(tree, types) -> tuple:
    """The nodes that are instances of ``types``, in ``ast.walk`` order. One class uses a per-tree bucket."""
    if isinstance(types, tuple):
        if len(types) != 1:
            return _filtered(tree, types)
        types = types[0]
    buckets = tree.__dict__.get(_BUCKETS)
    if buckets is None:
        buckets = {}
        for node in all_nodes(tree):
            buckets.setdefault(type(node), []).append(node)
        buckets = {key: tuple(items) for key, items in buckets.items()}
        setattr(tree, _BUCKETS, buckets)
    if types.__subclasses__():  # a base class such as ast.stmt: fall back to the exact filter
        return _filtered(tree, types)
    return buckets.get(types, ())
