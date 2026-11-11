"""L1 validator for Python sources (REQ-PY-004). Stdlib ``compile()`` only: a syntax check, nothing is executed."""

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
            compile(text, path, "exec", dont_inherit=True)
        except SyntaxError as exc:  # compile() also reports compile-time errors ast.parse does not (for example
            # a module-level return); a null byte raises ValueError instead
            return ValidationResult(layer=1, outcome="FAIL",
                                    reason=f"Python SyntaxError at line {exc.lineno}: {exc.msg}")
        except ValueError as exc:
            return ValidationResult(layer=1, outcome="FAIL", reason=f"Python source rejected: {exc}")
        return ValidationResult(layer=1, outcome="PASS")
