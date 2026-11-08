"""Topological order over module dependencies. External dependencies are ignored; cycles are reported."""

import heapq


def _strongly_connected(nodes, edges):
    index, low, on_stack, stack, out, counter = {}, {}, set(), [], [], [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in edges.get(v, ()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(sorted(comp))

    for v in sorted(nodes):
        if v not in index:
            visit(v)
    return out


def topo_order(deps: dict):
    """
    *deps* maps module name -> iterable of dependency names.
    Returns (order, cycles, blocked): order lists modules dependencies-first with ties broken by
    name; cycles lists each cycle's members; blocked lists modules that cannot be ordered
    (cycle members and everything depending on them).
    """
    names = set(deps)
    edges = {n: sorted(d for d in deps[n] if d in names) for n in names}
    indegree = {n: 0 for n in names}
    dependents = {n: [] for n in names}
    for n, ds in edges.items():
        for d in ds:
            indegree[n] += 1
            dependents[d].append(n)
    heap = [n for n in names if indegree[n] == 0]
    heapq.heapify(heap)
    order = []
    while heap:
        n = heapq.heappop(heap)
        order.append(n)
        for m in dependents[n]:
            indegree[m] -= 1
            if indegree[m] == 0:
                heapq.heappush(heap, m)
    remaining = sorted(names - set(order))
    cycles = [c for c in _strongly_connected(remaining, edges)
              if len(c) > 1 or c[0] in edges.get(c[0], ())]
    return order, cycles, remaining
