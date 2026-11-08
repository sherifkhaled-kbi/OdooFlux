"""Scenario run states for feature 009 tests and the golden report generator.

Every scenario is a run *state* (the orchestrator's stored form) plus build_report keyword arguments. The golden
JSON models in tests/golden_fixtures/reports/ are produced from these by build_goldens.py. The content is
synthetic and carries no migration truth: it only exercises the reporting mechanics (ADR-019, provisional
corpus rules do not apply because no Odoo behaviour is asserted).
"""

import copy

from ._setup import SRC  # noqa: F401

EVIDENCE_URLS = {"EV-110": "https://github.com/odoo/odoo/blob/17.0/odoo/addons/base/models/ir_ui_view.py",
                 "EV-109": "https://www.odoo.com/documentation/18.0/developer/reference/backend/views.html"}


def issue(file, line, severity, category, message, *, auto_fixable=True, fix_applied=False,
          evidence=("EV-110",), rejection_reason="", suggestion="Apply the documented replacement"):
    return {"file": file, "line": line, "severity": severity, "category": category, "message": message,
            "suggestion": suggestion, "auto_fixable": auto_fixable, "fix_applied": fix_applied,
            "evidence": list(evidence), "rejection_reason": rejection_reason}


def module(name, issues, *, status="DONE", layer1="PASS", layer3=None, rejections=(), edits=(),
           promoted=(), blocked=False, block_reason="", fixes=0, **extra):
    root = f"/work/{name}"
    entry = {"name": name, "path": root, "status": status, "layer1": layer1,
             "rejections": list(rejections), "promoted_files": list(promoted), "edits": list(edits),
             "report": {"module_path": root, "from_version": 17, "to_version": 18,
                        "issues": [dict(i, file=root + "/" + i["file"]) for i in issues],
                        "fixes_applied": fixes, "elapsed_seconds": 0.0, "timestamp": "t", "reversible": True,
                        "blocked": blocked, "block_reason": block_reason, "actions": [],
                        "planned_files": [], "written_files": []}}
    if layer3 is not False:  # False = the module was blocked before analysis, so no L3 was recorded
        entry["layer3"] = layer3 if layer3 is not None else {"outcome": "PASS", "reason": "", "coverage": "full"}
    entry.update(extra)
    return entry


def state(modules, *, mode="dry_run", run_id="run-golden", ai=False, steps=("17.0->18.0",),
          plan_status="READY", allow_unverified=False):
    return {"schema": "odooflux.runstate/1", "run_id": run_id, "mode": mode, "status": "COMPLETED",
            "options": {"backup": True, "fail_on": "critical", "ai": ai},
            "plan": {"source": "17.0", "target": "18.0", "steps": list(steps), "status": plan_status,
                     "reasons": [], "cycles": [], "allow_unverified": allow_unverified},
            "modules": modules, "ai_done": ai}


def _edit(path, before, after, start=10):
    return {"path": path, "dest": path, "spans": [{"start": start, "end": start + len(before),
                                                  "before": before, "after": after}]}


HOSTILE = "\x1b[31mRED\x1b[0m <script>alert(1)</script> \x07bell \x1b]0;title\x07 end"


