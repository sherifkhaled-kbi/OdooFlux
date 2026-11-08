"""AI proposer for candidate rules (feature 011, T060, REQ-KAP-017, REQ-KAP-002; contract candidate-rule-generation,
AI proposer section; D-08).

`propose` is optional and off by default. It runs only when the caller passes an enabled config, the kill switch is
off, and the `evidence_excerpt` category is granted to the configured provider. Otherwise it returns a status and
makes no gateway call.

The gateway and the authorizer are PARAMETERS (duck-typed): this module never imports `odooflux.ai`. The gateway needs
`complete(request)` returning an object with `error_kind`, `stop_reason`, `text` and `usage`. The authorizer needs
`missing(provider, categories)`. The CLI obtains both from the composition root, as `cli/ai_options.py` describes.

Data minimisation: the request carries one evidence excerpt (the evidence description and location labels, never
source files), the change fields the rationale needs, and the list of known template ids. The request is a relative
region only.

Reply: a closed object `{"rationale": str, "template_hint": str}` (no other keys). A reply that fails the schema, is
truncated, or is not JSON is discarded whole with a content-free reason. Accepted output is a proposal with origin
AI_PROPOSED. It never sets evidence, status, maturity, `confirmed`, `detectors_verified`, a fixer or a ledger
disposition. Nothing here writes a file: the CLI stores proposals under `candidates/ai/`, apart from verified knowledge.
"""

import copy
import json
from dataclasses import dataclass, field

from odooflux.knowledge import validator as v

__all__ = ["CATEGORY", "ORIGIN", "REPLY_SCHEMA", "ProposalRequest", "propose", "excerpt_for"]

CATEGORY = "evidence_excerpt"
ORIGIN = "AI_PROPOSED"
RATIONALE_MAX = 500
MAX_OUTPUT_TOKENS = 300
SYSTEM = ("You help review a candidate rule for an Odoo version change. You see one evidence excerpt and the change "
          "fields. Reply with one JSON object only: rationale (a short human-readable sentence) and template_hint "
          "(one of allowed_template_ids, or an empty string). Do not decide anything; a human reviews your reply.")
CHANGE_FIELDS = ("class", "domain", "kind", "step", "subject_key")


@dataclass
class ProposalRequest:
    """The request shape the gateway reads (the attributes of `odooflux.ai.providers.types.AIRequest`)."""

    request_id: str
    model: str
    system: str
    messages: list
    response_schema: dict
    max_output_tokens: int
    budget_ref: str
    cache_key: str
    region: dict
    provider: str = ""
    data_categories: tuple = ()
    rule_id: str = ""
    meta: dict = field(default_factory=dict)


def reply_schema(template_ids) -> dict:
    """The closed reply schema. `template_hint` is one of the known template ids, or the empty string."""
    return {"type": "object", "additionalProperties": False, "required": ["rationale", "template_hint"],
            "properties": {"rationale": {"type": "string", "minLength": 1, "maxLength": RATIONALE_MAX},
                           "template_hint": {"type": "string", "enum": [""] + sorted(template_ids)}}}


REPLY_SCHEMA = reply_schema(())


def excerpt_for(candidate: dict, evidence_by_id: dict) -> str:
    """The evidence text sent for `candidate`: each cited record's description and location labels. No file content."""
    parts = []
    for ev_id in candidate["rule"].get("evidence") or []:
        record = evidence_by_id.get(ev_id)
        if record is None:
            continue
        parts.append(str(record.get("description", "")))
        parts.extend(str(loc.get("match", "")) for loc in record.get("locations") or [])
    return "\n".join(p for p in parts if p)


def _count(text) -> int:
    """Rough token estimate for the job budget (ceil of bytes / 4), used when the reply reports no usage."""
    return -(-len(str(text).encode("utf-8", errors="replace")) // 4)


def _usage(resp) -> int:
    usage = getattr(resp, "usage", None)
    return int(getattr(usage, "input", 0) or 0) + int(getattr(usage, "output", 0) or 0)


def _parse_reply(text: str, template_ids) -> tuple:
    """(proposal fields or None, reason or None). The whole reply is discarded on any problem."""
    try:
        data = json.loads(text or "")
    except (TypeError, ValueError):
        return None, "not_json"
    if not isinstance(data, dict):
        return None, "not_object"
    if v.check(data, reply_schema(template_ids)):
        return None, "schema_violation"
    return {"rationale": data["rationale"], "template_hint": data["template_hint"]}, None


def _request(candidate, change, excerpt, *, config, template_ids) -> ProposalRequest:
    payload = {"allowed_template_ids": sorted(template_ids),
               "change": {k: change.get(k) for k in CHANGE_FIELDS}, "excerpt": excerpt}
    return ProposalRequest(
        request_id=candidate["candidate_id"], model=config["model"], system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, sort_keys=True, separators=(",", ":"))}],
        response_schema=reply_schema(template_ids), max_output_tokens=MAX_OUTPUT_TOKENS, budget_ref="job",
        cache_key="", region={"path": f"candidates/{candidate['candidate_id']}.json"}, provider=config["provider"],
        data_categories=(CATEGORY,))


