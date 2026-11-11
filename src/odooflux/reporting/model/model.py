"""Build report model v1 from the stored run state. Pure: same state in, same report out (FR-005)."""

from odooflux import __version__ as TOOL_VERSION
from odooflux.core.contracts.records import SEVERITIES, ValidationResult
from odooflux.utils.hashing import finding_id
from odooflux.core.orchestrator.status import PARTIAL_STATUS, StatusInputs, decide, serialise_layers, skipped

SCHEMA_VERSION = "1.0.0"
KNOWLEDGE_RELEASE_SCHEMA_VERSION = "1.1.0"  # used only when a knowledge_release object is supplied (OD-K4)
RUNTIME_NOT_REQUESTED = "runtime_not_requested"
STATIC_LIMIT = "Static run: L4 install and L5 behavioural tests were not executed, so runtime behaviour is unverified."


def _evidence(items, urls: dict) -> list:
    """Evidence ids become {id, url} when the caller knows the official URL; unknown ids stay plain (never invented)."""
    out = []
    for item in items:
        if isinstance(item, str) and item in urls:
            out.append({"id": item, "url": urls[item]})
        else:
            out.append(item)
    return out


FIX_CLASSES = ("certified", "experimental", "legacy")


def _fix_class(issue, experimental_ids):
    """Who would fix this finding. Only computed for a run that enabled experimental fixes (``experimental_ids``
    is not None); otherwise None and the finding carries no ``fix_class`` key at all."""
    if experimental_ids is None:
        return None
    maturity = getattr(issue, "maturity", "")
    if maturity == "FIX_ENABLED":
        return "certified"
    if maturity == "DETECT_ONLY" and issue.category in experimental_ids:
        return "experimental"
    if not maturity and issue.auto_fixable:
        return "legacy"
    return None


UNKNOWN = "UNKNOWN"  # the literal line of a finding whose source gives no line (never a guessed number)
DEFAULT_ACTION = "Review this finding and fix it by hand."


def _line(line):
    """The exact line of a finding, or UNKNOWN when the source gives none (line 0 is never invented)."""
    return line if isinstance(line, int) and not isinstance(line, bool) and line >= 1 else UNKNOWN


def known_column(issue) -> int:
    """The 1-based column of a finding, or 0 when its source gives none. A column is reported only together with a
    known line; a column is never derived from anything else (PA-5)."""
    column = getattr(issue, "column", 0)
    if _line(issue.line) == UNKNOWN or not isinstance(column, int) or isinstance(column, bool) or column < 1:
        return 0
    return column


def _not_fixed_reason(issue, *, refusal, blocked: str, mode: str, file_rejection=None):
    """Why an unresolved finding was not fixed automatically (AD-06). None for a FIXED finding. Precedence: the
    rejection itself, an experimental refusal, the absence of any fixer, the module block, the refused change of the
    finding's own file (``file_rejection``; the other files of the module were processed), then the run-level causes."""
    if issue.status == "FIXED":
        return None
    if issue.status == "REJECTED":
        return issue.rejection_reason
    if refusal:
        return refusal
    if issue.status == "NEEDS_REVIEW":
        return ("no automatic fixer for this rule (DETECT_ONLY)" if issue.maturity == "DETECT_ONLY"
                else "no automatic fixer for this finding")
    if blocked:
        return f"module blocked: {blocked}"
    if file_rejection:
        return f"fix rejected by validation ({file_rejection}); the finding stays open"
    if mode == "dry_run":
        return "not applied: a dry run writes no files"
    if mode == "analyze":
        return "not applied: an analyze run computes no edits"
    return "automatic fix not applied: the finding is still present after the fix pass"


def _refusals(entry: dict) -> dict:
    """(file, rule id, line) -> reason for every element an experimental rule refused in this module (AF-6)."""
    return {(rec["path"], rec["rule_id"], ref["line"]): ref["reason"]
            for rec in entry.get("experimental") or [] for ref in rec["refused"]}


