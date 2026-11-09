"""The migrate command: options, plan, run, legacy-shaped output, exit codes (contracts/cli.md)."""

import os
import sys
from pathlib import Path

from odooflux.cli.ai_options import resolve_ai
from odooflux.cli.main import DEPRECATED_API_KEY, default_state
from odooflux.cli.report_outputs import finish as finish_outputs, validate_outputs
from odooflux.core.contracts import UnsupportedVersionError
from odooflux.core.engine.step_runner import validate_output
from odooflux.core.jobs.state_dir import RunDir, check_state_dir
from odooflux.core.orchestrator.incremental import open_index
from odooflux.core.orchestrator.parallel import can_parallelise, resolve_jobs
from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.orchestrator.provisional import provisional_for
from odooflux.core.orchestrator.run import (
    RunOptions, SourceChangedError, new_state, report_from_dict, reports_from_state, run_pipeline)
from odooflux.dependencies.unified import FINDING_ID, UnifiedError, migration_coverage, withheld_records
from odooflux.discovery.modules import find_modules, module_ref
from odooflux.knowledge.loader import RELEASE_TREE
from odooflux.knowledge.release.coverage_check import check_transition_coverage
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.resolver import resolve_knowledge
from odooflux.reporting.model.legacy_json import save_combined_json_report, save_json_report
from odooflux.reporting.model.legacy_terminal import print_combined_summary, print_report
from odooflux.reporting.model.model import build_report
from odooflux.versions.graph.graph import normalize

SEVERITY_FLOOR = {"critical": "CRITICAL", "warning": "WARNING", "info": "INFO"}


def resolve_migrate_knowledge(args):
    """The one knowledge resolution of a migrate run (contracts/migration-integration.md "Resolution").

    Returns (handle, None), or (None, message) when the active release is corrupt, missing, or refused by
    --require-complete-kb. The caller exits 4 (blocked) and never falls back to the built-in tree (REQ-KAP-036)."""
    try:
        handle = resolve_knowledge(getattr(args, "kb_home", None),
                                   require_complete=bool(getattr(args, "require_complete_kb", False)))
    except KnowledgeReleaseError as exc:
        return None, f"ERROR: knowledge release: {exc}"
    return handle, None


def knowledge_release_block(handle) -> dict:
    """The report's `knowledge_release` object (contracts/migration-integration.md "Report"); built-in included."""
    return {"release_id": handle.release_id, "digest": handle.digest, "builtin": handle.builtin,
            "completeness": handle.completeness,
            "steps_covered": [{"step": step, "completeness": status} for step, status in sorted(handle.steps.items())]}


def compute_exit_code(reports: list, write_mode: bool, fail_on: str, rejected: int) -> int:
    """0 clean · 1 open findings at or above --fail-on · 3 rejected edit in write mode · 4 tool error
    or blocked module. Precedence 4 > 3 > 1 > 0. Argparse's 2 is never returned here."""
    if any(r.blocked for r in reports):
        return 4
    if write_mode and rejected:
        return 3
    if fail_on != "none" and any(r.open_findings(SEVERITY_FLOOR[fail_on]) for r in reports):
        return 1
    return 0


def make_validate_text(registries):
    return lambda path, text: validate_output(registries.validators.all(), path, text)


def _module_printer(args, total: int):
    counter = {"n": 0}

    def printer(entry: dict) -> None:
        counter["n"] += 1
        report = report_from_dict(dict(entry["report"]))
        print(f"\n  [{counter['n']}/{total}] {entry['name']}")
        print(f"        Path: {entry['path']}")
        if report.blocked:
            print(f"        BLOCKED ({report.block_reason})")
        else:
            print(f"        done  [crit={report.critical_count} warn={report.warning_count} "
                  f"info={report.info_count}"
                  + (f" fixed={report.fixed_count}" if args.fix else "") + "]")
        for done, text in report.actions:
            print(f"        [{'done' if done else 'planned'}] {text}")
        if args.fix and args.dry_run:
            names = ", ".join(Path(p).name for p in report.planned_files)
            print(f"        Dry run: would change {len(report.planned_files)} file(s)"
                  + (f": {names}" if names else ""))
        print_report(report, no_color=args.no_color, show_fixed=args.show_fixed,
                     filter_severity=args.filter_severity)
    return printer


def _usage(message: str) -> int:
    print(f"usage error: {message}", file=sys.stderr)
    return 2