def _empty(status: str, **extra) -> dict:
    return {"status": status, "proposals": [], "discarded": [], "denied": [], "skipped": [], "calls": [],
            "events": [], **extra}


def propose(candidates, *, evidence, changes, gateway, authorizer, config: dict, template_ids) -> dict:
    """Proposals for the PROPOSED `candidates`. See the module docstring. Inputs are never mutated.

    `evidence` is a list of EvidenceRecords and `changes` a list or mapping of ledger records (by change_id).
    Returns a dict with status: off | kill_switch | denied | ok. `status` denied also carries `missing`."""
    if not config.get("enabled"):
        return _empty("off")
    if config.get("kill_switch"):
        return _empty("kill_switch", events=[{"level": "INFO", "code": "AI_KILL_SWITCH",
                                              "detail": "no transmission; AI proposals skipped"}])
    missing = list(authorizer.missing(config["provider"], (CATEGORY,)))
    if missing:
        return _empty("denied", missing=missing, events=[{"level": "INFO", "code": "AI_GRANT_MISSING",
                                                          "detail": "missing grant: " + ",".join(missing)}])
    evidence_by_id = {r["id"]: copy.deepcopy(r) for r in evidence}
    change_by_id = changes if isinstance(changes, dict) else {r["change_id"]: r for r in changes}
    out = _empty("ok", missing=[])
    budget = config.get("budget_job_tokens")
    spent = 0
    template_ids = sorted(template_ids)
    for candidate in sorted((copy.deepcopy(c) for c in candidates), key=lambda c: c["candidate_id"]):
        cid = candidate["candidate_id"]
        if candidate.get("status") != "PROPOSED":
            out["skipped"].append({"candidate_id": cid, "reason": "not_proposed"})
            continue
        change = change_by_id.get(candidate["change_id"])
        excerpt = excerpt_for(candidate, evidence_by_id)
        if change is None or not excerpt:
            out["skipped"].append({"candidate_id": cid, "reason": "no_evidence_excerpt"})
            continue
        if budget is not None and spent >= budget:
            out["skipped"].append({"candidate_id": cid, "reason": "budget_exhausted"})
            continue
        req = _request(candidate, change, excerpt, config=config, template_ids=template_ids)
        try:
            resp = gateway.complete(req)
        except Exception as exc:  # noqa: BLE001  record the class only; no fallback to another provider
            out["denied"].append({"candidate_id": cid, "reason": "gateway_error:" + type(exc).__name__})
            continue
        spent += _usage(resp) or _count(req.messages[0]["content"])
        base = {"candidate_id": cid, "provider": config["provider"], "model": config["model"], "category": CATEGORY,
                "input_tokens": int(getattr(getattr(resp, "usage", None), "input", 0) or 0),
                "output_tokens": int(getattr(getattr(resp, "usage", None), "output", 0) or 0)}
        if getattr(resp, "error_kind", None):
            out["denied"].append({"candidate_id": cid, "reason": resp.error_kind})
            out["calls"].append({**base, "outcome": "error:" + resp.error_kind})
            continue
        if getattr(resp, "stop_reason", "complete") != "complete":
            out["discarded"].append({"candidate_id": cid, "reason": "truncated"})
            out["calls"].append({**base, "outcome": "rejected:truncated"})
            continue
        fields, reason = _parse_reply(getattr(resp, "text", ""), template_ids)
        if reason:
            out["discarded"].append({"candidate_id": cid, "reason": reason})
            out["calls"].append({**base, "outcome": "rejected:" + reason})
            continue
        out["proposals"].append({"ai_proposed": True, "candidate_id": cid, "change_id": candidate["change_id"],
                                 "origin": ORIGIN, **fields})
        out["calls"].append({**base, "outcome": "accepted"})
    return out
