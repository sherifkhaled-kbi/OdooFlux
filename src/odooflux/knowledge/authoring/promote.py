"""Verb `promote` (T025; contracts/manual-rule-cli.md "promote" and "Promotion gates"; REQ-KAP-018).

`promote` is the only path to FIX_ENABLED. It:
1. requires a non-empty approval reference that is not the promoter's own identity (no self-approval; the approval is
   recorded, never generated here);
2. runs promotion gates 1 to 5 (release/safety.py, provenance-backed) on an in-memory copy of the tree in which the rule
   is already FIX_ENABLED, so the authoring checks see the rule as it would be after promotion;
3. on success writes one `promote` revision to the history sidecar through the same transactional path as the other
   verbs (validation of the whole tree; rollback on a new ERROR).

A refusal raises `PromoteError` carrying the failing gate findings and writes nothing. Built-in rules (no origin or
origin BUILTIN) are grandfathered and are not promoted through this verb.
"""

from pathlib import Path

from odooflux.knowledge.authoring import ops
from odooflux.knowledge.loader import load_knowledge
from odooflux.knowledge.release.safety import BUILTIN_ORIGINS, FIX_ENABLED, gate_findings, load_provenance_index
from odooflux.knowledge.update.certification import REFERENCE_PREFIX


class PromoteError(ops.OpsError):
    """Promotion refused: no approval, a failed gate, or a rule that cannot be promoted. Nothing was written."""

    def __init__(self, message: str, findings=()):
        super().__init__(message)
        self.findings = list(findings)


def _approval_ref(approval, promoter: str) -> str:
    ref = approval.strip() if isinstance(approval, str) else ""
    if not ref:
        raise PromoteError("promotion needs a non-empty approval reference (--approval)")
    if ref.lower() in (promoter.lower(), "unknown"):
        raise PromoteError("the approval reference cannot be the promoter's own identity (no self-approval)")
    if ref.lower().startswith(f"{REFERENCE_PREFIX}:"):
        raise PromoteError("an automated certification reference (auto-cert:) is not a human approval")
    return ref


def _describe(findings) -> str:
    return "; ".join(f"gate {f['gate']} {f['code']}: {f['detail']}" for f in findings)


def promote(tree, rule_id: str, *, approval, author=None, at=None, provenance=None) -> dict:
    tree = Path(tree)
    promoter = ops.resolve_author(author)
    ref = _approval_ref(approval, promoter)
    _, row = ops._find(tree, rule_id)
    if row.get("origin") in BUILTIN_ORIGINS:
        raise PromoteError(f"{rule_id} is a built-in rule and is not promoted through this verb")
    if row.get("maturity") == "RETIRED":
        raise PromoteError(f"{rule_id} is retired and cannot be promoted")
    if row.get("maturity") == FIX_ENABLED:
        raise PromoteError(f"{rule_id} is already FIX_ENABLED")
    previous = row.get("maturity")

    candidate = {**row, "maturity": FIX_ENABLED}
    kb = load_knowledge(tree)
    kb.rules = [candidate if r.get("id") == rule_id else r for r in kb.rules]
    findings = [f for f in gate_findings(kb, load_provenance_index(tree, provenance), include_builtin=True)
                if f["rule_id"] == rule_id]
    if findings:
        raise PromoteError(f"promotion of {rule_id} refused, failing gates: {_describe(findings)}", findings)

    def change(new, _doc):
        new["maturity"] = FIX_ENABLED
        return new, {"previous_maturity": previous, "approval": ref, "gates": "1-5 passed"}

    return ops._revise(tree, rule_id, action="promote", change=change,
                       summary=f"promoted to FIX_ENABLED (approval {ref})", author=author, at=at)
