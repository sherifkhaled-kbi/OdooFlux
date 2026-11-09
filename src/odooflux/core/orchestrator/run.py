"""Run execution: per-module processing, checkpoints after every module, promotion, AI pass.

The same pipeline serves a fresh run and a resume. Reports are derived from the stored state, so
an interrupted-and-resumed run ends with the same report as an uninterrupted one (FR-014).
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from odooflux.analyzers.risk_inventory import inventory_module
from odooflux.core.jobs.promote import audit_staged, backup_module, promote_module, stage_edits
from odooflux.core.jobs.workspace import make_workspace
from odooflux.core.orchestrator.ai_pass import run_ai_pass
from odooflux.core.orchestrator import knowledge_rules, run_inputs
from odooflux.core.orchestrator.module_plan import plan_module
from odooflux.dependencies.scan import scan_run_dependencies
from odooflux.dependencies.unified import FINDING_ID
from odooflux.discovery.modules import module_ref
from odooflux.rules.shared.legacy_rules import SEVERITY_WARNING, Issue, MigrationReport
from odooflux.utils.hashing import digest_tree

DONE_STATES = ("PROMOTED", "DONE", "BLOCKED", "FAILED")


class SourceChangedError(RuntimeError):
    """Resume refused: a module changed since the run started (contracts/recovery.md)."""


@dataclass
class RunOptions:
    from_version: int
    to_version: int
    mode: str  # analyze | dry_run | fix
    backup: bool = True
    fail_on: str = "critical"
    ai: bool = False
    ai_verbose: bool = False
    allow_unverified: bool = False
    module_paths: list = field(default_factory=list)
    addons_paths: list = field(default_factory=list)
    skip: list = field(default_factory=list)
    enable_rules: list = field(default_factory=list)  # opt-in run-input rule ids (FR-019)

    @property
    def writes(self) -> bool:
        return self.mode == "fix"

    @property
    def computes_edits(self) -> bool:
        """Fix mode promotes the edits; a dry run computes the same edits in memory and writes nothing."""
        return self.mode in ("fix", "dry_run")


def report_to_dict(report: MigrationReport) -> dict:
    """Shallow copy: every field is a JSON value or a list of them (asdict's deep copy was the
    dominant cost of checkpointing)."""
    data = dict(vars(report))
    data["issues"] = [dict(vars(i)) for i in report.issues]
    return data


def report_from_dict(data: dict) -> MigrationReport:
    issues = [Issue(**i) for i in data.pop("issues", [])]
    report = MigrationReport(**data)
    report.issues = issues
    return report


def new_state(run, plan, options: RunOptions, modules: list) -> dict:
    return {
        "schema": "odooflux.runstate/1",
        "run_id": run.run_id,
        "mode": options.mode,
        "status": "RUNNING",
        "options": {**asdict(options), "reversible": options.backup},
        "plan": {"source": plan.source, "target": plan.target, "steps": [s.id for s in plan.steps],
                 "status": plan.status, "reasons": plan.reasons, "cycles": plan.cycles,
                 "allow_unverified": plan.allow_unverified},
        "modules": [{
            "name": m.name, "path": m.path, "status": "PENDING",
            "source_digest": ([list(item) for item in digest_tree(Path(m.path))]
                              if options.writes else []),
            "promoted_files": [],
            "report": None, "rejections": [], "layer1": "PASS",
        } for m in modules],
        "ai_done": False,
    }


def layer3_for(path: Path, to_version: int, report, layer3) -> dict:
    """Run L3 dependency integrity (REQ-VAL-003, injected by the composition root) and record its findings."""
    if layer3 is None:
        return {"outcome": "UNAVAILABLE", "reason": "no_layer3_adapter", "coverage": None}
    findings, result = layer3(path, to_version)
    for f in findings:
        report.issues.append(Issue(
            file=str(path / f.path), line=f.line, severity=f.severity, category=f.rule_id,
            message=f.message, suggestion=f.suggestion, auto_fixable=False))
    return {"outcome": result.outcome, "reason": result.reason or "", "coverage": result.coverage}


@dataclass
class RunContext:
    """Once-per-run inputs: bound run-input rules, dependency findings by manifest path, INFO gaps."""

    rules: list = field(default_factory=list)
    knowledge: list = field(default_factory=list)  # KnowledgeRule objects selected by the plan's steps
    steps: list = field(default_factory=list)  # rule step keys, e.g. ["17-18", "18-19"]
    dependency_findings: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)
    coverage_messages: dict = field(default_factory=dict)  # module name -> KB-COVERAGE-INCOMPLETE text (feature 012)


def build_run_context(state: dict, options: RunOptions, registries) -> RunContext:
    """Bind opted-in rules with the planned target (FR-017) and scan dependencies across all modules (FR-020)."""
    ctx = RunContext()
    withheld = (state.get("knowledge_coverage") or {}).get("withheld") or {}
    ctx.coverage_messages = {name: record["message"] for name, record in withheld.items()}
    ctx.dependency_findings, ctx.gaps = scan_run_dependencies(
        [m["path"] for m in state["modules"]], options.from_version, options.to_version)
    binder = getattr(registries, "run_rule_binder", None)
    if binder is not None and hasattr(binder, "for_steps"):
        ctx.steps = (knowledge_rules.step_keys(state["plan"]["steps"]) if state["plan"].get("steps")
                     else knowledge_rules.step_keys_for_range(options.from_version, options.to_version))
        ctx.knowledge, knowledge_gaps = binder.for_steps(run_inputs.run_params_for(state["plan"]["target"]),
                                                         ctx.steps)
        ctx.gaps = ctx.gaps + knowledge_gaps
    if options.enable_rules:
        binder = getattr(registries, "run_rule_binder", None)
        if binder is None:
            ctx.gaps.append("INFO: run-input rules skipped: no rule binder is configured")
        else:
            rules, gaps, _unknown = binder(run_inputs.run_params_for(state["plan"]["target"]),
                                           list(options.enable_rules))
            ctx.rules, ctx.gaps = rules, ctx.gaps + gaps
    return ctx


def _add_run_context(report, path: Path, run_ctx: RunContext) -> None:
    for gap in run_ctx.gaps:
        report.issues.append(Issue(file=str(path), line=0, severity="INFO", category="Run Input Gap",
                                   message=gap, suggestion="Supply the missing run input or core list data",
                                   auto_fixable=False))
    for manifest, items in run_ctx.dependency_findings.items():
        if Path(manifest).parent != path:
            continue
        for f in items:
            report.issues.append(Issue(file=f.path, line=f.line, severity=f.severity, category=f.rule_id,
                                       message=f.message, suggestion=f.suggestion, auto_fixable=False,
                                       evidence=list(f.evidence)))
    if path.name in run_ctx.coverage_messages:
        report.issues.append(Issue(
            file=str(path), line=0, severity=SEVERITY_WARNING, category=FINDING_ID,
            message=run_ctx.coverage_messages[path.name],
            suggestion="Add the missing module inventory or dependency to the active knowledge release, then re-run",
            auto_fixable=False))


def _process_module(run, entry: dict, options: RunOptions, registries, layer3=None, run_ctx=None) -> None:
    name, path = entry["name"], Path(entry["path"])
    report = MigrationReport(module_path=str(path), from_version=options.from_version,
                             to_version=options.to_version, reversible=run.reversible)
    backup_root = run.backup_dir / name
    if options.writes and options.backup:
        if backup_module(path, run) is None:
            report.blocked, report.block_reason = True, "backup failed"
            run.log.append("module_blocked", module=name, reason=report.block_reason)
            entry.update(status="BLOCKED", report=report_to_dict(report))
            return
    analysis, edits = plan_module(path, options.from_version, options.to_version, registries,
                                  compute_edits=options.computes_edits and not entry.get("fixes_withheld"),
                                  run_rules=run_ctx.rules if run_ctx else (),
                                  knowledge=run_ctx.knowledge if run_ctx else (),
                                  knowledge_steps=run_ctx.steps if run_ctx else ())
    report.issues = analysis.issues
    report.actions = analysis.actions
    if run_ctx is not None:
        _add_run_context(report, path, run_ctx)
    entry["layer3"] = layer3_for(path, options.to_version, report, layer3)
    entry["risk_inventory"] = inventory_module(path)
    rejections = [e for e in edits if e.rejection]
    entry["layer1"] = "FAIL" if rejections else "PASS"
    for edit in rejections:
        run.log.append("edit_rejected", module=name, path=str(edit.path),
                       rules=sorted({i.category for i in edit.issues}), reason=edit.rejection)
        entry["rejections"].append(edit.rejection)
    if options.mode == "dry_run" and not rejections:
        report.planned_files = [str(e.dest) for e in edits]
    entry["edits"] = [{"path": str(e.path), "dest": str(e.dest),
                       "spans": [{"start": s.start, "end": s.end, "before": s.before, "after": s.after}
                                 for s in e.edits]}
                      for e in edits if not e.rejection]
    if options.writes and edits and not rejections:
        try:
            work_root = make_workspace(run, name, path)
            stage_edits(work_root, path, edits)
            audit_staged(run, path, edits)
        except OSError as exc:
            report.blocked, report.block_reason = True, f"workspace failed: {exc}"
            run.log.append("module_blocked", module=name, reason=report.block_reason)
            entry.update(status="BLOCKED", report=report_to_dict(report))
            return
        ok, reason, written = promote_module(
            path, work_root, edits, run,
            backup_root=backup_root if options.backup else None)
        if ok:
            for edit in edits:
                for issue in edit.resolved:
                    issue.fix_applied = True
                report.written_files.append(str(edit.dest))
                if edit.dest != edit.path:
                    report.actions = [[True, t] if t.endswith(f"{edit.path.name} -> {edit.dest.name}")
                                      else [d, t] for d, t in report.actions]
            report.fixes_applied += len(edits)
            entry["promoted_files"] = written
            entry["status"] = "PROMOTED"
        else:
            report.blocked, report.block_reason = True, reason
            unwritten = [str(e.dest) for e in edits if str(e.dest) not in written]
            report.issues.append(Issue(
                file=str(path), line=0, severity="CRITICAL", category="Write Failed",
                message=(f"{reason}. Written: {', '.join(written) or 'none'}. "
                         f"Unwritten: {', '.join(unwritten) or 'none'}."),
                suggestion="Check disk space and file permissions, then re-run", auto_fixable=False))
            entry["status"] = "BLOCKED"
    elif rejections:
        entry["status"] = "FAILED"
        report.block_reason = "edit rejected by validation"
    else:
        entry["status"] = "DONE"
    entry["report"] = report_to_dict(report)


def run_pipeline(run, state: dict, registries, *, api_key=None, validate_text=None, hook=None, on_module=None,
                 layer3=None, jobs: int = 1, incremental=None):
    """Process every module that is not finished, checkpointing after each one.

    ``jobs`` > 1 (analysis and dry run) and ``incremental`` (an index, read-only modes) hand the module loop to
    ``orchestrator.parallel.process_modules`` (T012, T013); fix mode is always serial."""
    options = RunOptions(**{k: v for k, v in state["options"].items() if k in RunOptions.__dataclass_fields__})
    state["status"] = "RUNNING"
    run.write_state(state)
    run_ctx = build_run_context(state, options, registries)
    pooled = not options.writes and (incremental is not None or jobs > 1)
    if pooled:
        from odooflux.core.orchestrator.parallel import process_modules
        process_modules(run, state, options, registries, layer3, run_ctx, jobs=jobs, index=incremental,
                        on_module=on_module, hook=hook)
    for entry in [] if pooled else state["modules"]:
        if entry["status"] in DONE_STATES:
            continue
        if entry["status"] in ("PENDING", "WORKING") and options.writes:
            current = [list(item) for item in digest_tree(Path(entry["path"]))]  # JSON turns tuples into lists
            if current != entry["source_digest"]:
                raise SourceChangedError(f"module {entry['name']} changed since the run started")
        entry["status"] = "WORKING"
        if options.writes:
            run.write_state(state)
        _process_module(run, entry, options, registries, layer3, run_ctx)
        run.save_module(entry)
        if options.writes:  # checkpoints matter for resume; analysis runs are never resumed
            run.write_state(state)
        if on_module is not None:
            on_module(entry)
        if hook is not None:
            hook(entry["name"])
    if options.ai and not state["ai_done"] and options.writes:
        withheld = [m for m in state["modules"] if m.get("fixes_withheld")]
        if withheld:  # feature 012: AI proposes no edit for a module whose fixes are withheld
            ai_state = dict(state, modules=[m for m in state["modules"] if not m.get("fixes_withheld")])
            if ai_state["modules"]:
                run_ai_pass(run, ai_state, options, registries, api_key=api_key, validate_text=validate_text)
            if "ai_usage" in ai_state:
                state["ai_usage"] = ai_state["ai_usage"]
        else:
            run_ai_pass(run, state, options, registries, api_key=api_key, validate_text=validate_text)
        for entry in state["modules"]:
            run.save_module(entry)
        state["ai_done"] = True
        run.write_state(state)
    state["status"] = "COMPLETED"
    run.write_state(state)
    counts: dict = {}
    for entry in state["modules"]:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    run.audit.append("run_finished", run.run_id, details={"mode": options.mode, "modules": counts})
    return state


def reports_from_state(state: dict) -> list:
    return [report_from_dict(dict(m["report"])) for m in state["modules"] if m["report"]]


def rejected_count(state: dict) -> int:
    return sum(len(m["rejections"]) for m in state["modules"])


def module_refs(paths: list):
    return [module_ref(Path(p), i) for i, p in enumerate(paths)]
