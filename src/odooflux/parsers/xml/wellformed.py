"""XML parser adapter: well-formedness only (spans come in P4)."""

import xml.etree.ElementTree as ET

from odooflux.core.contracts import CONTRACT_VERSION


class XmlParser:
    key = "xml"
    contract_version = CONTRACT_VERSION

    def parse(self, text: str):
        try:
            ET.fromstring(text.encode("utf-8"))
        except ET.ParseError as exc:
            return str(exc)
        return None
