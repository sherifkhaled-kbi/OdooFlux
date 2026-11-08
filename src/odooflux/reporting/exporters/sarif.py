"""SARIF 2.1.0 export (FR-005, REQ-REP-004, contracts/sarif-and-diff.md). Pure function of the model.

Deviations from the contract table, all because the model carries no such data: no endLine/endColumn (findings have a
start line and optional column only) and no ``properties.step`` on rules."""

import json
from urllib.parse import quote

from odooflux import __version__
from odooflux.reporting.options import sanitize_text

SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
LEVEL = {"CRITICAL": "error", "WARNING": "warning", "INFO": "note"}
REPORTED = ("OPEN", "NEEDS_REVIEW", "REJECTED")


def _evidence_id(item) -> str:
    return sanitize_text(item["id"] if isinstance(item, dict) else item)


def _evidence_url(item):
    if isinstance(item, dict) and str(item.get("url", "")).startswith("https://"):
        return item["url"]
    return None


def _location(module: dict, finding: dict) -> dict:
    uri = quote(f"{module['name']}/{finding['path']}".replace("\\", "/"), safe="/")
    physical = {"artifactLocation": {"uri": uri}}
    if finding["line"] >= 1:
        region = {"startLine": finding["line"]}
        if finding.get("column", 0) >= 1:
            region["startColumn"] = finding["column"]
        physical["region"] = region
    return {"physicalLocation": physical}


def export_sarif(report: dict, *, include_fixed: bool = False, exit_code=None) -> str:
    statuses = REPORTED + (("FIXED",) if include_fixed else ())
    pairs = [(m, f) for m in report["modules"] for f in m["findings"] if f["status"] in statuses]
    rules, index = [], {}
    for module, f in sorted(pairs, key=lambda p: (p[1]["rule_id"], p[0]["name"], p[1]["path"], p[1]["line"])):
        rid = sanitize_text(f["rule_id"])
        if rid not in index:
            index[rid] = len(rules)
            rule = {"id": rid, "shortDescription": {"text": sanitize_text(f["message"]) or rid},
                    "properties": {"evidence": [_evidence_id(e) for e in f.get("evidence", [])]}}
            for e in f.get("evidence", []):
                if _evidence_url(e):
                    rule["helpUri"] = _evidence_url(e)
                    break
            rules.append(rule)
    results = []
    for module, f in pairs:
        fixed = f["status"] == "FIXED"
        text = sanitize_text(f["message"])
        if f.get("suggestion") and not fixed:
            text += f" Action: {sanitize_text(f['suggestion'])}"
        props = {"status": f["status"], "module": module["name"]}
        if f.get("rejection_reason"):
            props["rejection_reason"] = sanitize_text(f["rejection_reason"])
        rid = sanitize_text(f["rule_id"])
        result = {"ruleId": rid, "ruleIndex": index[rid],
                  "level": "none" if fixed else LEVEL[f["severity"]],
                  "message": {"text": text},
                  "locations": [_location(module, f)],
                  "partialFingerprints": {"odoofluxFindingId": f["id"]},
                  "properties": props}
        if fixed:
            result["kind"] = "pass"
        results.append(result)

    notifications = [{"level": "error",
                      "message": {"text": sanitize_text(f"module {m['name']} BLOCKED: "
                                                        + ", ".join(m["status_reasons"]))}}
                     for m in report["modules"] if m["status"] == "BLOCKED"]
    invocation = {"executionSuccessful": exit_code in (None, 0, 1, 3)}
    if exit_code is not None:
        invocation["exitCode"] = exit_code
    if notifications:
        invocation["toolExecutionNotifications"] = notifications

    scope = report["verification_scope"]
    props = {"verificationScope": {"layersRun": scope["layers_run"], "layersUnavailable": scope["layers_unavailable"],
                                   "layersSkipped": scope.get("layers_skipped", []), "limits": scope.get("limits", [])},
             "runId": report["run"]["run_id"], "mode": report["run"]["mode"]}
    if report.get("provisional"):
        props["provisional"] = report["provisional"]
    document = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "OdooFlux", "version": report["run"].get("tool_version", __version__),
                                "rules": rules}},
            "results": results,
            "invocations": [invocation],
            "properties": props,
        }],
    }
    return json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


class SarifRenderer:
    key = "sarif"
    contract_version = 1

    def render(self, report: dict, **options) -> str:
        return export_sarif(report, **options)
