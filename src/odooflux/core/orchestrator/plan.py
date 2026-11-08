"""Plan builder: steps, module order, and BLOCKED handling (FR-007, FR-008, FR-018)."""

from dataclasses import replace

from odooflux.core.contracts import UnsupportedVersionError
from odooflux.core.contracts.records import MigrationPlan
from odooflux.dependencies.graph import topo_order


def build_plan(graph, source: str, target: str, modules: list, *, allow_unverified: bool = False) -> MigrationPlan:
    """*source* and *target* must already be normalised (``M.0``). An unknown target raises."""
    reasons, blocked_steps, out_of_range = [], [], False
    try:
        steps = graph.steps(source, target)
    except UnsupportedVersionError:
        if source not in graph.versions and source < graph.minimum:
            steps, out_of_range = [], True
            reasons.append(f"source {source} is below the supported range "
                           f"{graph.minimum}–{graph.versions[-1]}")
        else:
            raise
    unresearched = graph.unresearched(steps)
    for step in unresearched:
        blocked_steps.append(step.id)
        if not allow_unverified:
            reasons.append(f"unresearched step {step.id} ({step.research_status}); "
                           "use --allow-unverified to run it")
    order, cycles, blocked = topo_order({m.name: m.depends for m in modules})
    by_name = {m.name: m for m in modules}
    ordered = [replace(by_name[name], order_index=index) for index, name in enumerate(order)]
    for cycle in cycles:
        reasons.append("dependency cycle: " + ", ".join(cycle))
    refused = out_of_range or (bool(unresearched) and not allow_unverified)
    return MigrationPlan(
        source=source, target=target, steps=steps, modules=ordered,
        status="BLOCKED" if refused else "READY", reasons=reasons,
        blocked_steps=blocked_steps, blocked_modules=blocked, cycles=cycles,
        allow_unverified=allow_unverified)
