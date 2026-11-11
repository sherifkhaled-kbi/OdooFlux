"""Per-module analysis and edit planning (P0 behaviour, now expressed through the engine)."""

import difflib
import re
from pathlib import Path

from odooflux.core.contracts.records import Finding
from odooflux.core.engine.apply import FileEdit, diff_to_edits
from odooflux.core.engine.rescan import resolved_by_rescan
from odooflux.core.engine.step_runner import Step, detect, run_step, run_steps
from odooflux.core.orchestrator import knowledge_rules
from odooflux.discovery.manifest import MANIFEST_NAMES
from odooflux.discovery.modules import iter_module_files
from odooflux.rules.shared.legacy_adapter import step_for
from odooflux.rules.shared.legacy_overlap import LEGACY_CATEGORIES
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


def _finding_family(item) -> str:
    """The legacy category a finding belongs to. An experimental rule row and the legacy row it replaces (after a
    fix, the same construct is often reported by the legacy row) are one finding for the re-scan."""
    legacy = LEGACY_CATEGORIES.get(item.category)
    return legacy[0] if legacy else item.category


def _touched_by(old: str, new: str):
    """Predicate: the original line (1-based) of an issue was replaced or removed by the fix."""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    changed = set()
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag != "equal":
            changed.update(range(i1 + 1, max(i2, i1 + 1) + 1))
    return lambda item: item.line in changed


def _file_step(path: str, from_version: int, to_version: int, registries, run_rules, knowledge, knowledge_steps,
               *, transform: bool, file_log=None):
    """Legacy step for the file plus the knowledge rules of its kind. The fixing transform runs the legacy
    fixer first, then the FIX_ENABLED knowledge fixers on its output (a construct the legacy fixer already
    changed is not found again, so nothing is edited twice). ``file_log`` collects experimental records."""
    mine = knowledge_rules.rules_for_file(knowledge, path)
    step = step_for(path, from_version, to_version, transform=transform,
                    extra_rules=_extra_rules(registries) + list(run_rules))
    if not mine:
        return step
    step.rules = step.rules + mine
    if transform:
        extra = knowledge_rules.fixing_transform(mine, knowledge_steps, file_log)
        if extra is not None:
            legacy = step.transform
            step.transform = (lambda p, t: extra(p, legacy(p, t) if legacy else t))
    return step


def _stages(path: str, from_version: int, to_version: int, registries, run_rules, knowledge, knowledge_steps):
    """The file's fixing transform split into ordered stages: the legacy fixer, then each FIX_ENABLED knowledge step
    in plan order. Returns (steps, logs); ``logs[i]`` collects the experimental records of stage i."""
    mine = knowledge_rules.rules_for_file(knowledge, path)
    legacy = step_for(path, from_version, to_version, transform=True,
                      extra_rules=_extra_rules(registries) + list(run_rules))
    steps, logs = [Step(step_id=legacy.step_id, rules=[], transform=legacy.transform)], [[]]
    order = {key: i for i, key in enumerate(knowledge_steps)}
    for step_key in sorted({r.step for r in mine if r.fixes}, key=lambda s: order.get(s, -1)):
        log: list = []
        steps.append(Step(step_id=step_key, rules=[], transform=knowledge_rules.fixing_transform(
            [r for r in mine if r.step == step_key], [step_key], log)))
        logs.append(log)
    return steps, logs


def _salvage(path: str, from_version: int, to_version: int, registries, run_rules, knowledge, knowledge_steps,
             validators, text: str, file_log: list):
    """The file after its refused whole-file transform, rebuilt stage by stage: each stage is validated on its own,
    and the output of the last VALID stage is kept (run_steps stops at the first refusal, so the refused stage's
    output is its input). Returns (kept_text, verdict); verdict is None when no stage changed the text. ``file_log``
    receives the experimental records of the kept stages only."""
    steps, logs = _stages(path, from_version, to_version, registries, run_rules, knowledge, knowledge_steps)
    del file_log[:]
    outcomes = run_steps(steps, path, text, validators)
    kept = outcomes[-1].output
    if kept == text:
        return text, None
    for index, outcome in enumerate(outcomes):
        if not outcome.rejected:
            file_log.extend(logs[index])
    verdict = next((o.verdict for o in reversed(outcomes) if not o.rejected and o.verdict is not None), None)
    return kept, verdict


def plan_module(module_path, from_version: int, to_version: int, registries, *,
                compute_edits: bool, run_rules=(), knowledge=(), knowledge_steps=(), experimental_log=None):
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

    def issues_of(findings, path, handled=frozenset()):
        return knowledge_rules.deduplicate([to_issue(f, path, known) for f in findings], set(known), handled)

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
        file_log: list = []
        step = _file_step(path, from_version, to_version, registries, run_rules, knowledge, knowledge_steps,
                          transform=True, file_log=file_log)
        outcome = run_step(step, path, text, validators)
        rejection, fixed, verdict = "", outcome.output, outcome.verdict
        if outcome.rejected:  # the whole-file transform was refused: keep the valid stages of it (AD-05, policy)
            rejection = outcome.rejection
            if renamed:  # the manifest rename cannot be split from its content: the file keeps its bytes and name
                del file_log[:]
                fixed = text
            else:
                fixed, kept_verdict = _salvage(path, from_version, to_version, registries, run_rules, knowledge,
                                               knowledge_steps, validators, text, file_log)
                verdict = kept_verdict or outcome.verdict
        handled = knowledge_rules.handled_lines(file_log, path)  # known only after the transform ran
        before = issues_of(outcome.findings, path, handled)
        refused_at = {(rec["rule_id"], refusal["line"]) for rec in file_log for refusal in rec["refused"]}
        for issue in before:  # an element its experimental fixer refused is for the developer, not auto-fixable
            if (issue.category, issue.line) in refused_at:
                issue.auto_fixable = False
        report.issues.extend(before)
        if experimental_log is not None:  # conversions and refusals of experimental rules, for the report
            experimental_log.extend(file_log)
        if rejection and fixed == text:  # nothing kept: the file keeps its bytes and its name, its findings stay open
            edits.append(FileEdit(path=fp, dest=fp, original=text, fixed=text, issues=before,
                                  rejection=rejection, validation=verdict))
            continue
        if fixed == text and not renamed:
            continue
        dest = new_manifest if renamed else fp
        after_errors: list = []
        after = issues_of(detect(step.rules, path, fixed, after_errors), path, handled)
        # SC-005: only a FIX_ENABLED knowledge rule (or a legacy row) can be marked fixed; a DETECT_ONLY finding
        # whose construct vanished stays open for the reviewer. The one exception is an experimental rule that
        # converted something in this file (its finding is the one its fixer acted on).
        converted_by = {r["rule_id"] for r in file_log if r["converted"]}
        resolved = [i for i in resolved_by_rescan(before, after, key=_finding_family, touched=_touched_by(
                        text, fixed))
                    if i.maturity in ("", "FIX_ENABLED") or i.category in converted_by]
        edits.append(FileEdit(path=fp, dest=dest, original=text, fixed=fixed, issues=before,
                              resolved=resolved, rejection=rejection,
                              edits=diff_to_edits(path, text, fixed), validation=verdict))
    for edit in edits:
        if edit.rejection:
            kept = edit.fixed != edit.original
            report.issues.append(Issue(
                file=str(edit.path), line=0, severity=SEVERITY_WARNING, category="Fix Rejected",
                message=(f"{edit.path.name}: {edit.rejection}. "
                         + ("The refused change is not applied; the valid changes to this file are kept."
                            if kept else "The file is left unchanged.")),
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
