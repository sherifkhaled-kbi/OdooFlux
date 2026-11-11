"""AI pass orchestration: the provider proposes, the core validates and promotes per module (FR-015)."""

import os
from pathlib import Path

from odooflux.core.engine.apply import FileEdit  # noqa: F401  (type of edits handled below)
from odooflux.core.jobs.promote import audit_staged, promote_module, stage_edits
from odooflux.core.jobs.workspace import make_workspace
from odooflux.core.engine.rescan import resolved_by_rescan  # noqa: F401
from odooflux.core.orchestrator.status import PARTIAL_STATUS

# Issues an AI edit refusal leaves on a report (ai/integration.py, ai/providers/legacy_anthropic.py).
AI_REFUSAL_CATEGORIES = ("Fix Rejected", "AI Rejected")


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


def _issue_ids(reports: list) -> list:
    """Identity of each report's issues before the AI pass: only issues added by the pass are AI refusals."""
    return [{id(issue) for issue in report.issues} for report in reports]


def _record_refusals(entry: dict, report, before: set) -> None:
    """Record the refusals the AI pass added to this module (same shape as the deterministic pass): the reason in
    entry["rejections"], the file in entry["refused_files"]. A refused file is never counted as applied; the module is
    PARTIAL when it has a refusal and is not blocked. Refusals already on the report (module_plan) are not repeated."""
    fresh = [i for i in report.issues
             if id(i) not in before and i.rejection_reason and i.category in AI_REFUSAL_CATEGORIES]
    if not fresh:
        return
    for issue in fresh:
        entry.setdefault("rejections", []).append(issue.rejection_reason)
        entry.setdefault("refused_files", {})[issue.file] = issue.rejection_reason
    if not report.blocked:
        entry["migration_status"] = PARTIAL_STATUS


def _run_escalation(run, state: dict, options, registries, validate_text) -> int:
    """Provider-neutral escalation (feature 007): the registered ``ai-escalation`` entry does the work."""
    from odooflux.core.orchestrator.run import report_from_dict, report_to_dict
    reports = [report_from_dict(dict(m["report"])) for m in state["modules"]]
    module_paths = [Path(m["path"]) for m in state["modules"]]
    before = _issue_ids(reports)
    result = registries.ai_providers.get("ai-escalation").run(
        config=state["ai_config"], reports=reports, module_paths=module_paths, run=run, registries=registries,
        write_module=_writer(run, options.backup), validate_text=validate_text,
        from_version=options.from_version, to_version=options.to_version, environ=os.environ,
        step_factory=_step_factory(state, options, registries))
    for entry, report, seen in zip(state["modules"], reports, before):
        _record_refusals(entry, report, seen)
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
    before = _issue_ids(reports)
    count = provider.fix_bundle(
        reports=reports, module_paths=module_paths, api_key=api_key,
        verbose=options.ai_verbose, run=run,
        write_module=_writer(run, options.backup), validate_text=validate_text)
    for entry, report, seen in zip(state["modules"], reports, before):
        _record_refusals(entry, report, seen)
        entry["report"] = report_to_dict(report)
    return count
