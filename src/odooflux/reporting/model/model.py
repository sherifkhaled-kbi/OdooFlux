"""Build report model v1 from the stored run state. Pure: same state in, same report out (FR-005)."""

from odooflux import __version__ as TOOL_VERSION
from odooflux.core.contracts.records import SEVERITIES, ValidationResult
from odooflux.utils.hashing import finding_id
from odooflux.core.orchestrator.status import StatusInputs, decide, serialise_layers, skipped

SCHEMA_VERSION = "1.0.0"
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


def _finding(issue, module_root: str, urls: dict = None) -> dict:
    rel = issue.file[len(module_root):].lstrip("/") if issue.file.startswith(module_root) else issue.file
    return {
        "id": finding_id(issue.category, rel, issue.line, issue.message),
        "rule_id": issue.category,
        "path": rel,
        "line": issue.line,
        "column": 0,
        "severity": issue.severity,
        "message": issue.message,
        "suggestion": issue.suggestion,
        "auto_fixable": issue.auto_fixable,
        "rejection_reason": issue.rejection_reason,
        "evidence": _evidence(issue.evidence, urls or {}),
        "status": issue.status,
        **({"maturity": issue.maturity, "review_required": issue.review_required}
           if getattr(issue, "maturity", "") else {}),  # knowledge-rule findings only (WS-E)
    }


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


def module_result(entry: dict, report, plan_allow_unverified: bool, urls: dict = None) -> dict:
    issues = report.issues
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
    root = report.module_path
    module = attach_inventory({
        "name": entry["name"],
        "path": root,
        "blocked": report.blocked,
        "block_reason": report.block_reason,
        "reversible": report.reversible,
        "status": decision.status,
        "status_reasons": reasons,
        "status_row": decision.row,
        "status_inputs_digest": decision.inputs_digest,
        "layers": serialise_layers(results),
        "processing": entry["status"],
        "findings": sorted((_finding(i, root, urls) for i in issues),
                           key=lambda f: (f["path"], f["line"], f["rule_id"])),
        "edits": entry.get("edits", []),
        "fixes_applied": report.fixes_applied,
        "promoted_files": list(entry.get("promoted_files", [])),
        "rejections": list(entry.get("rejections", [])),
    }, entry)
    for optional in ("runtime", "behavior"):  # present only when the runtime/behaviour layers recorded them
        if entry.get(optional) is not None:
            module[optional] = entry[optional]
    return module


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


def summarise(modules: list) -> dict:
    """Counts shown by every renderer (SC-002). Open means OPEN or NEEDS_REVIEW (what --fail-on tests)."""
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
            "edits": {"applied": sum(m["fixes_applied"] for m in modules),
                      "rejected": sum(len(m["rejections"]) for m in modules)},
            "files_written": sum(len(m["promoted_files"]) for m in modules)}


def build_report(state: dict, reports: list, *, run_log_path: str = "", evidence_urls: dict = None,
                 ai_usage: dict = None, provisional: dict = None, warnings: list = None) -> dict:
    """*evidence_urls* maps evidence ids to official URLs; *ai_usage* is the AI usage record when the run used AI;
    *provisional* ({"active": True, "labels": [...]}) marks a run that depended on a provisional corpus (ADR-019).
    All four are optional and additive: omitting them keeps the original model."""
    plan = state["plan"]
    modules = [module_result(m, r, plan["allow_unverified"], evidence_urls)
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
            "rollback_cmd": f"odooflux rollback {state['run_id']}",
            "reversible": bool(state["options"].get("backup", True)),
        },
        "severities": list(SEVERITIES),
        "summary": summarise(modules),
        "ai_usage": ai_usage,
        "warnings": list(warnings or []),
    }
    if provisional:
        report["provisional"] = provisional
    return report
