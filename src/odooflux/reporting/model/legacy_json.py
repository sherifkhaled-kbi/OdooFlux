"""Legacy JSON report shape, kept for characterisation parity (D-10)."""

import json
from datetime import datetime
from pathlib import Path

from odooflux.reporting.model.model import known_column, legacy_unresolved
from odooflux.rules.shared.legacy_rules import (
    MigrationReport, SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING)

def save_json_report(report: MigrationReport, output_path: Path, *, entry: dict = None, mode: str = "fix"):
    data = {
        "module_path": report.module_path,
        "from_version": report.from_version,
        "to_version": report.to_version,
        "timestamp": report.timestamp,
        "summary": {
            "critical": report.critical_count,
            "warnings": report.warning_count,
            "info": report.info_count,
            "fixable": report.fixable_count,
            "fixes_applied": report.fixes_applied,
            "open": sum(1 for i in report.issues if not i.fix_applied),
            "fixed": sum(1 for i in report.issues if i.fix_applied),
            "rejected": report.rejected_count,
            "blocked": report.blocked,
            "reversible": report.reversible and mode == "fix",  # PA-6: a dry run wrote nothing
            "elapsed_seconds": round(report.elapsed_seconds, 2),
        },
        "issues": [
            {
                "file": i.file,
                "line": i.line,
                "column": known_column(i),  # PA-5: 0 = not known
                "severity": i.severity,
                "category": i.category,
                "message": i.message,
                "suggestion": i.suggestion,
                "auto_fixable": i.auto_fixable,
                "fix_applied": i.fix_applied,
                "status": i.status,
                "evidence": i.evidence,
                "rejection_reason": i.rejection_reason,
                **fields,  # AD-06 (unresolved issues only): location, reason_not_fixed, developer_action
            }
            for i, fields in zip(report.issues, legacy_unresolved(report, entry, mode))
        ]
    }
    output_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(f"  JSON report saved → {output_path}")


# ─────────────────────────────────────────────


def save_combined_json_report(reports: list, output_path: Path, *, entries: list = None, mode: str = "fix"):
    entries = entries or [None] * len(reports)  # aligned with reports: each module's run-state record
    data = {
        "timestamp": datetime.now().isoformat(),
        "total_modules": len(reports),
        "summary": {
            "critical":      sum(r.critical_count for r in reports),
            "warnings":      sum(r.warning_count  for r in reports),
            "info":          sum(r.info_count     for r in reports),
            "fixes_applied": sum(r.fixes_applied  for r in reports),
            "open":          sum(sum(1 for i in r.issues if not i.fix_applied) for r in reports),
            "fixed":         sum(sum(1 for i in r.issues if i.fix_applied)     for r in reports),
            "total_elapsed_seconds": round(sum(r.elapsed_seconds for r in reports), 2),
        },
        "modules": [
            {
                "module_path": r.module_path,
                "from_version": r.from_version,
                "to_version": r.to_version,
                "summary": {
                    "critical": r.critical_count,
                    "warnings": r.warning_count,
                    "info":     r.info_count,
                    "fixable":  r.fixable_count,
                    "fixes_applied": r.fixes_applied,
                    "open": sum(1 for i in r.issues if not i.fix_applied),
                    "fixed": sum(1 for i in r.issues if i.fix_applied),
                    "elapsed_seconds": round(r.elapsed_seconds, 2),
                },
                "issues": [
                    {
                        "file": i.file,
                        "line": i.line,
                        "column": known_column(i),  # PA-5: 0 = not known
                        "severity": i.severity,
                        "category": i.category,
                        "message": i.message,
                        "suggestion": i.suggestion,
                        "auto_fixable": i.auto_fixable,
                        "fix_applied":  i.fix_applied,
                        **fields,  # AD-06 (unresolved issues only): location, reason_not_fixed, developer_action
                    }
                    for i, fields in zip(r.issues, legacy_unresolved(r, entry, mode))
                ],
            }
            for r, entry in zip(reports, entries)
        ],
    }
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Combined JSON report saved → {output_path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

_FAIL_ON_SEVERITY = {"critical": SEVERITY_CRITICAL, "warning": SEVERITY_WARNING,
                    "info": SEVERITY_INFO}