def unresolved_fields(issue, rel: str, not_fixed) -> dict:
    """The AD-06 fields of an unresolved issue (location, reason, developer action); {} for a FIXED one. Shared by
    the model and the legacy outputs so every format names the same location, reason and action."""
    if issue.status == "FIXED":
        return {}
    return {"location": {"path": rel, "line": _line(issue.line), "column": known_column(issue) or UNKNOWN},
            "reason_not_fixed": not_fixed,
            "developer_action": issue.suggestion or DEFAULT_ACTION}


def legacy_unresolved(report, entry: dict = None, mode: str = "fix") -> list:
    """unresolved_fields for each issue of a legacy MigrationReport, aligned with report.issues. *entry* is the
    module's run-state record (experimental refusals and module rejections) and *mode* the run mode; without an
    entry the module rejections are those the report's own REJECTED issues carry."""
    root = report.module_path
    refusals = _refusals(entry) if entry is not None else {}
    refused = (entry or {}).get("refused_files") or {}
    blocked = report.block_reason if report.blocked else ""
    return [unresolved_fields(i, _relative(i.file, root),
                              _not_fixed_reason(i, refusal=refusals.get((i.file, i.category, i.line)),
                                                blocked=blocked, mode=mode, file_rejection=refused.get(i.file)))
            for i in report.issues]


def _finding(issue, module_root: str, urls: dict = None, fix_class: str = None,
             not_fixed: str = None) -> dict:
    rel = issue.file[len(module_root):].lstrip("/") if issue.file.startswith(module_root) else issue.file
    finding = {
        "id": finding_id(issue.category, rel, issue.line, issue.message),
        "rule_id": issue.category,
        "path": rel,
        "line": issue.line,
        "column": known_column(issue),  # integer; 0 = not known (the location field says UNKNOWN)
        "severity": issue.severity,
        "message": issue.message,
        "suggestion": issue.suggestion,
        "auto_fixable": issue.auto_fixable,
        "rejection_reason": issue.rejection_reason,
        "evidence": _evidence(issue.evidence, urls or {}),
        "status": issue.status,
        **({"maturity": issue.maturity, "review_required": issue.review_required}
           if getattr(issue, "maturity", "") else {}),  # knowledge-rule findings only (WS-E)
        **({"fix_class": fix_class} if fix_class is not None else {}),  # experimental runs only (AD-1)
    }
    finding.update(unresolved_fields(issue, rel, not_fixed))  # AD-06: location, reason, action when unresolved
    return finding


def edit_classes(entry: dict, issues: list, experimental_ids) -> dict:
    """{file path: fix_class} for the edited files of a module (experimental runs only)."""
    converted = {rec["path"] for rec in entry.get("experimental") or [] if rec.get("converted")}
    classes = {}
    for issue in issues:
        cls = _fix_class(issue, experimental_ids)
        if issue.auto_fixable and cls in ("certified", "legacy"):
            classes.setdefault(issue.file, cls)
    for path in converted:
        classes[path] = "experimental"
    return classes


def _classed_edits(edits: list, entry: dict, issues: list, experimental_ids) -> list:
    """The module's edit records; with experimental fixes enabled each carries its file's ``fix_class``."""
    if experimental_ids is None:
        return edits
    classes = edit_classes(entry, issues, experimental_ids)
    # an edit no knowledge rule accounts for comes from the legacy layer (manifest version, legacy XML fixers)
    return [{**edit, "fix_class": classes.get(edit["path"], "legacy")} for edit in edits]


def _relative(path: str, root: str) -> str:
    return path[len(root):].lstrip("/") if path.startswith(root) else path


