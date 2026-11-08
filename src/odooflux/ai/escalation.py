"""Escalation: eligibility (T012), request lifecycle and response -> Edit (later tasks).

``escalation`` is the single integration point between the engine and AI. It reaches providers only through the
gateway (``odooflux.ai.gateway``); it never imports a provider adapter.
"""

from dataclasses import dataclass, field

from odooflux.ai.prompts.builder import DEFAULT_TEMPLATE, build_request, select_region
from odooflux.ai.caching.cache import cache_key
from odooflux.ai.protected import protected_changes, shape_ok, syntax_ok
from odooflux.ai.providers.types import AIResponse, Usage, UsageRecord, heuristic_tokens
from odooflux.ai.usage.usage import compute_cost
from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import Edit, apply_edits


@dataclass(frozen=True)
class FindingRef:
    """What escalation needs of a finding. ``status`` is OPEN until a re-scan says otherwise."""

    id: str
    rule_id: str
    path: str
    line: int
    message: str = ""
    suggestion: str = ""
    status: str = "OPEN"
    severity: str = "WARNING"


@dataclass(frozen=True)
class RuleMeta:
    """The slice of rule metadata escalation reads (REQ-AI-002). ``evidence`` entries: {"id", "excerpt"}."""

    rule_id: str
    ai_eligible: bool = False
    has_fix: bool = False
    evidence: tuple = ()
    review_required: bool = False
    docs: str = ""


@dataclass(frozen=True)
class Skipped:
    finding: FindingRef
    reason: str


def select_eligible(findings, metas: dict) -> tuple:
    """Split findings into (eligible, skipped). Never eligible: already fixed, unknown rule, ``ai_eligible`` false,
    a deterministic fix exists, or no evidence-backed rule metadata (FR-003, FR-013)."""
    eligible, skipped = [], []
    for finding in findings:
        meta = metas.get(finding.rule_id)
        if finding.status != "OPEN":
            reason = "already_fixed" if finding.status == "FIXED" else "not_open"
        elif meta is None:
            reason = "no_rule_metadata"
        elif not meta.ai_eligible:
            reason = "not_ai_eligible"
        elif meta.has_fix:
            reason = "deterministic_fix_available"
        elif not meta.evidence:
            reason = "no_evidence"
        else:
            eligible.append(finding)
            continue
        skipped.append(Skipped(finding, reason))
    return eligible, skipped


@dataclass(frozen=True)
class Verdict:
    """Result of reviewing one provider response. ``outcome`` is accepted, rejected:<reason>, skipped:<reason> or
    error:<kind>; only ``accepted`` carries an edit and the full candidate text."""

    outcome: str
    reason: str = ""
    edit: object = None
    new_text: str = ""
    replacement: str = ""

    @property
    def accepted(self) -> bool:
        return self.outcome == "accepted"


def _reject(reason: str) -> Verdict:
    return Verdict(outcome=f"rejected:{reason}", reason=reason)


def review_response(response, region, document, *, provider: str, model: str, step: str, finding_ids=(),
                    validate=None, severity: str = "WARNING") -> Verdict:
    """Contract obligations 1-5 (contracts/ai-provider.md): truncation, schema, decline, then the replacement is
    checked for syntax, region shape, protected identifiers, applied through the edit engine and validated."""
    if response.stop_reason == "error":
        return Verdict(outcome=f"error:{response.error_kind or 'unknown'}", reason=response.error_kind or "unknown")
    if response.stop_reason != "complete":
        return _reject("truncated")
    parsed = response.parsed
    if not isinstance(parsed, dict) or not isinstance(parsed.get("replacement"), str):
        return _reject("schema_mismatch")
    if parsed.get("cannot_fix"):
        return Verdict(outcome="skipped:model_declined", reason="model_declined")
    replacement = parsed["replacement"]
    before = region.text
    if replacement == before:
        return _reject("no_change")
    if not syntax_ok(region.path, replacement):
        return _reject("syntax_invalid")
    if not shape_ok(region.kind, region.path, before, replacement):
        return _reject("out_of_region")
    if protected_changes(region.path, before, replacement):
        return _reject("protected_identifier_changed")
    if document.text[region.start:region.end] != before:
        return _reject("before_text_mismatch")
    edit = Edit(id=f"ai:{region.start}-{region.end}:{provider}/{model}", rule_id=f"ai:{provider}/{model}",
                path=document.path, start=region.start, end=region.end, before=before, after=replacement,
                severity=severity, step=step, validation=("python-syntax", "xml-syntax", "static.rescan"),
                finding_ids=tuple(finding_ids))
    applied = apply_edits(document, [edit], precedence=[])
    if not applied.applied or not applied.preserved_ok:
        reason = applied.rejected[0].rejection_reason if applied.rejected else "internal"
        return _reject("before_text_mismatch" if reason == "stale-span" else f"edit_engine:{reason}")
    if validate is not None:
        failure = validate(document.path, applied.text)
        if failure:
            return _reject(f"validation_failed:{failure[0]}")
    return Verdict(outcome="accepted", edit=applied.applied[0], new_text=applied.text, replacement=replacement)


