"""L1 validator for JavaScript sources (REQ-JS-004) and the detect-only downgrade for JS rules (REQ-JS-001).

The tree-sitter adapter is optional (D-02, ADR-006) and is injected, not imported here. An adapter
is any object with ``available() -> bool`` and ``has_errors(text) -> bool | None`` (``None`` when it
cannot decide). Without an adapter the validator reports UNAVAILABLE and never fails a file.
"""

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.records import ValidationResult

NEEDS_REVIEW = "NEEDS_REVIEW"

UNAVAILABLE_REASON = "JavaScript parser adapter not installed; JS syntax not checked (ADR-006)"


def _adapter_ready(adapter) -> bool:
    return adapter is not None and bool(adapter.available())


class JavaScriptSyntaxValidator:
    key = "syntax.javascript"
    contract_version = CONTRACT_VERSION
    layer = 1

    def __init__(self, adapter=None):
        self._adapter = adapter

    def applies_to(self, path: str) -> bool:
        return path.endswith(".js")

    def validate(self, path: str, text: str) -> ValidationResult:
        if not _adapter_ready(self._adapter):
            return ValidationResult(layer=1, outcome="UNAVAILABLE", reason=UNAVAILABLE_REASON)
        errors = self._adapter.has_errors(text)
        if errors is None:
            return ValidationResult(layer=1, outcome="UNAVAILABLE", reason=UNAVAILABLE_REASON)
        if errors:
            return ValidationResult(layer=1, outcome="FAIL",
                                    reason="JavaScript parse tree contains error or missing nodes")
        return ValidationResult(layer=1, outcome="PASS")


def detect_only_plan(adapter, edits, findings):
    """Downgrade hook for JS rules. Returns ``(edits_to_apply, status_floor)``.

    With the adapter, edits go through unchanged and the rule sets no floor. Without it, JS is
    detect-only: no edits are applied, and any detection or planned edit floors the file at
    NEEDS_REVIEW.
    """
    if _adapter_ready(adapter):
        return list(edits), None
    if edits or findings:
        return [], NEEDS_REVIEW
    return [], None