def _experimental_summary(block: dict, entries: list, modules: list) -> dict:
    """summary.experimental: rules enabled, the conversions applied (with before and after), and the elements
    refused with their reason. Built from the per-module records the run stored (AD-1)."""
    applied, refused = [], []
    for entry, module in zip(entries, modules):
        for rec in entry.get("experimental") or []:
            rel = _relative(rec["path"], module["path"])
            for c in rec["converted"]:
                applied.append({"rule_id": rec["rule_id"], "path": rel, "line": c["line"],
                                "element": c["element"], "before": c["before"], "after": c["after"],
                                "fix_class": "experimental"})
            for r in rec["refused"]:
                refused.append({"rule_id": rec["rule_id"], "path": rel, "line": r["line"],
                                "element": r["element"], "reason": r["reason"]})
    return {"rules_enabled": list(block.get("rules") or []), "edits_applied": len(applied),
            "applied": applied, "refused": refused}


def _layer_results(entry: dict, report) -> dict:
    """ValidationResult per layer for this module. L4/L5 are not requested in a static run."""
    l1 = entry.get("layer1", "PASS")
    if report.blocked and "layer3" not in entry:
        # blocked before analysis (for example backup failed): L1/L2 never ran, so they are not PASS (F-REP-1)
        results = {1: skipped(1, "module_blocked_before_analysis"), 2: skipped(2, "module_blocked_before_analysis")}
    else:
        results = {1: ValidationResult(layer=1, outcome="PASS") if l1 == "PASS"
                   else ValidationResult(layer=1, outcome="FAIL", reason="edit_rejected"),
                   2: ValidationResult(layer=2, outcome="PASS")}
    l3 = entry.get("layer3")
    if l3:
        if l3["outcome"] == "PASS":
            results[3] = ValidationResult(layer=3, outcome="PASS", reason=l3.get("reason", ""))
        elif l3["outcome"] == "FAIL":
            results[3] = ValidationResult(layer=3, outcome="FAIL", reason=l3.get("reason") or "broken_reference")
        else:
            results[3] = ValidationResult(layer=3, outcome=l3["outcome"], reason=l3.get("reason") or "not_run")
    else:
        results[3] = ValidationResult(layer=3, outcome="UNAVAILABLE", reason="not_run")
    for n in (4, 5):  # recorded by the runtime/behaviour layers when they ran; otherwise not requested
        recorded = entry.get(f"layer{n}")
        if recorded:
            results[n] = ValidationResult(layer=n, outcome=recorded["outcome"], reason=recorded.get("reason", ""),
                                          coverage=recorded.get("coverage"))
        else:
            results[n] = skipped(n, RUNTIME_NOT_REQUESTED)
    return results


def attach_inventory(module: dict, entry: dict) -> dict:
    """Add the stored business-logic risk inventory (REQ-BIZ-001) to a module section when the run recorded one."""
    if entry.get("risk_inventory") is not None:
        module["risk_inventory"] = entry["risk_inventory"]
    return module


