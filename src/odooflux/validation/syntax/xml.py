"""L1 validator for XML views, data, and QWeb files (well-formedness, stdlib ElementTree)."""

import xml.etree.ElementTree as ET

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.records import ValidationResult


class XmlSyntaxValidator:
    key = "syntax.xml"
    contract_version = CONTRACT_VERSION
    layer = 1

    def applies_to(self, path: str) -> bool:
        return path.endswith(".xml")

    def validate(self, path: str, text: str) -> ValidationResult:
        try:
            ET.fromstring(text.encode("utf-8"))
        except ET.ParseError as exc:
            return ValidationResult(layer=1, outcome="FAIL", reason=f"XML is not well-formed: {exc}")
        return ValidationResult(layer=1, outcome="PASS")