@dataclass
class FindingOutcome:
    finding_id: str
    rule_id: str
    path: str
    line: int
    status: str  # OPEN | FIXED (FIXED only from a re-scan)
    outcome: str  # accepted | resolved_by_rescan | rejected:* | skipped:* | error:* | cache_hit
    request_id: str = ""
    edit_id: str = ""


@dataclass
class FileResult:
    text: str
    outcomes: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    edits: list = field(default_factory=list)
    status_cap: object = None  # "NEEDS_REVIEW" when a review_required rule's finding was fixed by AI


def _pair_map(before: list, after: list) -> dict:
    """Index map before->after: same rule, closest lines first (same pairing as the engine's re-scan attribution)."""
    pairs = sorted(((abs(a.line - b.line), i, j) for i, b in enumerate(before) for j, a in enumerate(after)
                    if a.rule_id == b.rule_id), key=lambda t: t)
    used_b, used_a, mapping = set(), set(), {}
    for _d, i, j in pairs:
        if i in used_b or j in used_a:
            continue
        used_b.add(i)
        used_a.add(j)
        mapping[i] = j
    return mapping


class Escalator:
    """Sends eligible findings, one region each, through ``sender`` (the gateway) and keeps only edits that pass the
    response checks, validation and a re-scan. Nothing here imports a provider adapter.

    Optional collaborators: ``budgets`` (BudgetTree, hard stops), ``ledger`` (UsageLedger), ``cache`` (ResultCache,
    cached edits are re-validated like fresh ones), ``pricing`` (catalog pricing of the selected model).
    ``sender_hooks`` is True when ``sender`` accepts ``on_attempt``/``before_retry`` (the gateway does)."""

    def __init__(self, sender, *, provider: str, model: str, step: str, validate, rescan,
                 template_version: str = DEFAULT_TEMPLATE, max_output_cap: int = 4096, count_tokens=None,
                 budgets=None, ledger=None, cache=None, pricing=None, sender_hooks: bool = False):
        self.sender = sender
        self.provider, self.model, self.step = provider, model, step
        self.validate, self.rescan = validate, rescan
        self.template_version = template_version
        self.max_output_cap = max_output_cap
        self.count_tokens = count_tokens or heuristic_tokens
        self.budgets, self.ledger, self.cache = budgets, ledger, cache
        self.pricing, self.sender_hooks = pricing, sender_hooks
        self._seq = 0

    def _request_id(self, module: str, relpath: str) -> str:
        self._seq += 1
        return f"{module}/{relpath}#{self._seq}"

    def _record(self, module, request_id, outcome, finding, usage=None, attempts=1, cost=None):
        if self.ledger is None:
            return
        usage = usage or Usage()
        self.ledger.record(UsageRecord(
            request_id=request_id, provider=self.provider, model=self.model, input_tokens=usage.input,
            output_tokens=usage.output, cached_tokens=usage.cached, estimated=usage.estimated, cost=cost,
            outcome=outcome, finding_ids=(finding.id,), module=module, attempts=attempts))

    def _judge(self, response, region, relpath, current, finding, seen, keys):
        """Response checks, validation and the re-scan. Returns (outcome, verdict, scan_data)."""
        document = Document.from_text(relpath, current)
        verdict = review_response(response, region, document, provider=self.provider, model=self.model,
                                  step=self.step, finding_ids=(finding.id,), validate=self.validate,
                                  severity=finding.severity)
        if not verdict.accepted:
            return verdict.outcome, verdict, None
        before_scan, after_scan = self.rescan(relpath, current), self.rescan(relpath, verdict.new_text)
        mapping = _pair_map(before_scan, after_scan)
        tracked_to_before = _pair_map(list(seen.values()), before_scan)
        target_idx = tracked_to_before.get(keys.index(finding.id))
        if target_idx is None:  # the re-scan cannot see the finding: nothing can be attributed to this edit
            return "rejected:finding_not_in_rescan", verdict, None
        if target_idx in mapping:
            return "rejected:finding_unresolved", verdict, None
        if set(range(len(after_scan))) - set(mapping.values()):
            return "rejected:introduced_findings", verdict, None
        return "accepted", verdict, (mapping, tracked_to_before, after_scan)

    def _send(self, request, module, relpath, finding, est_in, est_cost):
        """Budget check, send, accounting. Returns (response, outcome-or-None-when-sent)."""
        blocked = None
        if self.budgets is not None:
            blocked = self.budgets.check(module, relpath, est_in, request.max_output_tokens, est_cost)
        if blocked:
            self._record(module, request.request_id, f"skipped:{blocked}", finding, attempts=0)
            return None, f"skipped:{blocked}"
        charged = []

        def charge(resp):
            usage = resp.usage
            if self.budgets is not None:
                self.budgets.charge(module, relpath, usage.input + usage.output + usage.cached,
                                    compute_cost(usage, self.pricing))
                charged.append(True)

        if self.sender_hooks:
            guard = None
            if self.budgets is not None:
                guard = lambda: self.budgets.check(module, relpath, est_in, request.max_output_tokens,  # noqa: E731
                                                   est_cost) is None
            response = self.sender(request, on_attempt=charge, before_retry=guard)
        else:
            response = self.sender(request)
        if response.stop_reason != "error" and response.usage.input == 0 and response.usage.output == 0 \
                and response.usage.cached == 0:
            response.usage = Usage(input=est_in, output=self.count_tokens(response.text), estimated=True)
        if not charged:
            charge(response)
        return response, None

    def escalate_file(self, module: str, relpath: str, text: str, findings, metas: dict) -> FileResult:
        eligible, skipped = select_eligible(findings, metas)
        result = FileResult(text=text, skipped=skipped)
        tracked = {f.id: f for f in eligible}
        seen = {f.id: _Seen(f.rule_id, f.line) for f in eligible}  # current location of each unresolved finding
        outcomes = {}
        fixed_rules = set()
        while True:
            pending = [f for f in eligible if f.id in seen and f.id not in outcomes]
            if not pending:
                break
            finding = max(pending, key=lambda f: (seen[f.id].line, f.id))
            current = result.text
            region = select_region(relpath, current, seen[finding.id].line)
            request_id = self._request_id(module, relpath)
            if region is None:
                outcomes[finding.id] = self._outcome(finding, "OPEN", "skipped:no_region")
                self._record(module, request_id, "skipped:no_region", finding, attempts=0)
                continue
            meta = metas[finding.rule_id]
            keys = list(seen.keys())
            evidence_ids = [e["id"] for e in meta.evidence]
            key = cache_key(region.text, finding.rule_id, self.provider, self.model, self.template_version,
                            evidence_ids, self.step)
            outcome = verdict = scan = None
            cached = self.cache.get(key) if self.cache is not None else None
            if cached is not None:
                synthetic = AIResponse(text="", parsed={"replacement": cached, "notes": "", "cannot_fix": False})
                outcome, verdict, scan = self._judge(synthetic, region, relpath, current, finding, seen, keys)
                if outcome == "accepted":
                    outcome = "cache_hit"
                    self._record(module, request_id, "cache_hit", finding, attempts=0)
                else:
                    self.cache.revalidation_failed(key)  # a stale or tampered cached edit is dropped
                    outcome = verdict = scan = None
            if outcome is None:
                try:
                    request, _info = build_request(
                        finding_line=seen[finding.id].line, rule_id=finding.rule_id,
                        rule_message=finding.message, meta=meta, region=region, relpath=relpath,
                        provider=self.provider, model=self.model, target_step=self.step, request_id=request_id,
                        budget_ref=f"job/{module}/{relpath}/{request_id}", cache_key=key,
                        max_output_tokens=min(self.max_output_cap, 2 * self.count_tokens(region.text) + 256),
                        template_version=self.template_version)
                except ValueError as exc:
                    outcomes[finding.id] = self._outcome(finding, "OPEN", f"skipped:{exc}")
                    self._record(module, request_id, f"skipped:{exc}", finding, attempts=0)
                    continue
                est_in = self.count_tokens(request.system) + sum(self.count_tokens(m["content"])
                                                                 for m in request.messages)
                est_cost = compute_cost(Usage(input=est_in, output=request.max_output_tokens), self.pricing)
                response, blocked = self._send(request, module, relpath, finding, est_in, est_cost)
                if blocked:
                    outcomes[finding.id] = self._outcome(finding, "OPEN", blocked, request_id)
                    continue
                outcome, verdict, scan = self._judge(response, region, relpath, current, finding, seen, keys)
                self._record(module, request_id, outcome, finding, response.usage, response.attempts,
                             compute_cost(response.usage, self.pricing))
                if outcome == "accepted" and self.cache is not None:
                    self.cache.put(key, verdict.replacement, self.template_version)
            if outcome not in ("accepted", "cache_hit"):
                outcomes[finding.id] = self._outcome(finding, "OPEN", outcome, request_id)
                continue
            # accepted: the re-scan decides every finding's fate
            mapping, tracked_to_before, after_scan = scan
            result.text = verdict.new_text
            result.edits.append(verdict.edit)
            for i, k in enumerate(keys):
                b = tracked_to_before.get(i)
                if b is None:
                    continue
                a = mapping.get(b)
                if a is None:
                    fixed_rules.add(tracked[k].rule_id)
                    outcomes[k] = self._outcome(
                        tracked[k], "FIXED", outcome if k == finding.id else "resolved_by_rescan",
                        request_id if k == finding.id else "", verdict.edit.id)
                    seen.pop(k)
                else:
                    seen[k] = _Seen(seen[k].rule_id, after_scan[a].line)
        result.outcomes = [outcomes[f.id] for f in eligible if f.id in outcomes]
        if any(metas[r].review_required for r in fixed_rules):
            result.status_cap = "NEEDS_REVIEW"
        return result

    @staticmethod
    def _outcome(finding, status, outcome, request_id="", edit_id="") -> FindingOutcome:
        return FindingOutcome(finding_id=finding.id, rule_id=finding.rule_id, path=finding.path, line=finding.line,
                              status=status, outcome=outcome, request_id=request_id, edit_id=edit_id)


@dataclass
class _Seen:
    rule_id: str
    line: int