def module_result(entry: dict, report, plan_allow_unverified: bool, urls: dict = None,
                  experimental_ids=None, mode: str = "fix") -> dict:
    issues = report.issues
    refusals = _refusals(entry)
    rejections = [str(r) for r in entry.get("rejections", [])]
    blocked = report.block_reason if report.blocked else ""

    refused = (entry or {}).get("refused_files") or {}

    def finding(issue):
        reason = _not_fixed_reason(issue, refusal=refusals.get((issue.file, issue.category, issue.line)),
                                   blocked=blocked, mode=mode, file_rejection=refused.get(issue.file))
        return _finding(issue, root, urls, _fix_class(issue, experimental_ids), reason)

    open_items = [i for i in issues if i.status in ("OPEN", "NEEDS_REVIEW")]
    results = _layer_results(entry, report)
    layers = {n: r.outcome for n, r in results.items()}
    decision = decide(StatusInputs(
        layers=layers,
        l5_coverage=entry.get("l5_coverage"),
        plan_state="unverified_allowed" if plan_allow_unverified else "ok",
        tool_state="tool_error" if report.blocked else "ok",
        open_critical=sum(1 for i in open_items if i.severity == "CRITICAL"),
        open_review=sum(1 for i in open_items if i.severity != "INFO" and not i.auto_fixable),
        open_warning=sum(1 for i in open_items if i.severity == "WARNING" and i.auto_fixable)))
    reasons = list(decision.reasons)
    if report.blocked and report.block_reason:
        reasons.insert(0, report.block_reason)
    status = decision.status
    if rejections and not report.blocked and status != "BLOCKED":  # refused edits: incomplete, developer must act
        status = PARTIAL_STATUS
        reasons.insert(0, f"rejected_edits:{len(rejections)}")
    root = report.module_path
    module = attach_inventory({
        "name": entry["name"],
        "path": root,
        "blocked": report.blocked,
        "block_reason": report.block_reason,
        # only a fix run writes files, so only it can be reversed (PA-6); a dry run or analyze run wrote nothing
        "reversible": bool(report.reversible) and mode == "fix",
        "status": status,
        "status_reasons": reasons,
        "status_row": decision.row,
        "status_inputs_digest": decision.inputs_digest,
        "layers": serialise_layers(results),
        "processing": entry["status"],
        "findings": sorted((finding(i) for i in issues), key=lambda f: (f["path"], f["line"], f["rule_id"])),
        "edits": _classed_edits(entry.get("edits", []), entry, issues, experimental_ids),
        "fixes_applied": report.fixes_applied,
        "promoted_files": list(entry.get("promoted_files", [])),
        "rejections": list(entry.get("rejections", [])),
        "refused_files": _refused_files(entry, root),
    }, entry)
    for optional in ("runtime", "behavior"):  # present only when the runtime/behaviour layers recorded them
        if entry.get(optional) is not None:
            module[optional] = entry[optional]
    return module


def _refused_files(entry: dict, root: str) -> list:
    """Each file whose change the validator refused, with the reason and whether the file still changes: ``changes_kept``
    is true when the module's valid stages of that file are kept (written, or planned in a dry run). A file with
    ``changes_kept`` false keeps its original bytes (PA-3)."""
    kept = {edit["path"] for edit in entry.get("edits") or []}
    return [{"path": _relative(path, root), "reason": reason, "changes_kept": path in kept}
            for path, reason in (entry.get("refused_files") or {}).items()]


def _verification_scope(modules: list) -> dict:
    """Run-level scope: a layer ran when at least one module has a PASS or FAIL for it (FR-009)."""
    ran = {n for n in range(1, 6) for m in modules if m["layers"][f"L{n}"]["outcome"] in ("PASS", "FAIL")}
    unavailable = [n for n in range(1, 6) if n not in ran and n in (4, 5)]
    skipped_layers = [n for n in range(1, 6) if n not in ran and n not in unavailable]
    reasons = {}
    for n in unavailable + skipped_layers:
        recorded = [m["layers"][f"L{n}"]["reason"] for m in modules if m["layers"][f"L{n}"]["reason"]]
        reasons[f"L{n}"] = recorded[0] if recorded else (RUNTIME_NOT_REQUESTED if n in (4, 5) else "not_run")
    limits = [STATIC_LIMIT] if 4 in unavailable or 5 in unavailable else []
    for m in modules:
        reason = m["layers"]["L3"]["reason"]
        if m["layers"]["L3"]["outcome"] == "PASS" and "limits:" in reason:
            limits.append(f"L3 ({m['name']}): {reason.split('limits:', 1)[1].strip()}")
    outcomes = {f"L{n}": {o: sum(1 for m in modules if m["layers"][f"L{n}"]["outcome"] == o)
                          for o in ("PASS", "FAIL", "UNAVAILABLE", "SKIPPED")} for n in range(1, 6)}
    return {"layers_run": sorted(ran), "layers_unavailable": unavailable, "layers_skipped": skipped_layers,
            "reasons": reasons, "limits": limits, "layer_outcomes": outcomes}


