"""Per-module analysis and edit planning (P0 behaviour, now expressed through the engine)."""

import re
from pathlib import Path

from odooflux.core.contracts.records import Finding
from odooflux.core.engine.apply import FileEdit, diff_to_edits
from odooflux.core.engine.rescan import resolved_by_rescan
from odooflux.core.engine.step_runner import detect, run_step
from odooflux.core.orchestrator import knowledge_rules
from odooflux.discovery.manifest import MANIFEST_NAMES
from odooflux.discovery.modules import iter_module_files
from odooflux.rules.shared.legacy_adapter import step_for
from odooflux.rules.shared.legacy_rules import (
    Issue, MigrationReport, SEVERITY_CRITICAL, SEVERITY_WARNING, _read_file)

SCAN_EXTENSIONS = {'.py', '.xml', '.js', '.ts', '.css', '.scss', '.less'}


def to_issue(item, path: str, known=None) -> Issue:
    """``known`` maps a knowledge rule id to its ``KnowledgeRule`` (maturity, review flag, evidence)."""
    if isinstance(item, Issue):
        return item
    assert isinstance(item, Finding)
    rule = (known or {}).get(item.rule_id)
    if rule is None:
        return Issue(file=path, line=item.line, severity=item.severity, category=item.rule_id,
                     message=item.message, suggestion=item.suggestion, auto_fixable=False,
                     evidence=list(item.evidence))
    return Issue(file=path, line=item.line, severity=item.severity, category=item.rule_id,
                 message=item.message, suggestion=item.suggestion, auto_fixable=rule.fixes,
                 evidence=list(item.evidence), maturity=rule.maturity, review_required=rule.review_required)


def _extra_rules(registries) -> list:
    """Plugin rules (the registry holds plugins only; legacy rules come from the adapter)."""
    return registries.rules.all() if registries is not None else []


def _validators(registries) -> list:
    return registries.validators.all() if registries is not None else []


def _file_step(path: str, from_version: int, to_version: int, registries, run_rules, knowledge, knowledge_steps,
               *, transform: bool):
    """Legacy step for the file plus the knowledge rules of its kind. The fixing transform runs the legacy
    fixer first, then the FIX_ENABLED knowledge fixers on its output (a construct the legacy fixer already
    changed is not found again, so nothing is edited twice)."""
    mine = knowledge_rules.rules_for_file(knowledge, path)
    step = step_for(path, from_version, to_version, transform=transform,
                    extra_rules=_extra_rules(registries) + list(run_rules))
    if not mine:
        return step
    step.rules = step.rules + mine
    if transform:
        extra = knowledge_rules.fixing_transform(mine, knowledge_steps)
        if extra is not None:
            legacy = step.transform
            step.transform = (lambda p, t: extra(p, legacy(p, t) if legacy else t))
    return step


