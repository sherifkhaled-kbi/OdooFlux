"""Subcommands other than migrate: plan, rollback, resume, versions."""

import argparse
import os
import sys

from odooflux.cli.main import default_state
from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.recovery.resume import resume
from odooflux.core.recovery.rollback import rollback
from odooflux.discovery.modules import find_modules, module_ref
from odooflux.versions.graph.graph import normalize


def _modules(args):
    module_args = [args.module] if getattr(args, "module", None) else []
    module_args += list(getattr(args, "modules", None) or [])
    addons = [args.addons_path] if getattr(args, "addons_path", None) else []
    paths = find_modules(module_args, addons, [])
    return [module_ref(p, i) for i, p in enumerate(paths)]


def cmd_versions(graph, ctx) -> int:
    print(f"{'VERSION':<10}{'PYTHON MIN':<12}{'SUPPORT':<14}")
    for vid in graph.versions:
        version = ctx.registries.versions.get(vid)
        print(f"{vid:<10}{(version.python_min or '-'):<12}{version.support_status:<14}")
    print("\nSTEP                    RESEARCH")
    for step in _all_steps(graph):
        print(f"{step.id:<24}{step.research_status}")
    return 0


def _all_steps(graph):
    order = graph.versions
    out = []
    for a, b in zip(order, order[1:]):
        out.extend(graph.steps(a, b))
    return out


def cmd_plan(args, graph) -> int:
    source, target = normalize(args.source), normalize(args.target)
    plan = build_plan(graph, source, target, _modules(args), allow_unverified=args.allow_unverified)
    print(f"Plan {plan.source} -> {plan.target}: {plan.status}")
    for step in plan.steps:
        print(f"  step {step.id:<20} {step.research_status}")
    for module in plan.modules:
        print(f"  module [{module.order_index}] {module.name}  depends on: {', '.join(module.depends) or '-'}")
    for reason in plan.reasons:
        print(f"  ! {reason}")
    return 4 if plan.status == "BLOCKED" else 0


def cmd_rollback(args) -> int:
    results = rollback(default_state(args), args.run_id)
    for path, action, detail in results:
        print(f"{action:<9} {path}  ({detail})")
    conflicts = sum(1 for r in results if r[1] == "conflict")
    already = sum(1 for r in results if r[1] == "already")
    if already and already == len(results):
        print(f"Rollback of {args.run_id}: already rolled back")
        return 0
    print(f"Rollback of {args.run_id}: {len(results) - conflicts - already} restored, {conflicts} conflict(s)")
    return 1 if conflicts else 0


def cmd_resume(args, ctx) -> int:
    from odooflux.cli.migrate import make_validate_text, print_state_reports, _module_printer
    from odooflux.core.jobs.state_dir import RunDir
    state_dir = default_state(args)
    view = argparse.Namespace(fix=True, dry_run=False, no_color=True, show_fixed=False,
                              filter_severity=None, report=None, report_format="legacy")
    try:
        run = RunDir.open(state_dir, args.run_id)
        view.fix = run.read_state()["mode"] == "fix"
        state = resume(state_dir, args.run_id, ctx.registries,
                       api_key=args.api_key or os.environ.get("ANTHROPIC_API_KEY"),
                       validate_text=make_validate_text(ctx.registries),
                       on_module=_module_printer(view, len(run.read_state()["modules"])),
                       layer3=ctx.layer3)
    except Exception as exc:  # resume refusals are reported, not raised
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4
    return print_state_reports(state, run, view, ctx.registries)