def summarise(modules: list, dry_run: bool = False) -> dict:
    """Counts shown by every renderer (SC-002). Open means OPEN or NEEDS_REVIEW (what --fail-on tests).
    A dry run writes nothing: its edits are planned, so they are counted as ``planned`` and never as ``applied``."""
    by_status = {"open": 0, "fixed": 0, "rejected": 0, "needs_review": 0}
    totals = {"critical": 0, "warning": 0, "info": 0}
    open_totals = dict(totals)
    modules_by_status = {}
    for m in modules:
        modules_by_status[m["status"]] = modules_by_status.get(m["status"], 0) + 1
        for f in m["findings"]:
            by_status[f["status"].lower()] += 1
            totals[f["severity"].lower()] += 1
            if f["status"] in ("OPEN", "NEEDS_REVIEW"):
                open_totals[f["severity"].lower()] += 1
    return {"modules_by_status": modules_by_status, "findings": totals, "open_findings": open_totals,
            "findings_by_status": by_status,
            "edits": {"applied": 0 if dry_run else sum(m["fixes_applied"] for m in modules),
                      "rejected": sum(len(m["rejections"]) for m in modules),
                      **({"planned": sum(len(m["edits"]) for m in modules)} if dry_run else {})},
            "files_written": sum(len(m["promoted_files"]) for m in modules)}


def build_report(state: dict, reports: list, *, run_log_path: str = "", evidence_urls: dict = None,
                 ai_usage: dict = None, provisional: dict = None, warnings: list = None,
                 knowledge_release: dict = None) -> dict:
    """*evidence_urls* maps evidence ids to official URLs; *ai_usage* is the AI usage record when the run used AI;
    *provisional* ({"active": True, "labels": [...]}) marks a run that depended on a provisional corpus (ADR-019).
    *knowledge_release* is a plain mapping {release_id, digest, builtin, completeness, steps_covered} built by the
    caller from the knowledge handle; supplying it sets schema_version 1.1.0. All are optional and additive: omitting
    them keeps the original model byte for byte."""
    plan = state["plan"]
    writes = state["mode"] == "fix"
    experimental = state.get("experimental")  # present only for a run with --experimental-fixes (AD-1)
    experimental_ids = frozenset(experimental.get("rules") or []) if experimental is not None else None
    modules = [module_result(m, r, plan["allow_unverified"], evidence_urls, experimental_ids, mode=state["mode"])
               for m, r in zip(state["modules"], reports)]
    ai_usage = ai_usage if ai_usage is not None else state.get("ai_usage")
    if ai_usage is None:
        ai_usage = {"enabled": bool(state["options"].get("ai")), "consent": None, "providers": [],
                    "budget_events": [], "totals": {}}
    provisional = provisional if provisional is not None else state.get("provisional")
    report = {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": state["run_id"],
            "tool_version": TOOL_VERSION,
            "mode": state["mode"],
            "status": state["status"],
            "source": plan["source"],
            "target": plan["target"],
            "steps": plan["steps"],
            "plan_status": plan["status"],
            "plan_reasons": plan["reasons"],
            "cycles": plan["cycles"],
        },
        "modules": modules,
        "verification_scope": _verification_scope(modules),
        "recovery": {
            "run_log": run_log_path,
            # only a fix run writes files: analyze and dry runs have nothing to roll back (AD-06, D3)
            "rollback_cmd": f"odooflux rollback {state['run_id']}" if writes else None,
            "reversible": writes and bool(state["options"].get("backup", True)),
        },
        "severities": list(SEVERITIES),
        "summary": summarise(modules, dry_run=state["mode"] == "dry_run"),
        "ai_usage": ai_usage,
        "warnings": list(warnings or []),
    }
    if experimental is not None:
        report["summary"]["experimental"] = _experimental_summary(experimental, state["modules"], modules)
    if provisional:
        report["provisional"] = provisional
    if knowledge_release is not None:
        report["schema_version"] = KNOWLEDGE_RELEASE_SCHEMA_VERSION
        report["knowledge_release"] = dict(knowledge_release)
    return report
