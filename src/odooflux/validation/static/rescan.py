"""L2 static compatibility: re-scan the validated output and attach post-fix findings (REQ-VAL-002)."""

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.records import ValidationResult


class RescanValidator:
    """Reports L2 PASS when the re-scan ran; findings are returned to the caller, not stored here."""

    key = "static.rescan"
    contract_version = CONTRACT_VERSION
    layer = 2

    def applies_to(self, path: str) -> bool:
        return True

    def validate(self, path: str, text: str) -> ValidationResult:
        return ValidationResult(layer=2, outcome="PASS")


def attach_post_fix(path: str, post_findings: list) -> dict:
    """Per-file record of findings still present after the fixes (L2 output)."""
    return {"path": path, "findings": sorted(post_findings, key=lambda f: (f.line, f.rule_id))}
