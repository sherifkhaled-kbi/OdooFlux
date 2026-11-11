"""Legacy console output, reproduced from the report model (T056)."""

import os
from pathlib import Path
from typing import Optional

from odooflux.reporting.model.model import UNKNOWN, _line, known_column, legacy_unresolved
from odooflux.rules.shared.legacy_rules import (
    MigrationReport, SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO)

# REPORT RENDERING
# ─────────────────────────────────────────────

SEVERITY_COLOR = {
    SEVERITY_CRITICAL: '\033[91m',
    SEVERITY_WARNING:  '\033[93m',
    SEVERITY_INFO:     '\033[96m',
}
RESET = '\033[0m'
BOLD  = '\033[1m'
GREEN = '\033[92m'
YELLOW = '\033[93m'


def print_report(report: MigrationReport, no_color: bool = False, show_fixed: bool = False,
                 filter_severity: Optional[str] = None, *, entry: Optional[dict] = None, mode: str = "fix"):
    def c(color, text):
        return text if no_color else f"{color}{text}{RESET}"

    width = 80
    open_issues  = [i for i in report.issues if not i.fix_applied]
    fixed_issues = [i for i in report.issues if i.fix_applied]

    print()
    print(c(BOLD, "=" * width))
    print(c(BOLD, f"  Odoo Migration Report  v{report.from_version} → v{report.to_version}"))
    print(c(BOLD, f"  Module : {report.module_path}"))
    print(c(BOLD, f"  Time   : {report.timestamp}"))
    print(c(BOLD, "=" * width))

    display_issues = report.issues if show_fixed else open_issues

    _SEV_ORDER = {SEVERITY_CRITICAL: 3, SEVERITY_WARNING: 2, SEVERITY_INFO: 1}
    if filter_severity:
        _min_level = _SEV_ORDER.get(filter_severity, 1)
        display_issues = [i for i in display_issues
                          if _SEV_ORDER.get(i.severity, 0) >= _min_level]

    if not display_issues:
        if fixed_issues:
            print(c(GREEN, f"\n  ✓ All {len(fixed_issues)} issue(s) fixed! Module is clean.\n"))
        else:
            from pathlib import Path
            if not (Path(report.module_path) / "__manifest__.py").is_file():
                print(c(YELLOW, "\n  ! No issues found by the rules that ran, but this directory has no __manifest__.py:\n"
                                "    dependency integrity (L3) could not run and nothing was verified.\n"))
            else:
                print(c(GREEN, "\n  ✓ No issues found! Module looks clean.\n"))
        if fixed_issues and not show_fixed:
            print(f"  (Use --show-fixed to see {len(fixed_issues)} resolved issue(s))\n")
        return

    by_file: dict = {}
    for issue in display_issues:
        by_file.setdefault(issue.file, []).append(issue)
    unresolved = {id(i): f for i, f in zip(report.issues, legacy_unresolved(report, entry, mode))}

    for filepath, issues in sorted(by_file.items()):
        rel = os.path.relpath(filepath, report.module_path)
        print(f"\n{c(BOLD, '  FILE: ' + rel)}")
        print("  " + "-" * (width - 2))
        for issue in sorted(issues, key=lambda i: i.line):
            sev_color = SEVERITY_COLOR.get(issue.severity, '')
            tag = (c(GREEN, ' ✓ FIXED') if issue.fix_applied
                   else c(GREEN, ' [AUTO-FIX]') if issue.auto_fixable
                   else '')
            line = _line(issue.line)  # AD-06: a line below 1 is shown as UNKNOWN, never as a number
            loc = f"L{line}:{known_column(issue) or UNKNOWN}" if line != UNKNOWN else UNKNOWN  # PA-5: same rule
            print(
                f"  {c(sev_color, f'[{issue.severity:<8}]')} "
                f"{loc:<6} "
                f"{c(BOLD, issue.category)}{tag}"
            )
            print(f"           {issue.message}")
            if not issue.fix_applied:
                fields = unresolved[id(issue)]
                print(f"           → {fields['developer_action']}")
                print(f"           Not fixed: {fields['reason_not_fixed']}")

    remaining_crit = sum(1 for i in open_issues if i.severity == SEVERITY_CRITICAL)
    remaining_warn = sum(1 for i in open_issues if i.severity == SEVERITY_WARNING)
    remaining_info = sum(1 for i in open_issues if i.severity == SEVERITY_INFO)
    total_crit = sum(1 for i in report.issues if i.severity == SEVERITY_CRITICAL)
    total_warn = sum(1 for i in report.issues if i.severity == SEVERITY_WARNING)
    total_info = sum(1 for i in report.issues if i.severity == SEVERITY_INFO)

    print()
    print(c(BOLD, "=" * width))
    print(c(BOLD, "  SUMMARY"))
    print(c(BOLD, "=" * width))
    print(f"  {c(SEVERITY_COLOR[SEVERITY_CRITICAL], f'Critical : {remaining_crit}')}"
          + (f"  (total: {total_crit})" if total_crit != remaining_crit else ""))
    print(f"  {c(SEVERITY_COLOR[SEVERITY_WARNING],  f'Warnings : {remaining_warn}')}"
          + (f"  (total: {total_warn})" if total_warn != remaining_warn else ""))
    print(f"  {c(SEVERITY_COLOR[SEVERITY_INFO],     f'Info     : {remaining_info}')}"
          + (f"  (total: {total_info})" if total_info != remaining_info else ""))
    if fixed_issues:
        print(f"  {c(GREEN, f'Fixed    : {len(fixed_issues)}')}")
    if report.fixes_applied:
        print(f"  {c(GREEN, f'Files modified: {report.fixes_applied}')}")
    print(c(BOLD, "=" * width))
    print()




