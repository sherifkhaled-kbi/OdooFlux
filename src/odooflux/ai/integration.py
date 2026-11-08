"""The registered escalation pass: wires catalog, gateway, budgets, cache and usage to the orchestrator's AI pass.

The orchestrator (core) never imports this package. ``builtins`` registers ``EscalationPass`` as the ``ai-escalation``
entry; ``core/orchestrator/ai_pass.py`` calls ``check_config`` before discovery and ``run`` after the deterministic pass.
Accepted AI edits go through the same workspace, validation (L1, L2 re-scan, L3), backup and promotion as any edit.
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.ai.authorization import AuthorizationError, parse_grants
from odooflux.ai.caching.cache import ResultCache
from odooflux.ai.escalation import Escalator, FindingRef, RuleMeta
from odooflux.ai.gateway import GatewayConfig, build_gateway
from odooflux.ai.providers.catalog import CatalogError, load_catalog
from odooflux.ai.providers.credentials import CredentialError
from odooflux.ai.usage.budgets import BudgetTree
from odooflux.ai.usage.usage import UsageLedger
from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.engine.apply import FileEdit, diff_to_edits
from odooflux.core.engine.rescan import resolved_by_rescan
from odooflux.core.engine.step_runner import detect
from odooflux.core.jobs.promote import stage_edits
from odooflux.core.jobs.workspace import make_workspace
from odooflux.rules.shared.legacy_adapter import step_for
from odooflux.rules.shared.legacy_rules import Issue, SEVERITY_INFO, SEVERITY_WARNING
from odooflux.utils.hashing import finding_id

SUPPORTED_SUFFIXES = (".py", ".xml")


@dataclass
class PassResult:
    count: int = 0
    usage: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _Seen:
    rule_id: str
    line: int


def _rule_id(item) -> str:
    return getattr(item, "rule_id", None) or getattr(item, "category", "")


def rule_metadata_from_knowledge(kb) -> dict:
    """RuleMeta per rule id from the loaded knowledge base. ``has_fix`` is true when the rule binds a fixer."""
    out = {}
    for rule in kb.rules:
        evidence = []
        for ev_id in rule.get("evidence") or []:
            record = kb.evidence.get(ev_id)
            if not record:
                continue
            loc = (record.get("locations") or [{}])[0]
            where = f" [{loc.get('branch', '')}@{str(loc.get('revision', ''))[:12]} {loc.get('path', '')}:{loc.get('line', '')}]"
            evidence.append({"id": ev_id, "excerpt": (record.get("description") or "")[:600] + where})
        out[rule["id"]] = RuleMeta(
            rule_id=rule["id"], ai_eligible=bool(rule.get("ai_eligible")), has_fix=bool(rule.get("fixer_ref")),
            evidence=tuple(evidence), review_required=bool(rule.get("review_required")),
            docs=" ".join(x for x in (rule.get("message", ""), rule.get("suggestion", "")) if x))
    return out


def _event_text(event: dict) -> str:
    where = "".join(f" {k}={event[k]}" for k in ("module", "file") if event.get(k))
    reason = f" ({event['reason']})" if event.get("reason") else ""
    return f"budget_{event['scope']}:{where} limit {event['limit']}, used {event['used']}{reason}".replace(":  ", ": ")


def report_usage(summary: dict, gateway, config: dict, cache, layer3_log: list) -> dict:
    """The ``ai_usage`` record: the report model's required shape (``enabled``, ``consent``, ``providers``,
    ``budget_events`` as text, ``totals``) plus the detailed ledger fields."""
    providers = []
    for key, row in summary["by_model"].items():
        name, _, model = key.partition("/")
        entry = {"name": name, "model": model, "requests": row["requests"], "input_tokens": row["input_tokens"],
                 "output_tokens": row["output_tokens"], "cached_tokens": row["cached_tokens"], "cost": row["cost"]}
        providers.append(entry)
    details = summary["budget_events"]
    summary.update({
        "enabled": True, "consent": True, "providers": providers,
        "budget_events": [_event_text(e) for e in details], "budget_event_details": details,
        "provider": gateway.provider_name, "model": config["model"], "external": gateway.entry.type == "external",
        "kill_switch": bool(config.get("kill_switch")), "authorizations": dict(config.get("authorizations") or {}),
        "cache": dict(cache.stats), "layer3": layer3_log})
    return summary


def _ai_outcome(rec) -> str:
    """Audit outcome of a usage record: refused when nothing reached the provider, failed on an error."""
    if rec.outcome in ("accepted", "cache_hit"):
        return "ok"
    if rec.attempts == 0 or rec.outcome.startswith(("skipped:", "rejected:")):
        return "refused"
    return "failed"


class EscalationPass:
    key = "ai-escalation"
    contract_version = CONTRACT_VERSION

    def __init__(self, layer3=None, metadata_source=None, transport_for=None, environ=None, sleep=time.sleep, *,
                 knowledge_root=None):
        self.layer3 = layer3
        self.metadata_source = metadata_source
        self.transport_for = transport_for
        self.environ = environ
        self.sleep = sleep
        self.knowledge_root = knowledge_root  # None: the built-in knowledge tree (REQ-KAP-036)

    # -- configuration, checked before discovery ---------------------------------------------------------------
    def check_config(self, config: dict):
        """An error message for an unusable configuration, else None."""
        try:
            catalog = load_catalog(config.get("catalog_paths") or [])
            parse_grants([f"{p}={','.join(c)}" for p, c in (config.get("authorizations") or {}).items()])
            entry, descriptor = catalog.resolve(config["provider"], config["model"], config.get("endpoint", ""))
        except (CatalogError, AuthorizationError) as exc:
            return str(exc)
        if config.get("budget_job_cost") is not None and not descriptor.pricing:
            return (f"--ai-budget-job-cost needs pricing for {config['provider']}/{config['model']} in the model "
                    "catalog (pricing not configured)")
        if entry.adapter == "fake" and not config.get("fake_script"):
            return "the fake provider needs a script (ODOOFLUX_AI_FAKE_SCRIPT)"
        return None

    def _metadata(self) -> dict:
        if self.metadata_source is not None:
            return self.metadata_source()
        from odooflux.knowledge.loader import load_knowledge
        kb = load_knowledge() if self.knowledge_root is None else load_knowledge(self.knowledge_root)
        return rule_metadata_from_knowledge(kb)

    # -- the pass ----------------------------------------------------------------------------------------------
    def run(self, *, config, reports, module_paths, run, registries, write_module, validate_text, from_version,
            to_version, environ=None, step_factory=None) -> PassResult:
        env = self.environ if self.environ is not None else (environ if environ is not None else os.environ)
        catalog = load_catalog(config.get("catalog_paths") or [])
        scanned = tuple(str(p) for p in module_paths)
        gateway = build_gateway(
            GatewayConfig(provider=config["provider"], model=config["model"], endpoint=config.get("endpoint", ""),
                          grants=config.get("authorizations") or {}, kill_switch=bool(config.get("kill_switch")),
                          max_retries=int(config.get("max_retries", 2)), timeout_s=float(config.get("timeout_s", 60.0)),
                          secrets_file=config.get("secrets_file", ""), scanned_paths=scanned,
                          fake_script=config.get("fake_script", "")),
            catalog, environ=env, transport_for=self.transport_for, sleep=self.sleep)
        state_dir = Path(run.root).parent.parent
        cache = ResultCache(state_dir / "ai-cache", enabled=bool(config.get("use_cache", True)))
        if config.get("clear_cache"):
            cache.clear()
        ledger = UsageLedger()
        budgets = BudgetTree(job_tokens=config["budget_job_tokens"], module_tokens=config.get("budget_module_tokens"),
                             file_tokens=config.get("budget_file_tokens"),
                             request_tokens=config.get("budget_request_tokens"), job_cost=config.get("budget_job_cost"))
        metas = self._metadata()
        escalator = Escalator(
            gateway.complete, provider=gateway.provider_name, model=config["model"],
            step=f"{from_version}-{to_version}",
            validate=lambda path, text: ("L1", validate_text(path, text)) if validate_text(path, text) else None,
            rescan=lambda path, text: [], budgets=budgets, ledger=ledger, cache=cache,
            pricing=gateway.descriptor.pricing, sender_hooks=True,
            max_output_cap=gateway.descriptor.max_output or 4096)
        layer3_log = []
        written = 0
        for report, module_path in zip(reports, module_paths):
            if report.blocked:
                continue
            written += self._module(escalator, metas, report, Path(module_path), registries, write_module,
                                    validate_text, from_version, to_version, run, layer3_log, ledger,
                                    step_factory)
        ledger.budget_events = list(budgets.events)
        audit = getattr(run, "audit", None)
        if audit is not None:  # metadata only: never a prompt, a response or a credential (REQ-SEC-005)
            for rec in ledger.records:
                audit.append("ai_request", rec.module, _ai_outcome(rec), {
                    "provider": rec.provider, "model": rec.model, "input_tokens": rec.input_tokens,
                    "output_tokens": rec.output_tokens, "cache_hit": rec.outcome == "cache_hit",
                    "outcome": rec.outcome.split(":", 1)[0]})
        usage = report_usage(ledger.summary(), gateway, config, cache, layer3_log)
        return PassResult(count=written, usage=usage)

    def _module(self, escalator, metas, report, module_path, registries, write_module, validate_text, from_version,
                to_version, run, layer3_log, ledger, step_factory=None) -> int:
        extra = registries.rules.all()
        files = sorted({i.file for i in report.issues if not i.fix_applied and not i.auto_fixable
                        and i.file.endswith(SUPPORTED_SUFFIXES)})
        file_edits, notices, fixed_pairs, cap_rules = [], [], [], []
        for file_name in files:
            fp = Path(file_name)
            try:
                text = fp.read_text(encoding="utf-8")
                relpath = fp.relative_to(module_path).as_posix()
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            step = (step_factory(str(fp)) if step_factory is not None else
                    step_for(str(fp), from_version, to_version, transform=False, extra_rules=extra))

            def scan(_path, body, _fp=fp, _step=step):
                return [_Seen(_rule_id(f), f.line) for f in detect(_step.rules, str(_fp), body, [])]

            fresh = detect(step.rules, str(fp), text, [])
            findings = [FindingRef(id=finding_id(relpath, _rule_id(f), f.line, f.message), rule_id=_rule_id(f),
                                   path=relpath, line=f.line, message=f.message, suggestion=f.suggestion,
                                   severity=f.severity) for f in fresh if _rule_id(f) in metas]
            if not findings:
                continue
            escalator.rescan = scan
            result = escalator.escalate_file(module_path.name, relpath, text, findings, metas)
            for o in result.outcomes:
                if o.status == "OPEN":
                    notices.append(self._notice(fp, o))
            if result.status_cap:
                notices.append(Issue(file=str(fp), line=0, severity=SEVERITY_INFO, category="AI Review Required",
                                     message="An AI edit fixed a finding of a review-required rule; the module stays "
                                             "NEEDS_REVIEW until a person reviews it.",
                                     suggestion="Review the AI edit in the backup diff", auto_fixable=False))
            if result.text == text:
                continue
            after = detect(step.rules, str(fp), result.text, [])
            before_issues = [self._issue(fp, f) for f in fresh]
            after_issues = [self._issue(fp, f) for f in after]
            resolved = resolved_by_rescan(before_issues, after_issues)
            file_edits.append(FileEdit(path=fp, dest=fp, original=text, fixed=result.text, issues=before_issues,
                                       resolved=resolved, edits=diff_to_edits(str(fp), text, result.text)))
            fixed_pairs.extend((fp, issue) for issue in resolved)
        report.issues.extend(notices)
        if not file_edits:
            return 0
        if self.layer3 is not None and self._layer3_regression(module_path, file_edits, run, to_version, layer3_log):
            for edit in file_edits:
                report.issues.append(Issue(
                    file=str(edit.path), line=0, severity=SEVERITY_WARNING, category="Fix Rejected",
                    message=f"AI edits for {module_path.name} rejected: validation_failed:layer3. None were written.",
                    suggestion="Fix by hand; the findings stay open", auto_fixable=False,
                    rejection_reason="validation_failed:layer3"))
            return 0
        count = write_module(module_path, file_edits, report)
        if report.blocked:
            return 0
        for fp, issue in fixed_pairs:  # mirror the re-scan result onto the report's findings
            candidates = [i for i in report.issues if i.file == str(fp) and i.category == issue.category
                          and not i.fix_applied]
            if candidates:
                min(candidates, key=lambda i: abs(i.line - issue.line)).fix_applied = True
        return count

    @staticmethod
    def _issue(fp, f) -> Issue:
        if isinstance(f, Issue):
            return f
        return Issue(file=str(fp), line=f.line, severity=f.severity, category=f.rule_id, message=f.message,
                     suggestion=f.suggestion, auto_fixable=False)

    @staticmethod
    def _notice(fp, outcome) -> Issue:
        kind = outcome.outcome
        if kind.startswith("error:"):
            category, severity = "AI Error", SEVERITY_WARNING
        elif kind.startswith("rejected:"):
            category, severity = "AI Rejected", SEVERITY_INFO
        else:
            category, severity = "AI Skip", SEVERITY_INFO
        return Issue(file=str(fp), line=outcome.line, severity=severity, category=category,
                     message=f"{outcome.rule_id}: {kind}; the finding stays open",
                     suggestion="Fix by hand, or adjust the AI configuration and re-run", auto_fixable=False)

    def _layer3_regression(self, module_path, file_edits, run, to_version, layer3_log) -> bool:
        """True when staging the AI edits introduces an L3 finding the module did not have."""
        base_findings, base = self.layer3(module_path, to_version)
        work = make_workspace(run, module_path.name, module_path)
        stage_edits(work, module_path, file_edits)
        findings, result = self.layer3(work, to_version)
        layer3_log.append({"module": module_path.name, "outcome": result.outcome, "baseline": base.outcome})
        key = lambda f: (f.rule_id, f.path, f.message)  # noqa: E731
        return bool({key(f) for f in findings} - {key(f) for f in base_findings})
