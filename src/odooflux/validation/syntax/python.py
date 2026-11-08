"""L1 validator for Python sources (REQ-PY-004). Stdlib ``ast`` only."""

import ast

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.records import ValidationResult
from odooflux.discovery.manifest import MANIFEST_NAMES


class PythonSyntaxValidator:
    key = "syntax.python"
    contract_version = CONTRACT_VERSION
    layer = 1

    def applies_to(self, path: str) -> bool:
        return path.endswith(".py") and path.rsplit("/", 1)[-1] not in MANIFEST_NAMES

    def validate(self, path: str, text: str) -> ValidationResult:
        try:
            ast.parse(text)
        except SyntaxError as exc:
            return ValidationResult(layer=1, outcome="FAIL",
                                    reason=f"Python SyntaxError at line {exc.lineno}: {exc.msg}")
        return ValidationResult(layer=1, outcome="PASS")
