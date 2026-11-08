"""Shared shape of generic rules: the rule identity passed in by a binding, and builders for Finding and Edit.

Detectors take ``(document, ctx, **params)`` and return ``Finding`` values; fixers take the same arguments
and return engine ``Edit`` values for ``core.engine.edits.apply_edits``. Nothing here reads or writes files.
"""

from dataclasses import dataclass

from odooflux.core.contracts.records import SEVERITIES, Finding
from odooflux.core.engine.documents import Document, Span
from odooflux.core.engine.edits import Edit


@dataclass(frozen=True)
class RuleContext:
    """Identity and reporting text of one bound rule (from its metadata row)."""

    rule_id: str
    severity: str
    step: str
    message: str = ""
    suggestion: str = ""

    def __post_init__(self):
        if not self.rule_id:
            raise ValueError("rule_id is required")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")


def finding(document: Document, ctx: RuleContext, span: Span) -> Finding:
    """A finding at the line where ``span`` starts."""
    return Finding(rule_id=ctx.rule_id, path=document.path, line=document.line_col(span.start)[0],
                   severity=ctx.severity, message=ctx.message, suggestion=ctx.suggestion,
                   matched=document.text[span.start:span.end])


def edit(document: Document, ctx: RuleContext, span: Span, after: str, *, op: str, validation) -> Edit:
    """Replace ``span`` with ``after``. The id is stable for the rule, operation and span."""
    return Edit(
        id=f"{ctx.rule_id}:{op}:{span.start}-{span.end}", rule_id=ctx.rule_id, path=document.path,
        start=span.start, end=span.end, before=document.text[span.start:span.end], after=after,
        severity=ctx.severity, step=ctx.step, validation=tuple(validation))
