"""Report model outputs of the migrate command (feature 009): validation of the output options, JSON/SARIF/HTML/diff
files, the ``--ui`` terminal summary and the exit code. Kept out of migrate.py so that file stays small. Renderers are
reached only through the renderer registry: this core package never imports a renderer adapter."""

import shutil
import sys
from pathlib import Path

import json

from odooflux.cli.exit_codes import ExitPolicy, UsageError, exit_code, legacy_exit_code, parse_fail_on_status
from odooflux.reporting.model.model import build_report
from odooflux.reporting.model.output_paths import check_output_paths

OUTPUT_OPTIONS = (("--report", "report"), ("--sarif", "sarif"), ("--html", "html"), ("--diff", "diff"))


def _get(args, name, default=None):
    return getattr(args, name, default)


def validate_outputs(args, registries, write_mode: bool, scanned_roots: list):
    """Return a usage-error message, or None. Runs before any processing (exit 2)."""
    try:
        ExitPolicy(fail_on=_get(args, "fail_on", "critical"),
                   fail_on_status=parse_fail_on_status(_get(args, "fail_on_status")))
    except UsageError as exc:
        return str(exc)
    fmt = _get(args, "report_format", "legacy")
    if _get(args, "report") and fmt not in ("legacy",) and fmt not in registries.renderers:
        return f"--report-format {fmt!r} is not a registered renderer"
    if _get(args, "report") and fmt in ("diff", "diff-index"):
        return "use --diff FILE for the unified diff; --report-format diff needs the original files"
    if _get(args, "diff") and write_mode and _get(args, "no_backup"):
        return "--diff needs the pre-run backup to read the original files; remove --no-backup"
    if _get(args, "max_findings_per_file") is not None and _get(args, "max_findings_per_file") < 1:
        return "--max-findings-per-file must be at least 1"
    return check_output_paths({opt: _get(args, attr) for opt, attr in OUTPUT_OPTIONS}, scanned_roots)


def _write(path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def finish(state: dict, run, args, registries, reports: list, legacy_done: bool) -> int:
    """Write the requested outputs from the model and return the exit code."""
    view = state
    if state.get("knowledge_unverified"):  # a step not covered by the active release: same input as an unverified plan
        view = {**state, "plan": {**state["plan"], "allow_unverified": True}}
    document = build_report(view, reports, run_log_path=str(run.log.path),
                            warnings=state.get("knowledge_warnings"),
                            knowledge_release=state.get("knowledge_release"))
    write_mode = state["mode"] == "fix"
    try:
        policy = ExitPolicy(fail_on=state["options"]["fail_on"],
                            fail_on_status=parse_fail_on_status(_get(args, "fail_on_status")))
    except UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    mode = _get(args, "exit_codes") or ("v1" if _get(args, "fail_on_status") is not None else "legacy")
    if mode == "v1":
        code = exit_code(document, policy, write_mode=write_mode)
    else:  # D-10: characterised mapping for one minor release
        code = legacy_exit_code(reports, write_mode, state["options"]["fail_on"],
                                sum(r.rejected_count for r in reports))

    report_path, fmt = _get(args, "report"), _get(args, "report_format", "legacy")
    renderers = registries.renderers
    if report_path and not legacy_done and fmt != "legacy":
        renderer = renderers.get(fmt)
        if getattr(renderer, "deprecation_notice", None):
            print(renderer.deprecation_notice, file=sys.stderr)
        _write(report_path, renderer.render(document))
        run.audit.append("report_written", Path(report_path).name, details={"format": fmt})
        print(f"  Report saved → {report_path} ({fmt})")
    if _get(args, "sarif"):
        _write(args.sarif, renderers.get("sarif").render(
            document, include_fixed=_get(args, "sarif_include_fixed", False), exit_code=code))
        run.audit.append("report_written", Path(args.sarif).name, details={"format": "sarif"})
        print(f"  SARIF saved → {args.sarif}")
    if _get(args, "html"):
        _write(args.html, renderers.get("html").render(document))
        run.audit.append("report_written", Path(args.html).name, details={"format": "html"})
        print(f"  HTML report saved → {args.html}")
    if _get(args, "diff"):
        source = {"backup_dir": run.backup_dir} if write_mode else {}
        try:
            patch = renderers.get("diff").render(document, **source)
            index_text = renderers.get("diff-index").render(document, **source)
        except RuntimeError as exc:  # the diff exporter's OriginalUnavailableError
            print(f"ERROR: --diff: {exc}", file=sys.stderr)
            return 4
        _write(args.diff, patch)
        _write(f"{args.diff}.index.json", index_text)
        index = json.loads(index_text)
        run.audit.append("report_written", Path(args.diff).name, details={"format": "diff"})
        print(f"  Diff saved → {args.diff} ({len(index['files'])} file(s); index {args.diff}.index.json)")
        if state["mode"] == "analyze":
            print("  Note: analyze runs do not compute edits, so the diff is empty; "
                  "use --fix (or --fix --dry-run) to export the kept edits.")
        for excluded in index["excluded_modules"]:
            print(f"  Diff excludes module {excluded['module']}: {'; '.join(excluded['reasons'])}")
    ui = _get(args, "ui")
    if ui:
        text = renderers.get("terminal").render(
            document, ui=ui, is_tty=sys.stdout.isatty(), no_color=bool(_get(args, "no_color")),
            width=max(shutil.get_terminal_size((80, 24)).columns, 20),
            max_findings_per_file=_get(args, "max_findings_per_file", 20) or 20,
            show_fixed=bool(_get(args, "show_fixed")), min_severity=_get(args, "filter_severity") or "INFO")
        print(text, end="")
    return code