def scenarios() -> dict:
    s = {}
    s["static_validated"] = (state([module(
        "kbi_sale_approval",
        [issue("views/v.xml", 3, "INFO", "17-18.xml.note", "informational note", auto_fixable=False),
         issue("views/v.xml", 9, "WARNING", "17-18.xml.tree-to-list", "tree renamed", fix_applied=True),
         issue("models/a.py", 5, "WARNING", "17-18.py.attrs", "attr changed", fix_applied=True),
         issue("models/a.py", 7, "WARNING", "17-18.py.attrs", "attr changed", fix_applied=True)],
        fixes=3, edits=[_edit("/work/kbi_sale_approval/views/v.xml", "<tree>", "<list>")])]),
        {"evidence_urls": EVIDENCE_URLS})
    s["needs_review"] = (state([module(
        "kbi_hr_extension",
        [issue("views/hr.xml", 42, "WARNING", "17-18.xml.attrs-removed", "attrs domain not convertible",
               auto_fixable=False, evidence=("EV-109", "EV-110")),
         issue("views/hr.xml", 57, "WARNING", "17-18.xml.tree-to-list", "tree renamed", fix_applied=True)],
        fixes=1)]), {"evidence_urls": EVIDENCE_URLS})
    s["failed"] = (state([module(
        "kbi_stock_custom",
        [issue("models/stock.py", 118, "CRITICAL", "17-18.py.api-removed", "removed API used",
               auto_fixable=False, rejection_reason=""),
         issue("models/stock.py", 203, "CRITICAL", "17-18.py.field", "protected identifier",
               rejection_reason="protected_identifier_changed (field 'qty_done' renamed)")],
        status="FAILED", layer1="FAIL", rejections=["validation_failed:L1-python (IndentationError line 119)",
                                                    "protected_identifier_changed (field 'qty_done' renamed)"])]),
        {})
    s["blocked"] = (state([module(
        "kbi_old_portal", [], status="BLOCKED", blocked=True, block_reason="backup failed",
        layer3=False)]), {})
    s["install_verified"] = (state([module(
        "kbi_install_ok", [issue("models/m.py", 2, "WARNING", "17-18.py.x", "fixed", fix_applied=True)],
        fixes=1, layer4={"outcome": "PASS", "reason": "", "coverage": None},
        runtime={"image": "odoo:18.0", "digest": "sha256:" + "ab" * 32, "logs_path": "logs/l4.log",
                 "errors": []})], mode="fix"), {})
    s["verified_success"] = (state([module(
        "kbi_verified", [], layer4={"outcome": "PASS", "reason": "", "coverage": None},
        layer5={"outcome": "PASS", "reason": "", "coverage": "full"}, l5_coverage="full",
        runtime={"image": "odoo:18.0", "digest": "sha256:" + "cd" * 32, "logs_path": "logs/l4.log",
                 "errors": []},
        behavior={"comparisons": [{"test": "t1", "source": "pass", "target": "pass"}],
                  "summary": {"pass_both": 1, "regression": 0, "fixed": 0, "fail_both": 0,
                              "target_only": 0, "source_only": 0}})]), {})
    s["ai_enabled"] = (state([module(
        "kbi_ai_mod", [issue("models/m.py", 4, "WARNING", "ai:provider/model", "ai proposed",
                             auto_fixable=False)])], mode="fix", ai=True),
        {"ai_usage": {"enabled": True, "consent": True,
                      "providers": [{"name": "anthropic", "model": "<configured-model>", "requests": 7,
                                     "input_tokens": 12410, "output_tokens": 2980, "cached_tokens": 8200,
                                     "estimated": False, "cost": None}],
                      "budget_events": ["job budget 50000 tok: 15390 used"],
                      "totals": {"requests": 7, "input_tokens": 12410, "output_tokens": 2980}}})
    s["provisional"] = (state([module(
        "kbi_prov", [issue("views/v.xml", 1, "WARNING", "17-18.xml.x", "fixed", fix_applied=True)], fixes=1)],
        steps=("17.0->18.0",)), {"provisional": {"active": True, "labels": [
            "17.0->18.0 rules validated only against the PROVISIONAL corpus; not approved migration truth"]}})
    s["hostile"] = (state([module(
        "kbi_hostile",
        [issue("views/<b>x</b>.xml", 1, "CRITICAL", "r.\x1b[31mbad", HOSTILE, auto_fixable=False,
               suggestion=HOSTILE, evidence=("EV-110", "EV-<img src=x onerror=alert(1)>"))],
        status="FAILED", layer1="FAIL", rejections=[HOSTILE])]), {"evidence_urls": EVIDENCE_URLS})
    mixed_modules = [
        module("kbi_sale_approval", [issue("views/v.xml", 3, "INFO", "17-18.xml.note", "note", auto_fixable=False),
                                     issue("views/v.xml", 9, "WARNING", "17-18.xml.tree-to-list", "t",
                                           fix_applied=True),
                                     issue("views/v.xml", 11, "WARNING", "17-18.xml.tree-to-list", "t2")],
               fixes=1, edits=[_edit("/work/kbi_sale_approval/views/v.xml", "<tree>", "<list>")]),
        module("kbi_hr_extension", [issue("views/hr.xml", 42, "WARNING", "17-18.xml.attrs-removed", "attrs",
                                          auto_fixable=False),
                                    issue("views/hr.xml", 50, "WARNING", "17-18.xml.x", "bad edit",
                                          rejection_reason="validation_failed:L1-xml")], rejections=["validation_failed:L1-xml"],
               layer1="FAIL"),
        module("kbi_stock_custom", [issue("models/stock.py", 118, "CRITICAL", "17-18.py.api", "api",
                                          auto_fixable=False)]),
        module("kbi_old_portal", [], status="BLOCKED", blocked=True, block_reason="workspace failed",
               layer3={"outcome": "UNAVAILABLE", "reason": "not_run", "coverage": None}),
    ]
    s["mixed"] = (state(mixed_modules, mode="fix"), {"evidence_urls": EVIDENCE_URLS})
    return copy.deepcopy(s)
