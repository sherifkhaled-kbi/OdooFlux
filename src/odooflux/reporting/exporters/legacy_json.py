"""Legacy JSON from the report model (T017, D-10): same fields as the P1 characterised writer
(reporting/model/legacy_json.py), kept for one minor release. ``timestamp`` is the export time and
``elapsed_seconds`` is 0.0 because the deterministic model carries neither."""

import json
from datetime import datetime

DEPRECATION_NOTICE = ("WARNING: --report-format legacy-json is deprecated (D-10) and will be removed after one minor "
                      "release. Use --report-format json (schema v1) instead.")


def _major(version: str) -> int:
    return int(str(version).split(".")[0])


def _issue(module: dict, f: dict, full: bool) -> dict:
    root = module["path"].rstrip("/")
    out = {"file": f"{root}/{f['path']}" if f["path"] else root, "line": f["line"], "severity": f["severity"],
           "category": f["rule_id"], "message": f["message"], "suggestion": f["suggestion"],
           "auto_fixable": f["auto_fixable"], "fix_applied": f["status"] == "FIXED"}
    if full:
        out.update(status=f["status"], evidence=[e["id"] if isinstance(e, dict) else e for e in f["evidence"]],
                   rejection_reason=f["rejection_reason"])
    return out


def _counts(module: dict) -> dict:
    fs = module["findings"]
    not_fixed = [f for f in fs if f["status"] != "FIXED"]
    return {"critical": sum(1 for f in not_fixed if f["severity"] == "CRITICAL"),
            "warnings": sum(1 for f in not_fixed if f["severity"] == "WARNING"),
            "info": sum(1 for f in not_fixed if f["severity"] == "INFO"),
            "fixable": sum(1 for f in not_fixed if f["auto_fixable"]),
            "fixes_applied": module["fixes_applied"],
            "open": len(not_fixed), "fixed": len(fs) - len(not_fixed)}


def export_legacy_json(report: dict) -> str:
    run = report["run"]
    from_v, to_v = _major(run["source"]), _major(run["target"])
    modules = report["modules"]
    now = datetime.now().isoformat()
    if len(modules) == 1:
        m = modules[0]
        summary = _counts(m)
        summary.update(rejected=sum(1 for f in m["findings"] if f["status"] == "REJECTED"), blocked=m["blocked"],
                       reversible=m["reversible"], elapsed_seconds=0.0)
        data = {"module_path": m["path"], "from_version": from_v, "to_version": to_v, "timestamp": now,
                "summary": summary, "issues": [_issue(m, f, True) for f in m["findings"]]}
    else:
        per = [_counts(m) for m in modules]
        data = {"timestamp": now, "total_modules": len(modules),
                "summary": {"critical": sum(c["critical"] for c in per), "warnings": sum(c["warnings"] for c in per),
                            "info": sum(c["info"] for c in per),
                            "fixes_applied": sum(c["fixes_applied"] for c in per),
                            "open": sum(c["open"] for c in per), "fixed": sum(c["fixed"] for c in per),
                            "total_elapsed_seconds": 0.0},
                "modules": [{"module_path": m["path"], "from_version": from_v, "to_version": to_v,
                             "summary": dict(c, elapsed_seconds=0.0),
                             "issues": [_issue(m, f, False) for f in m["findings"]]}
                            for m, c in zip(modules, per)]}
    return json.dumps(data, indent=2)


class LegacyJsonRenderer:
    key = "legacy-json"
    contract_version = 1
    deprecation_notice = DEPRECATION_NOTICE  # the CLI prints it to stderr when this format is requested

    def render(self, report: dict, **options) -> str:
        return export_legacy_json(report)
