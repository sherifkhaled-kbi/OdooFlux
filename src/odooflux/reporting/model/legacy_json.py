"""Legacy JSON report shape, kept for characterisation parity (D-10)."""

import json
from datetime import datetime
from pathlib import Path

from odooflux.rules.shared.legacy_rules import (
    MigrationReport, SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING)

def save_json_report(report: MigrationReport, output_path: Path):
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
            "reversible": report.reversible,
            "elapsed_seconds": round(report.elapsed_seconds, 2),
        },
        "issues": [
            {
                "file": i.file,
                "line": i.line,
                "severity": i.severity,
                "category": i.category,
                "message": i.message,
                "suggestion": i.suggestion,
                "auto_fixable": i.auto_fixable,
                "fix_applied": i.fix_applied,
                "status": i.status,
                "evidence": i.evidence,
                "rejection_reason": i.rejection_reason,
            }
            for i in report.issues
        ]
    }
    output_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(f"  JSON report saved → {output_path}")


# ─────────────────────────────────────────────


def save_combined_json_report(reports: list, output_path: Path):
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
                        "severity": i.severity,
                        "category": i.category,
                        "message": i.message,
                        "suggestion": i.suggestion,
                        "auto_fixable": i.auto_fixable,
                        "fix_applied":  i.fix_applied,
                    }
                    for i in r.issues
                ],
            }
            for r in reports
        ],
    }
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Combined JSON report saved → {output_path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

_FAIL_ON_SEVERITY = {"critical": SEVERITY_CRITICAL, "warning": SEVERITY_WARNING,
                    "info": SEVERITY_INFO}