def plan_module(module_path, from_version: int, to_version: int, registries, *,
                compute_edits: bool, run_rules=(), knowledge=(), knowledge_steps=()):
    """
    Analyze every file of a module. Returns (report, edits). Nothing is written here: edits carry
    the validated fixed text, and rejected edits carry the parser error (FR-015).
    """
    module_path = Path(module_path)
    report = MigrationReport(module_path=str(module_path), from_version=from_version, to_version=to_version)
    _check_manifest_version(module_path, from_version, report)

    files = iter_module_files(module_path)
    manifests = [f for f in files if f.name.lower() in MANIFEST_NAMES]
    others = [f for f in files if f.suffix.lower() in SCAN_EXTENSIONS]
    new_manifest = module_path / "__manifest__.py"
    old_manifest = module_path / "__openerp__.py"
    duplicate = new_manifest.exists() and old_manifest.exists()
    if duplicate:
        report.issues.append(Issue(
            file=str(old_manifest), line=0, severity=SEVERITY_CRITICAL,
            category="Duplicate Manifest",
            message="Both __openerp__.py and __manifest__.py exist; __openerp__.py was neither "
                    "copied nor renamed (F-SAFE-5)",
            suggestion="Confirm which manifest is current, then delete the other one",
            auto_fixable=False))
    elif old_manifest.exists():
        report.actions.append([False, "rename __openerp__.py -> __manifest__.py"])

    validators = _validators(registries)
    known = {r.key: r for r in knowledge}
    scan_csv = bool(knowledge)  # csv has no legacy rows; only knowledge rules read it
    if scan_csv:
        others = others + [f for f in files if f.suffix.lower() == ".csv"]

    def issues_of(findings, path):
        return knowledge_rules.deduplicate([to_issue(f, path, known) for f in findings], set(known))

    edits = []
    for fp in dict.fromkeys(manifests + others):
        scratch = MigrationReport(module_path="", from_version=from_version, to_version=to_version)
        text = _read_file(fp, scratch)
        report.issues.extend(scratch.issues)
        if text is None:
            continue
        path = str(fp)
        renamed = fp == old_manifest and not duplicate
        if not compute_edits or (duplicate and fp == old_manifest):
            outcome = run_step(_file_step(path, from_version, to_version, registries, run_rules, knowledge,
                                          knowledge_steps, transform=False), path, text, validators)
            report.issues.extend(issues_of(outcome.findings, path))
            continue
        step = _file_step(path, from_version, to_version, registries, run_rules, knowledge, knowledge_steps,
                          transform=True)
        outcome = run_step(step, path, text, validators)
        before = issues_of(outcome.findings, path)
        report.issues.extend(before)
        if outcome.rejected:
            edits.append(FileEdit(path=fp, dest=fp, original=text, fixed=text, issues=before,
                                  rejection=outcome.rejection))
            continue
        if outcome.output == text and not renamed:
            continue
        dest = new_manifest if renamed else fp
        after_errors: list = []
        after = issues_of(detect(step.rules, path, outcome.output, after_errors), path)
        # SC-005: only a FIX_ENABLED knowledge rule (or a legacy row) can be marked fixed; a DETECT_ONLY finding
        # whose construct vanished stays open for the reviewer.
        resolved = [i for i in resolved_by_rescan(before, after) if i.maturity in ("", "FIX_ENABLED")]
        edits.append(FileEdit(path=fp, dest=dest, original=text, fixed=outcome.output, issues=before,
                              resolved=resolved,
                              edits=diff_to_edits(path, text, outcome.output)))
    for edit in edits:
        if edit.rejection:
            report.issues.append(Issue(
                file=str(edit.path), line=0, severity=SEVERITY_WARNING, category="Fix Rejected",
                message=f"{edit.path.name}: {edit.rejection}. No file in this module is written.",
                suggestion="Edit this file by hand; its findings stay open",
                auto_fixable=False, rejection_reason=edit.rejection))
    return report, edits


def _check_manifest_version(module_path: Path, from_version: int, report: MigrationReport):
    for name in ("__manifest__.py", "__openerp__.py"):
        mf = module_path / name
        if not mf.exists():
            continue
        try:
            text = mf.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"['\"]version['\"]\\s*:\\s*['\"](\d+)\.", text)
            if not m:
                # Try simpler pattern
                m = re.search(r"'version'\s*:\s*'(\d+)\.", text)
            if not m:
                m = re.search(r'"version"\s*:\s*"(\d+)\.', text)
            if m:
                declared = int(m.group(1))
                if declared != from_version:
                    report.issues.append(Issue(
                        file=str(mf), line=0, severity=SEVERITY_WARNING,
                        category="Version Mismatch",
                        message=(
                            f"Manifest declares version {declared}.x but "
                            f"--from-version={from_version} was passed"
                        ),
                        suggestion=(
                            f"Confirm the source version. If the module is v{declared}, "
                            f"re-run with --from-version {declared}"
                        ),
                        auto_fixable=False,
                    ))
        except Exception:
            pass
        break