def print_combined_summary(reports: list, no_color: bool = False):
    def c(color, text):
        return text if no_color else f"{color}{text}{RESET}"
    width = 80
    print()
    print(c(BOLD, "=" * width))
    to_v = reports[0].to_version if reports else 19
    print(c(BOLD, f"  COMBINED SUMMARY  ({len(reports)} module(s) → Odoo {to_v})"))
    print(c(BOLD, "=" * width))
    print(f"  {'Module':<40} {'Crit':>6} {'Warn':>6} {'Info':>6} {'Fixed':>6} {'Time':>7}")
    print("  " + "-" * (width - 2))
    for r in reports:
        name = Path(r.module_path).name
        crit_s = c(SEVERITY_COLOR[SEVERITY_CRITICAL], str(r.critical_count)) if r.critical_count else "0"
        warn_s = c(SEVERITY_COLOR[SEVERITY_WARNING],  str(r.warning_count))  if r.warning_count  else "0"
        info_s = c(SEVERITY_COLOR[SEVERITY_INFO],     str(r.info_count))     if r.info_count     else "0"
        fix_s  = c(GREEN, str(r.fixes_applied)) if r.fixes_applied else "0"
        time_s = f"{r.elapsed_seconds:.1f}s"
        print(f"  {name:<40} {crit_s:>6} {warn_s:>6} {info_s:>6} {fix_s:>6} {time_s:>7}")
    print("  " + "-" * (width - 2))
    total_c = sum(r.critical_count  for r in reports)
    total_w = sum(r.warning_count   for r in reports)
    total_i = sum(r.info_count      for r in reports)
    total_f = sum(r.fixes_applied   for r in reports)
    total_t = sum(r.elapsed_seconds for r in reports)
    print(
        f"  {'TOTAL':<40} "
        f"{c(SEVERITY_COLOR[SEVERITY_CRITICAL], str(total_c)):>6} "
        f"{c(SEVERITY_COLOR[SEVERITY_WARNING],  str(total_w)):>6} "
        f"{c(SEVERITY_COLOR[SEVERITY_INFO],     str(total_i)):>6} "
        f"{c(GREEN, str(total_f)):>6} "
        f"{total_t:.1f}s"
    )
    print(c(BOLD, "=" * width))
    print()