def run_migrate(args, ctx, graph, failures) -> int:
    if os.environ.get("NO_COLOR"):  # https://no-color.org
        args.no_color = True
    if args.backup and args.no_backup:
        return _usage("--backup and --no-backup are mutually exclusive")
    try:
        from_v, to_v = normalize(args.from_version), normalize(args.to_version)
    except UnsupportedVersionError as exc:
        return _usage(str(exc))
    if int(from_v.split(".")[0]) >= int(to_v.split(".")[0]):
        return _usage(f"--from-version ({args.from_version}) must be less than --to-version ({args.to_version})")
    if args.ai_fix and not args.fix:
        print("WARNING: --ai-fix without --fix means regex fixes are skipped. Adding --fix automatically.")
        args.fix = True
    write_mode = args.fix and not args.dry_run
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    do_ai = args.ai_fix and write_mode
    if do_ai and not api_key:
        return _usage("--ai-fix requires an Anthropic API key: pass --api-key or set "
                      "the ANTHROPIC_API_KEY environment variable")
    ai_cfg, ai_error = resolve_ai(args, os.environ)
    if not ai_error and ai_cfg.enabled:
        ai_error = ctx.registries.ai_providers.get("ai-escalation").check_config(ai_cfg.to_dict())
    if ai_error:
        return _usage(ai_error)
    new_ai = ai_cfg.enabled and write_mode  # --ai transmits nothing outside --fix (no dry run, no analyze)

    module_args = [args.module] if args.module else []
    module_args += list(args.modules or [])
    addons = [args.addons_path] if args.addons_path else []
    findings: list = []
    paths = find_modules(module_args, addons, findings)
    if args.skip:
        skip = set(args.skip)
        paths = [p for p in paths if p.name not in skip]
    invalid = [p for p in paths if not p.is_dir()]
    if invalid:
        for p in invalid:
            print(f"ERROR: Not a valid directory: {p}")
        return 4
    if not paths:
        print("ERROR: No valid addon directories found.")
        return 4
    refs = [module_ref(p, i) for i, p in enumerate(paths)]
    problem = validate_outputs(args, ctx.registries, write_mode, list(paths) + [Path(a).resolve() for a in addons])
    if problem:
        return _usage(problem)

    try:
        plan = build_plan(graph, from_v, to_v, refs, allow_unverified=args.allow_unverified)
    except UnsupportedVersionError as exc:
        return _usage(str(exc))
    if plan.status == "BLOCKED":
        for reason in plan.reasons:
            print(f"BLOCKED: {reason}")
        return 4

    handle = ctx.knowledge  # the single handle of this run (set by main.run from resolve_migrate_knowledge)
    unified = None  # feature 012: Community + Enterprise coverage from the active release's inventories
    if not handle.builtin:
        try:
            unified = migration_coverage(Path(handle.root) / RELEASE_TREE, from_v, to_v,
                                         {ref.name: list(ref.depends) for ref in refs})
        except UnifiedError as exc:
            print(f"ERROR: knowledge inventory: {exc}")
            return 4

    state_dir = default_state(args)
    scanned = list(paths) + [Path(a).resolve() for a in addons]
    problem = check_state_dir(state_dir, scanned)
    if problem:
        print(f"ERROR: {problem}. Choose a --state-dir outside the modules and addons path.")
        return 4

    try:
        jobs = resolve_jobs(getattr(args, "jobs", 1))
    except ValueError as exc:
        return _usage(str(exc))
    binder = getattr(ctx.registries, "run_rule_binder", None)
    unknown_rules = [r for r in (getattr(args, "enable_rule", None) or [])
                     if binder is None or r not in binder.known()]
    if unknown_rules:
        return _usage(f"--enable-rule: not a run-input rule: {', '.join(unknown_rules)}")

    mode = "fix" if write_mode else ("dry_run" if args.fix else "analyze")
    options = RunOptions(
        from_version=int(from_v.split(".")[0]), to_version=int(to_v.split(".")[0]), mode=mode,
        backup=not args.no_backup, fail_on=args.fail_on, ai=do_ai or new_ai, ai_verbose=args.ai_verbose,
        allow_unverified=args.allow_unverified, module_paths=[str(p) for p in paths],
        addons_paths=[str(a) for a in addons], skip=list(args.skip),
        enable_rules=list(getattr(args, "enable_rule", None) or []))
    run = RunDir.create(state_dir, reversible=options.backup, with_backup=write_mode)
    state = new_state(run, plan, options, plan.modules)
    label = provisional_for(options.module_paths, options.from_version, options.to_version,
                            flag=bool(getattr(args, "provisional_corpus", False)))
    if label:
        state["provisional"] = label
    if new_ai:
        state["ai_config"] = ai_cfg.to_dict()  # no credential is ever stored
    coverage = check_transition_coverage(handle, [s.id for s in plan.steps])
    state["knowledge_release"] = knowledge_release_block(handle)
    withheld = withheld_records(unified) if unified is not None else {}
    if withheld:  # only when an inventory exists and a module is INCOMPLETE; otherwise the state is unchanged
        state["knowledge_coverage"] = {"withheld": withheld}
        for entry in state["modules"]:
            if entry["name"] in withheld:
                entry["fixes_withheld"] = True
    if coverage.warnings:
        state["knowledge_warnings"] = list(coverage.warnings)
    if not coverage.verified:
        state["knowledge_unverified"] = True  # the report caps the run like an unverified plan (no new status)
    run.write_state(state)

    run.audit.add_secrets([api_key])
    run.audit.append("config_loaded", "cli", details={
        "mode": mode, "from_version": from_v, "to_version": to_v, "jobs": jobs, "backup": options.backup,
        "ai": bool(ai_cfg.enabled), "ai_provider": ai_cfg.provider or None, "ai_model": ai_cfg.model or None,
        "incremental": bool(getattr(args, "incremental", False)), "modules": len(refs)})
    run.audit.append("plan_created", "plan", details={"status": plan.status, "steps": [s.id for s in plan.steps],
                                                       "modules": len(plan.modules)})

    print(f"\n  Odoo Migration Tool  v{from_v} → {to_v}")
    print(f"  Modules : {len(refs)}")
    print("  Fix     : " + ("YES (writes enabled)" if write_mode else
                            "DRY RUN (planned edits only, nothing written)" if args.fix else
                            "NO (analyze only)"))
    print(f"  Target  : Odoo {to_v}")
    print(f"  AI Fix  : {'YES (legacy-anthropic)' if do_ai else 'NO'}")
    if ai_cfg.enabled:
        print(f"  AI      : {'ON' if new_ai else 'enabled, inactive (needs --fix without --dry-run)'} "
              f"(provider {ai_cfg.provider}, model {ai_cfg.model}; consent given)")
        grants = "; ".join(f"{p}={','.join(c)}" for p, c in sorted(ai_cfg.authorizations.items())) or "none"
        print(f"  AI auth : {grants}" + ("; EXTERNAL TRANSMISSION DISABLED (kill switch)" if ai_cfg.kill_switch else ""))
    print(f"  Run     : {run.run_id}  (state: {state_dir})")
    if not handle.builtin:
        print(f"  Knowledge: release {handle.release_id} (digest {handle.digest})")
    for warning in coverage.warnings:
        print(f"  Knowledge: {warning}")
    if withheld:
        print(f"  Coverage: {len(withheld)} module(s) INCOMPLETE; fixes withheld ({FINDING_ID})")
    if write_mode:
        print("  Backup  : " + ("verified before each module's first write" if options.backup
                                else "NONE (--no-backup): this run is not reversible"))
    if args.dry_run:
        print("  Mode    : DRY RUN")
    if args.skip:
        print(f"  Skipped : {', '.join(args.skip)}")
    for spec, error in failures:
        print(f"  Plugin  : {spec} not loaded ({error})")
    if args.api_key:
        print(DEPRECATED_API_KEY)
    index = None
    if getattr(args, "incremental", False):
        if write_mode:
            print("  Incremental: ignored in fix mode (the index serves read-only runs only)")
        else:
            index = open_index(state_dir)
    if jobs > 1 and not can_parallelise(mode, jobs):
        print(f"  Jobs    : {jobs} requested; this run is serial (fix mode and platforms without fork run serially)")

    try:
        run_pipeline(run, state, ctx.registries, api_key=api_key,
                     validate_text=make_validate_text(ctx.registries),
                     on_module=_module_printer(args, len(refs)), layer3=ctx.layer3, jobs=jobs, incremental=index)
    except SourceChangedError as exc:
        print(f"ERROR: {exc}")
        return 4
    if index is not None:
        print(f"\n  Incremental: {index.stats['analyzed']} analysed, {index.stats['skipped']} skipped, "
              f"{index.parsed} files parsed")
    return print_state_reports(state, run, args, ctx.registries)


def print_state_reports(state: dict, run, args, registries) -> int:
    """Final output from stored state: combined summary, report files, exit code."""
    reports = reports_from_state(state)
    if len(reports) > 1:
        print_combined_summary(reports, no_color=getattr(args, "no_color", True))
    report_path = getattr(args, "report", None)
    legacy = bool(report_path) and getattr(args, "report_format", "legacy") == "legacy"
    if legacy:
        if len(reports) == 1:
            save_json_report(reports[0], Path(report_path))
        else:
            save_combined_json_report(reports, Path(report_path))
        run.audit.append("report_written", Path(report_path).name, details={"format": "legacy"})
    return finish_outputs(state, run, args, registries, reports, legacy)
