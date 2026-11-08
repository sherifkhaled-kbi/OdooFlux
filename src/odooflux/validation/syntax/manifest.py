"""L1 validator for manifests: must be a literal dict (``ast.literal_eval``)."""

import ast

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.records import ValidationResult
from odooflux.discovery.manifest import MANIFEST_NAMES


class ManifestSyntaxValidator:
    key = "syntax.manifest"
    contract_version = CONTRACT_VERSION
    layer = 1

    def applies_to(self, path: str) -> bool:
        return path.rsplit("/", 1)[-1] in MANIFEST_NAMES

    def validate(self, path: str, text: str) -> ValidationResult:
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError, TypeError) as exc:
            return ValidationResult(layer=1, outcome="FAIL", reason=f"Manifest SyntaxError: {exc}")
        if not isinstance(value, dict):
            return ValidationResult(layer=1, outcome="FAIL", reason="Manifest is not a literal dict")
        return ValidationResult(layer=1, outcome="PASS")
