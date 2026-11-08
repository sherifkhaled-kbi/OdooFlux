"""AI pass orchestration: the provider proposes, the core validates and promotes per module (FR-015)."""

import os
from pathlib import Path

from odooflux.core.engine.apply import FileEdit  # noqa: F401  (type of edits handled below)
from odooflux.core.jobs.promote import audit_staged, promote_module, stage_edits
from odooflux.core.jobs.workspace import make_workspace
from odooflux.core.engine.rescan import resolved_by_rescan  # noqa: F401


def _writer(run, backup_enabled: bool):
    def write_module(module_path, edits, report) -> int:
        module_path = Path(module_path)
        work_root = make_workspace(run, module_path.name, module_path)
        stage_edits(work_root, module_path, edits)
        audit_staged(run, module_path, edits)
        ok, reason, written = promote_module(
            module_path, work_root, edits, run,
            backup_root=(run.backup_dir / module_path.name) if backup_enabled else None)
        if not ok:
            report.blocked, report.block_reason = True, reason
            return 0
        for edit in edits:
            for issue in edit.resolved:
                issue.fix_applied = True
            report.written_files.append(str(edit.dest))
        report.fixes_applied += len(edits)
        return len(edits)
    return write_module


def _step_factory(state: dict, options, registries):
    """Rescan steps built the way the planner builds them (bound run rules and knowledge rules included), so the AI
    re-scan sees the same findings as the analysis. None when the planner API is unavailable: the entry falls back to
    the legacy and plugin rules."""
    try:
        from odooflux.core.orchestrator.module_plan import _file_step
        from odooflux.core.orchestrator.run import build_run_context
        ctx = build_run_context(state, options, registries)
        return lambda path: _file_step(path, options.from_version, options.to_version, registries, ctx.rules,
                                       ctx.knowledge, ctx.steps, transform=False)
    except Exception:  # noqa: BLE001  planner internals are owned elsewhere; never break the run for a rescan helper
        return None


def _run_escalation(run, state: dict, options, registries, validate_text) -> int:
    """Provider-neutral escalation (feature 007): the registered ``ai-escalation`` entry does the work."""
    from odooflux.core.orchestrator.run import report_from_dict, report_to_dict
    reports = [report_from_dict(dict(m["report"])) for m in state["modules"]]
    module_paths = [Path(m["path"]) for m in state["modules"]]
    result = registries.ai_providers.get("ai-escalation").run(
        config=state["ai_config"], reports=reports, module_paths=module_paths, run=run, registries=registries,
        write_module=_writer(run, options.backup), validate_text=validate_text,
        from_version=options.from_version, to_version=options.to_version, environ=os.environ,
        step_factory=_step_factory(state, options, registries))
    for entry, report in zip(state["modules"], reports):
        entry["report"] = report_to_dict(report)
    state["ai_usage"] = result.usage
    return result.count


def run_ai_pass(run, state: dict, options, registries, *, api_key: str, validate_text) -> int:
    from odooflux.core.orchestrator.run import report_from_dict, report_to_dict
    if state.get("ai_config"):
        return _run_escalation(run, state, options, registries, validate_text)
    provider = registries.ai_providers.get("legacy-anthropic")
    reports = [report_from_dict(dict(m["report"])) for m in state["modules"]]
    module_paths = [Path(m["path"]) for m in state["modules"]]
    count = provider.fix_bundle(
        reports=reports, module_paths=module_paths, api_key=api_key,
        verbose=options.ai_verbose, run=run,
        write_module=_writer(run, options.backup), validate_text=validate_text)
    for entry, report in zip(state["modules"], reports):
        entry["report"] = report_to_dict(report)
    return count
